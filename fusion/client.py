# Adapted from hermes-labs-plugins (MIT); see THIRD_PARTY.md.
"""GitHub Copilot CLI (``copilot --acp --stdio``) client: the generic ACP client plus Copilot's quirks."""

from __future__ import annotations

import base64
import binascii
import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path
from contextvars import ContextVar, copy_context
from dataclasses import dataclass, field
import re
import queue
import threading
from types import SimpleNamespace
from uuid import uuid4
from typing import Any

from .transport import ACPClient, _model_selection_request, _session_model_ids


def _native_protocol(meta):
    return isinstance(meta, dict) and type(meta.get('hermesToolIntentVersion')) is int and meta['hermesToolIntentVersion'] == 1


def _native_schemas(tools, choice=None):
    tools = [] if tools is None else tools
    if not isinstance(tools, list) or len(tools) > 256:
        raise RuntimeError('Invalid native tool schema count')
    try:
        encoded = json.dumps(tools, ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(encoded) > 2 * 1024 * 1024:
            raise RuntimeError('Native tool schema payload is too large')
        tools = json.loads(encoded)  # Own an immutable-in-practice snapshot for this turn.
    except (ValueError, TypeError, UnicodeError) as exc:
        raise RuntimeError('Invalid native tool schema payload') from exc
    names = set()
    for tool in tools:
        function = tool.get('function') if isinstance(tool, dict) and tool.get('type') == 'function' else None
        if not isinstance(function, dict):
            raise RuntimeError('Invalid native tool schema definition')
        name = function.get('name')
        if not isinstance(name, str) or re.fullmatch(r'[A-Za-z0-9_-]{1,128}', name) is None or name in names:
            raise RuntimeError('Invalid or duplicate native tool schema name; names are never repaired')
        if not isinstance(function.get('parameters', {}), dict) or not isinstance(function.get('description', ''), str):
            raise RuntimeError('Invalid native tool schema definition')
        names.add(name)
    if choice == 'none':
        return []
    if isinstance(choice, dict) and choice.get('type') == 'function':
        function = choice.get('function')
        name = function.get('name') if isinstance(function, dict) else None
        if not isinstance(name, str) or name not in names:
            raise RuntimeError('Native tool schema choice names an unavailable function')
        return [tool for tool in tools if tool['function']['name'] == name]
    if choice is not None and choice not in ('auto', 'required'):
        raise RuntimeError('Unsupported native tool schema choice')
    return tools


def _native_intents(result, schemas):
    meta = result.get('_meta') or {}
    if not isinstance(meta, dict):
        raise RuntimeError('Invalid native tool-intent metadata')
    if 'hermesToolCalls' not in meta:
        if 'hermesToolIntentVersion' in meta and not _native_protocol(meta):
            raise RuntimeError('Unsupported native tool-intent protocol version')
        return []
    if not _native_protocol(meta):
        raise RuntimeError('Unsupported native tool-intent protocol version')
    calls = meta['hermesToolCalls']
    if not isinstance(calls, list) or len(calls) > 32:
        raise RuntimeError('Invalid native tool-intent count')
    try:
        if len(json.dumps(calls, ensure_ascii=False, allow_nan=False).encode('utf-8')) > 1024 * 1024:
            raise RuntimeError('Native tool-intent payload is too large')
    except (ValueError, TypeError, UnicodeError) as exc:
        raise RuntimeError('Invalid native tool-intent payload') from exc
    allowed = {tool['function']['name'] for tool in schemas}
    ids = set()
    actions = set()
    for call in calls:
        if not isinstance(call, dict) or not isinstance(call.get('name'), str) or call['name'] not in allowed:
            raise RuntimeError('Copilot bridge returned an undeclared tool intent')
        call_id = call.get('id')
        if not isinstance(call_id, str) or not call_id or len(call_id) > 256 or call_id in ids:
            raise RuntimeError('Invalid or duplicate native tool-intent identifier')
        if not isinstance(call.get('arguments'), dict):
            raise RuntimeError('Native tool-intent arguments must be an object')
        action = (call['name'], json.dumps(call['arguments'], sort_keys=True, ensure_ascii=False, allow_nan=False))
        if action in actions:
            # Multiphase solvers can independently propose the same operation with
            # different IDs. Neither silently discard an ID nor repeat its effect.
            raise RuntimeError('Copilot returned indistinguishable parallel tool requests; refusing repeated execution')
        actions.add(action)
        ids.add(call_id)
    return calls

def copilot_child_environment(command: str, *, forward_token: bool = False, credential: str | None = None) -> dict[str, str]:
    from .transport import _build_subprocess_env
    env = _build_subprocess_env()
    env.pop('COPILOT_GITHUB_TOKEN', None)
    if forward_token or os.environ.get('HERMES_COPILOT_FORWARD_TOKEN') == '1':
        if Path(command).name not in ('weave-copilot', 'weave-copilot.exe'):
            raise RuntimeError('Scoped Copilot credential forwarding is only enabled for weave-copilot')
        from agent.secret_scope import get_secret
        token = (get_secret('COPILOT_GITHUB_TOKEN', '') if credential is None else credential) or ''
        token = token.strip()
        if not token:
            raise RuntimeError('Explicit Copilot credential forwarding requires COPILOT_GITHUB_TOKEN')
        # One provider credential only, after the normal sanitizer. Never repository/bot secrets.
        env['COPILOT_GITHUB_TOKEN'] = token
    return env


def webui_artifact_links(content, cwd):
    """Use the WebUI's existing safe file-URI handling for verified workspace outputs."""
    from urllib.parse import unquote
    root = Path(cwd).resolve()
    pieces = re.split(r'(```[\s\S]*?```|~~~[\s\S]*?~~~)', content)
    pattern = re.compile(r'(!?\[[^\]\n]*\]\()([^\s()]+)(\))')
    def replace(match):
        raw = match[2]
        if raw.startswith('sandbox:/') and not raw.startswith('sandbox://'):
            raw = raw[len('sandbox:'):]
        if ':' in raw or raw.startswith('#'):
            return match[0]
        path = Path(unquote(raw))
        try:
            target = (path if path.is_absolute() else root / path).resolve()
            if target.is_relative_to(root) and target.is_file():
                return match[1] + target.as_uri() + match[3]
        except (OSError, ValueError):
            pass
        return match[0]
    for i in range(0, len(pieces), 2):
        pieces[i] = pattern.sub(replace, pieces[i])
    return ''.join(pieces)


# Inline only: do not introduce URL fetching (and a new SSRF surface) here.
_MAX_IMAGE_BYTES = 10 * 1024 * 1024
_MAX_TOTAL_IMAGE_BYTES = 20 * 1024 * 1024
_MAX_IMAGES = 16
_IMAGE_HEADERS = {
    "image/png": lambda data: data.startswith(b"\x89PNG\r\n\x1a\n"),
    "image/jpeg": lambda data: data.startswith(b"\xff\xd8\xff"),
    "image/gif": lambda data: data.startswith((b"GIF87a", b"GIF89a")),
    "image/webp": lambda data: data.startswith(b"RIFF") and data[8:12] == b"WEBP",
}


@dataclass
class _Turn:
    images: dict[str, dict[str, str]] = field(default_factory=dict)
    image_capable: bool = False
    native_tool_capable: bool = False
    tool_schemas: list[dict[str, Any]] = field(default_factory=list)
    native_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    native_answer_text: str = ''
    session_id: str | None = None
    usage: Any = None
    usage_source: str | None = None
    fusion_events: list[dict[str, Any]] = field(default_factory=list)
    fusion_truncated: bool = False
    context: dict[str, int] | None = None
    progress: list[str] = field(default_factory=list)
    used_models: list[str] = field(default_factory=list)
    emit: Any = None
    process: Any = None
    process_lock: Any = field(default_factory=threading.RLock)
    process_released: bool = False
    cancelled: Any = field(default_factory=threading.Event)
    runtime_observe: bool = True
    runtime_request_id: str = field(default_factory=lambda: str(uuid4()))
    runtime_sequence: int = 0
    runtime_route: str = ''
    runtime_status: str = 'selecting'
    runtime_model: str | None = None
    runtime_role: str | None = None
    runtime_phase: Any = None
    runtime_lock: Any = field(default_factory=threading.RLock)
    runtime_ended: bool = False
    native_cancelled: bool = False


def _runtime_text(value):
    return value if isinstance(value, str) and 0 < len(value) <= 240 and value.isprintable() else None


def _runtime_snapshot(turn, status=None):
    """Keep request-local lifecycle only; no host-specific runtime UI dependency."""
    with turn.runtime_lock:
        if turn.runtime_ended:
            return
        if status is not None:
            turn.runtime_status = status
        turn.runtime_ended = turn.runtime_status in ('completed', 'interrupted', 'error')
        turn.runtime_sequence += 1


def _runtime_identity(turn, *, model, role=None, phase=None, phase_event=False):
    with turn.runtime_lock:
        if turn.runtime_ended:
            return
        changed = model != turn.runtime_model
        if phase_event:
            changed = changed or (phase, role) != (turn.runtime_phase, turn.runtime_role)
        if not changed:
            return
        # Even unknown-model occupancy must not be retrospectively attributed to
        # the first model. A new identity needs its own native occupancy update.
        turn.context = None
        turn.runtime_model = model
        if phase_event:
            turn.runtime_phase, turn.runtime_role = phase, role
        else:
            # _fleet/model describes the root assistant, not a phase's critic.
            # A different root identity cannot inherit that phase's role.
            turn.runtime_phase, turn.runtime_role = None, None
        _runtime_snapshot(turn, 'running')


class _LiveStream:
    """Bounded progress stream; cancellation owns only this turn's ACP process."""
    def __init__(self, client, messages, kwargs):
        self.client = client
        self.turn = _Turn()
        self.observer_context = copy_context()
        self.turn.runtime_route = _runtime_text(kwargs.get('model')) or getattr(client, 'placeholder_model', 'copilot-acp')
        _runtime_snapshot(self.turn, 'selecting')
        self.queue = queue.Queue(maxsize=64)
        self.stopped = self.turn.cancelled
        self.cached = []
        self.finished = False
        self.turn.emit = lambda text: self._put(('progress', text))
        def run():
            try:
                from .openai_bridge import completion_to_stream_chunks
                result = client._complete(messages, kwargs, self.turn)
                for chunk in completion_to_stream_chunks(result):
                    self._put(('chunk', chunk))
            except BaseException as exc:
                self._put(('error', exc))
            finally:
                self._put(('done', None))
        self.worker = threading.Thread(target=copy_context().run, args=(run,), daemon=True, name='copilot-acp-stream')
        self.worker.start()

    def _put(self, item):
        while not self.stopped.is_set():
            try:
                self.queue.put(item, timeout=.1)
                return
            except queue.Full:
                pass

    @property
    def hermes_acp_fusion_events(self):
        return list(self.turn.fusion_events)

    def __iter__(self):
        if self.finished:
            yield from self.cached
            return
        try:
            while not self.stopped.is_set():
                try:
                    kind, value = self.queue.get(timeout=.1)
                except queue.Empty:
                    continue
                if kind == 'done':
                    self.finished = True
                    break
                if kind == 'error':
                    raise value
                if kind == 'progress':
                    delta = SimpleNamespace(role='assistant', content=None, tool_calls=None,
                        reasoning_content=value, reasoning=value)
                    value = SimpleNamespace(choices=[SimpleNamespace(index=0, delta=delta, finish_reason=None)], usage=None)
                self.cached.append(value)
                yield value
        finally:
            self.close()

    async def __aiter__(self):
        import asyncio
        iterator = iter(self)
        def advance():
            try:
                return True, next(iterator)
            except StopIteration:
                return False, None
        try:
            while True:
                more, chunk = await asyncio.to_thread(advance)
                if not more:
                    break
                yield chunk
        finally:
            await asyncio.to_thread(self.close)

    def __getitem__(self, index):
        return list(self)[index]

    def close(self):
        self.stopped.set()
        self.observer_context.copy().run(_runtime_snapshot, self.turn, 'interrupted')
        if self.turn.process is not None:
            self.client._release_turn_process(self.turn)
        if threading.current_thread() is not self.worker:
            self.worker.join(timeout=3)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _progress(turn, text):
    if len(turn.progress) < 128:
        text = text[:600] + '\n'
        turn.progress.append(text)
        if turn.emit is not None:
            turn.emit(text)


def _usage(value: Any, *, native_call: bool = False) -> SimpleNamespace | None:
    """Only actual token counters, never context occupancy (used/size) or estimates.

    Native call events are snapshots, not deltas. Keep the latest, don't sum repeated
    notifications. A final prompt-level usage record takes precedence when present.
    """
    if not isinstance(value, dict):
        return None
    def counter(key):
        n = value.get(key)
        return n if type(n) is int and n >= 0 else None
    prompt = counter("input" if native_call else "inputTokens")
    completion = counter("output" if native_call else "outputTokens")
    if prompt is None or completion is None:
        return None
    total = counter("totalTokens") if not native_call else None
    if total is not None and total != prompt + completion:
        return None
    cached = counter("cacheRead" if native_call else "cachedReadTokens")
    reasoning = counter("reasoning" if native_call else "reasoningTokens")
    return SimpleNamespace(
        prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion,
        prompt_tokens_details=SimpleNamespace(cached_tokens=cached) if cached is not None and cached <= prompt else None,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=reasoning) if reasoning is not None and reasoning <= completion else None,
    )


# A cached client may serve overlapping callers: never keep per-turn data on self.
_TURN: ContextVar[_Turn | None] = ContextVar("copilot_acp_turn", default=None)


def _inline_image(url: Any) -> tuple[dict[str, str], int]:
    if not isinstance(url, str):
        raise ValueError("Copilot ACP images require an inline base64 data URL.")
    header, separator, data = url.partition(",")
    mime = header.removeprefix("data:").removesuffix(";base64")
    if not separator or header != f"data:{mime};base64" or mime not in _IMAGE_HEADERS:
        raise ValueError("Copilot ACP supports inline PNG, JPEG, GIF and WebP data URLs only; URLs are not fetched.")
    if not data or len(data) > 4 * ((_MAX_IMAGE_BYTES + 2) // 3):
        raise ValueError("Copilot ACP image exceeds the inline image size limit or is empty.")
    try:
        raw = base64.b64decode(data, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Invalid Copilot ACP image base64.") from exc
    if not raw or len(raw) > _MAX_IMAGE_BYTES or not _IMAGE_HEADERS[mime](raw):
        raise ValueError("Copilot ACP image data does not match its MIME type or size limit.")
    return {"type": "image", "data": data, "mimeType": mime}, len(raw)


def _image_messages(messages: list[dict[str, Any]], turn: _Turn) -> list[dict[str, Any]]:
    """Use opaque text slots so the core's transcript/tool formatter keeps its semantics."""
    result = []
    total = 0
    for message in messages:
        if not isinstance(message, dict) or not isinstance(message.get("content"), list):
            result.append(message)
            continue
        content = []
        for block in message["content"]:
            if isinstance(block, dict) and block.get("type") == "image_url":
                value = block.get("image_url")
                image, size = _inline_image(value.get("url") if isinstance(value, dict) else value)
                total += size
                if len(turn.images) >= _MAX_IMAGES or total > _MAX_TOTAL_IMAGE_BYTES:
                    raise ValueError("Copilot ACP inline image count or aggregate size limit exceeded.")
                slot = f"[hermes-image-{uuid4().hex}]"
                turn.images[slot] = image
                content.append({"type": "text", "text": slot})
            else:
                content.append(block)
        result.append({**message, "content": content})
    return result


# Stderr fingerprint of the deprecated `gh copilot` extension. Require BOTH the product name
# AND a deprecation marker: the NEW `@github/copilot` CLI legitimately mentions "copilot-cli".
_DEPRECATION_REQUIRED = ("gh-copilot",)
_DEPRECATION_MARKERS = ("has been deprecated", "no commands will be executed")
_DEPRECATED_CLI_ERROR = (
    "Hermes ACP mode requires the NEW GitHub Copilot CLI (github.com/github/copilot-cli), but the binary it just "
    "spawned is the deprecated `gh copilot` extension.\n\n"
    "Install the new CLI:\n  npm install -g @github/copilot\n  # then verify with: copilot --help\n\n"
    "If `copilot` already resolves to the new CLI but you still see this,\npoint Hermes at it explicitly:\n"
    "  export HERMES_COPILOT_ACP_COMMAND=/path/to/new/copilot\n\n"
    "Alternative: use the `copilot` provider (no ACP, hits the Copilot API\ndirectly with a Copilot subscription "
    "token) via `hermes setup`.\n\nOriginal error:\n"
)


def is_gh_copilot_deprecation_message(stderr_text: str) -> bool:
    """True iff stderr looks like the deprecated gh-copilot extension's banner."""
    lower = stderr_text.lower()
    return any(req in lower for req in _DEPRECATION_REQUIRED) and any(m in lower for m in _DEPRECATION_MARKERS)


class CopilotACPClient(ACPClient):
    """ACP client for the GitHub Copilot CLI."""

    def __init__(self, *, forward_copilot_token=True, require_native_tools=True, runtime_stream_only=False, **kwargs):
        # Public package is strict-only; old generic ACP escape hatches are not supported.
        if forward_copilot_token is not True or require_native_tools is not True:
            raise ValueError('Fusion requires strict native tools and scoped credentials')
        if kwargs.get('acp_command') is not None or kwargs.get('acp_args') is not None:
            raise ValueError('Legacy ACP launch overrides are not supported by strict Fusion')
        args = kwargs.get('args')
        if not isinstance(args, (list, tuple)) or len(args) != 4 or args[0] != '--copilot-cli' or not isinstance(args[1], str) or not args[1] or args[2:] not in (['--hydrafusion', '--hermes-tools-only'], ('--hydrafusion', '--hermes-tools-only')):
            raise ValueError('Fusion launch requires --copilot-cli <cli> --hydrafusion --hermes-tools-only')
        # Consume this plugin-only policy before the private transport sees its client kwargs.
        self._runtime_stream_only = runtime_stream_only
        self._forward_copilot_token = forward_copilot_token
        self._require_native_tools = require_native_tools
        self._copilot_credential = None
        if forward_copilot_token:
            from agent.secret_scope import get_secret, current_secret_scope
            if current_secret_scope() is not None:
                self._copilot_credential = get_secret('COPILOT_GITHUB_TOKEN', '') or ''
            else:
                from hermes_constants import get_hermes_home
                from tui_gateway.launch_profile_policy import owner_secret_scope
                # WebUI profile binding has no installed secret scope and can
                # clear ambient dotenv variables between tool iterations.
                owner = owner_secret_scope(get_hermes_home())
                self._copilot_credential = owner.get('COPILOT_GITHUB_TOKEN', '') or ''
        super().__init__(**kwargs)

    # Same launch spec as the copilot-acp profile's process_* fields (the fallback when a
    # caller passes no command/args).
    default_command = "weave-copilot"
    default_args = ('--copilot-cli', 'copilot', '--hydrafusion', '--hermes-tools-only')
    command_env_vars = ('HERMES_FUSION_BRIDGE',)
    args_env_var = 'HERMES_FUSION_ARGS'
    marker_base_url = "fusion://copilot"
    placeholder_model = "__fusion_unselected__"
    label = "Copilot ACP"
    missing_command_hint = "Install GitHub Copilot CLI or set HERMES_COPILOT_ACP_COMMAND/COPILOT_CLI_PATH."
    # The CLI keeps its own login (Hermes never reads it); `copilot login` is its terminal sign-in command.
    auth_required_hint = "Run `copilot login` to sign in to the GitHub Copilot CLI."
    unsupported_transport_hint = (
        "Either install a CLI that ships with --acp support (e.g. `@github/copilot` late 2025+), or set "
        "HERMES_COPILOT_ACP_COMMAND / HERMES_COPILOT_ACP_ARGS to a working pair.")

    def _spawn(self):
        turn = _TURN.get()
        if turn is not None and turn.cancelled.is_set():
            raise RuntimeError('Copilot ACP turn was cancelled before launch')
        if not self._forward_copilot_token and os.environ.get('HERMES_COPILOT_FORWARD_TOKEN') != '1':
            proc = super()._spawn()
        else:
            from hermes_cli._subprocess_compat import windows_hide_flags
            proc = subprocess.Popen([self._acp_command, *self._acp_args], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8',
                errors='replace', bufsize=1, cwd=self._acp_cwd,
                env=copilot_child_environment(self._acp_command, forward_token=self._forward_copilot_token, credential=self._copilot_credential),
                creationflags=windows_hide_flags())
            with self._active_process_lock:
                self._active_processes.add(proc)
                self.is_closed = False
        if turn is not None:
            with turn.process_lock:
                turn.process = proc
                # Popen/support probing can finish after close observed no process.
                if turn.cancelled.is_set():
                    self._release_turn_process(turn)
                    raise RuntimeError('Copilot ACP turn was cancelled during launch')
        return proc

    @staticmethod
    def _terminate_process(proc):
        # Both cancellation and ordinary session exit must reap the exact child.
        try:
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            with contextlib.suppress(Exception):
                proc.kill()
            with contextlib.suppress(Exception):
                proc.wait(timeout=2)

    def _release_turn_process(self, turn):
        # Close and the session's finally may race; exactly one owns retirement.
        with turn.process_lock:
            if turn.process is not None and not turn.process_released:
                turn.process_released = True
                super()._release_process(turn.process)

    def _release_process(self, proc):
        turn = _TURN.get()
        if turn is not None and turn.process is proc:
            self._release_turn_process(turn)
        else:
            super()._release_process(proc)

    def _create_chat_completion(self, *, messages=None, **kwargs):
        import asyncio
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            # Hermes auxiliaries also drive external-process clients from async code.
            return asyncio.to_thread(self._create_chat_completion, messages=messages, **kwargs)
        if kwargs.pop('stream', False):
            return _LiveStream(self, messages, kwargs)
        # WebUI auxiliary calls (for example title generation) share the worker
        # context, but their independent windows must not replace the chat meter.
        return self._complete(messages, kwargs, _Turn(runtime_observe=not self._runtime_stream_only))

    def _complete(self, messages, kwargs, turn):
        token = _TURN.set(turn)
        try:
            kwargs = {**kwargs, 'model': kwargs.get('model') or 'fusion-standard'}
            turn.runtime_route = _runtime_text(kwargs.get('model')) or 'fusion-standard'
            if turn.runtime_sequence == 0:
                _runtime_snapshot(turn, 'selecting')
            if self._require_native_tools:
                turn.tool_schemas = _native_schemas(kwargs.get('tools'), kwargs.get('tool_choice'))
                kwargs = {**kwargs, 'tools': None}
            response = super()._create_chat_completion(messages=_image_messages(messages or [], turn), stream=False, **kwargs)
            response.usage = turn.usage
            message = response.choices[0].message
            if self._require_native_tools:
                if turn.cancelled.is_set():
                    raise RuntimeError('Copilot ACP turn was cancelled before tool handoff')
                if turn.native_tool_calls:
                    from .openai_bridge import build_openai_tool_call
                    message.tool_calls = [build_openai_tool_call(call_id=call['id'], name=call['name'],
                        arguments=json.dumps(call['arguments'], ensure_ascii=False)) for call in turn.native_tool_calls]
                    message.content = None
                    response.choices[0].finish_reason = 'tool_calls'
                else:
                    # The upstream text parser may consume literal tool-call examples.
                    # Restore the actual answer, but never execute its parsed text.
                    message.tool_calls = None
                    message.content = turn.native_answer_text
                    response.choices[0].finish_reason = 'stop'
            if message.content and not getattr(message, 'tool_calls', None):
                message.content = webui_artifact_links(message.content, self._acp_cwd)
            if turn.emit is None and turn.progress:
                message = response.choices[0].message
                native = getattr(message, 'reasoning_content', None) or ''
                message.reasoning_content = ''.join(turn.progress) + native
                message.reasoning = message.reasoning_content
            response.hermes_acp_context = turn.context
            response.hermes_acp_used_models = list(turn.used_models)
            response.hermes_acp_usage_source = turn.usage_source
            response.hermes_acp_fusion_events = list(turn.fusion_events)
            response.hermes_acp_fusion_events_truncated = turn.fusion_truncated
            _runtime_snapshot(turn, 'interrupted' if turn.cancelled.is_set() or turn.native_cancelled else 'completed')
            return response
        except BaseException:
            _runtime_snapshot(turn, 'interrupted' if turn.cancelled.is_set() or turn.native_cancelled else 'error')
            raise
        finally:
            _TURN.reset(token)

    def list_models(self, *, timeout_seconds=15.0):
        token = _TURN.set(_Turn())
        try:
            with self._session(timeout_seconds, allow_file_requests=False) as (session, _):
                if not _native_protocol(session.get('_meta')):
                    raise RuntimeError('Copilot bridge did not acknowledge native tool schemas')
                return _session_model_ids(session, self.model_entry_disabled)
        finally:
            _TURN.reset(token)

    def _hermes_session_new_params(self, params):
        turn = _TURN.get()
        if not self._require_native_tools or turn is None:
            return params
        if not turn.native_tool_capable:
            raise RuntimeError('Copilot bridge does not support native Hermes tool intents; refusing text fallback')
        return {**params, '_meta': {**(params.get('_meta') or {}), 'hermesToolSchemas': turn.tool_schemas}}

    def _run_prompt(self, prompt_text: str, *, timeout_seconds: float, model: str | None = None):
        turn = _TURN.get()
        with self._session(timeout_seconds) as (session, request):
            if turn is not None:
                turn.session_id = session["sessionId"]
            if self._require_native_tools:
                if not _native_protocol(session.get('_meta')):
                    raise RuntimeError('Copilot bridge did not acknowledge native tool schemas')
                preamble = getattr(sys.modules[ACPClient.__module__], '_PROMPT_PREAMBLE', ())
                prefix = '\n\n'.join(part.strip() for part in preamble) + '\n\n'
                if not preamble or not prompt_text.startswith(prefix):
                    raise RuntimeError('Upstream ACP prompt preamble changed; refusing conflicting tool instructions')
                prompt_text = ('You are the active Copilot backend for Hermes. Use the registered native functions '
                    'to request Hermes tools; their names are transport aliases. Hermes alone executes actions '
                    'and handles approvals. A request ends this response and actual results arrive in the next '
                    'conversation turn. Never claim an action ran before its actual Hermes result. Do not emit '
                    'text tool-call tags or JSON instead of invoking a registered function.\n\n' + prompt_text[len(prefix):])
            if model and model != self.placeholder_model:
                if model not in _session_model_ids(session, self.model_entry_disabled):
                    raise RuntimeError(f"{self.label} requested model is unavailable; refusing session-default fallback.")
                selection = _model_selection_request(session, model, placeholder=self.placeholder_model,
                                                     disabled=self.model_entry_disabled)
                if selection is None:
                    raise RuntimeError(f"{self.label} cannot select the requested model; refusing fallback.")
                # Selection failures deliberately propagate: never run the prompt on another model.
                selected = request(*selection)
                if isinstance(selected, dict):
                    current = (selected.get("models") or {}).get("currentModelId")
                    options = selected.get("configOptions") or []
                    currents = [o.get("currentValue") for o in options if isinstance(o, dict)
                                and "model" in (o.get("category"), o.get("id"))]
                    if (current is not None and current != model) or any(c != model for c in currents):
                        raise RuntimeError(f"{self.label} acknowledged a different model; refusing fallback.")
            blocks = [{"type": "text", "text": prompt_text}]
            if turn is not None and turn.images:
                if not turn.image_capable:
                    raise RuntimeError("Copilot ACP agent did not advertise image prompt support.")
                slots = re.compile("(" + "|".join(re.escape(s) for s in turn.images) + ")")
                blocks = [turn.images[part] if part in turn.images else {"type": "text", "text": part}
                          for part in slots.split(prompt_text) if part]
            text_parts, reasoning_parts = [], []
            result = request("session/prompt", {"sessionId": session["sessionId"], "prompt": blocks},
                             text_parts=text_parts, reasoning_parts=reasoning_parts)
            if turn is not None and isinstance(result, dict):
                turn.native_cancelled = result.get('stopReason') == 'cancelled'
                if self._require_native_tools:
                    if result.get('stopReason') == 'cancelled' or turn.cancelled.is_set():
                        raise RuntimeError('Copilot ACP turn was cancelled before tool handoff')
                    turn.native_tool_calls = _native_intents(result, turn.tool_schemas)
                    turn.native_answer_text = ''.join(text_parts)
                if (usage := _usage(result.get("usage"))) is not None:
                    turn.usage, turn.usage_source = usage, "session/prompt"
            return "".join(text_parts), "".join(reasoning_parts)

    def _handle_server_message(self, msg, **kwargs):
        turn = _TURN.get()
        if turn is not None and msg.get("id") == 1 and "method" not in msg:
            result = msg.get("result") or {}
            turn.image_capable = ((result.get("agentCapabilities") or {}).get("promptCapabilities") or {}).get("image") is True
            turn.native_tool_capable = _native_protocol(result.get('_meta'))
        if msg.get('method') == '_fleet/model' and 'id' not in msg:
            params = msg.get('params')
            if turn is not None and turn.session_id is not None and isinstance(params, dict) and params.get('sessionId') == turn.session_id:
                model = params.get('model')
                if _runtime_text(model) is not None:
                    _runtime_identity(turn, model=model)
                if isinstance(model, str) and model and model not in turn.used_models and len(turn.used_models) < 32:
                    turn.used_models.append(model[:240])
                    _progress(turn, 'Copilot used model: ' + model[:240])
            return True
        if msg.get('method') == '_fleet/fusion' and 'id' not in msg:
            params = msg.get('params')
            if turn is not None and turn.session_id is not None and isinstance(params, dict) and params.get('sessionId') == turn.session_id:
                if params.get('event') == 'phase_started':
                    model, role, phase = (params.get(k) for k in ('model', 'role', 'phase'))
                    index = params.get('index')
                    valid_index = index is None or type(index) is int and 0 <= index <= 2**63 - 1
                    if all(v is None or _runtime_text(v) is not None for v in (model, role, phase)) and valid_index:
                        _runtime_identity(turn, model=model, role=role, phase=(phase, index), phase_event=True)
                if len(turn.fusion_events) < 128:
                    allowed = ('event', 'pattern', 'phase', 'role', 'model', 'status', 'hint',
                               'durationMs', 'credits', 'totalCredits', 'requests', 'index')
                    event = {k: (v[:512] if isinstance(v, str) else v) for k, v in params.items()
                             if k in allowed and (v is None or type(v) in (str, int, float, bool))}
                    turn.fusion_events.append(event)
                    if event.get('event') == 'phase_started':
                        _progress(turn, f"Fusion · {event.get('pattern', 'route')} · {event.get('role', 'model')}: {event.get('model', 'unknown')}")
                    elif event.get('event') == 'completed':
                        _progress(turn, 'Fusion · completed')
                else:
                    turn.fusion_truncated = True
            return True
        if msg.get("method") == "session/update":
            params = msg.get("params") or {}
            # Text/reasoning must share the same turn-local ownership fence as usage.
            # Before session/new completes there is no session authorized to publish.
            if turn is None or turn.session_id is None or not isinstance(params, dict) or params.get("sessionId") != turn.session_id:
                return True
            update = params.get("update") or {}
            if isinstance(update, dict) and update.get("sessionUpdate") == "usage_update":
                used, size = update.get('used'), update.get('size')
                if type(used) is int and type(size) is int and 0 <= used <= size and size > 0:
                    context = {'used': used, 'size': size}
                    if context != turn.context:
                        turn.context = context
                        _runtime_snapshot(turn, 'running')
                        _progress(turn, f'Copilot runtime context: {used} / {size} tokens')
                meta = update.get("_meta") or {}
                usage = _usage(meta.get("call") if isinstance(meta, dict) else None, native_call=True)
                if usage is not None:
                    turn.usage, turn.usage_source = usage, "usage_update._meta.call"
        return super()._handle_server_message(msg, **kwargs)

    def model_entry_disabled(self, entry: dict[str, Any]) -> bool:
        """Copilot marks org-policy-disabled models with ``_meta.copilotEnablement: disabled``."""
        return str((entry.get("_meta") or {}).get("copilotEnablement") or "").strip().lower() == "disabled"

    def early_exit_error(self, stderr_text: str) -> str | None:
        return _DEPRECATED_CLI_ERROR + stderr_text if is_gh_copilot_deprecation_message(stderr_text) else None
