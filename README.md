# Copilot Fusion provider (0.1.0)

## Install from GitHub

Install into the profile that should use Fusion (repeat for each intended profile):

```sh
hermes plugins install mossyhub/hermes-copilot-fusion
```

For a named profile use `hermes -p PROFILE plugins install mossyhub/hermes-copilot-fusion`. Review the normal host scan/consent prompts; do not disable security scanning. The repository manifest declares `kind: model-provider` and the provider ID is `copilot-fusion`.

**Dependencies are separate.** Install GitHub's official [Copilot CLI](https://github.com/github/copilot-cli#installation) from its official distribution; upstream [releases and checksums](https://github.com/github/copilot-cli/releases) are authoritative. This repository does not redistribute the CLI. You also need the native-tool bridge from [weave-copilot hermes-tools-v0.1.0](https://github.com/mossyhub/weave-copilot/releases/tag/hermes-tools-v0.1.0). That Linux x64 self-contained SDK host is built from commit `4cecc41f71a36ff124f32c720736fc80e6473b3e`; its `weave-copilot` asset SHA-256 is `96a5875e50e6ec14ae8e3a5463b3fd41544b013d102eaf191a3ff0a6f09569e8`. Verify its `SHA256SUMS` before making it executable. The required source branch is `feat/hermes-external-tools`, not the fork's upstream-only main branch.

Set `HERMES_FUSION_BRIDGE` and `HERMES_FUSION_ARGS` in the intended profile's environment using the absolute paths shown below, and configure that owner's `COPILOT_GITHUB_TOKEN` through supported private secret setup. No token belongs in Git or a shared command. Select provider `copilot-fusion`, model `fusion-standard` (or `fusion-high` / `fusion-max`) and base URL `fusion://copilot` through the usual model settings. Start a fresh session; the three Fusion rows appear when the live bridge catalog enables those aliases. Native model/context reports appear under **Processed → Thinking**. Auxiliary tasks are separate calls; configure them deliberately.

The published v0.1.0 archive is the independently qualified original package, SHA-256 `3c92926ab5174fb209bfbbff6f477753e37c7a2ad1b83ade7f102f941cd3f0c9`, not a rebuild of this publication checkout. Runtime, scripts, tests, manifest and licenses are byte-identical to that archive; this README adds publication setup and the repository adds CI/publication metadata. See [publication provenance](https://github.com/mossyhub/hermes-copilot-fusion/blob/main/PUBLISHING.md). The archive's original README has an older separate bridge build reference; use the release and checksum above for the published Linux bridge.

## Provider-only WebUI experience

This package deliberately leaves Hermes/WebUI source unchanged. The ordinary picker exposes three rows rather than a custom Fusion/Effort widget. Expand the native **Processed → Thinking** section to see Copilot's actual reported model and context snapshots. The custom always-visible runtime row, dynamic per-phase context ring, expanded phase inspector and `_fusionRuntime` persistence from the separate rich lab are **not included**. The stock usage meter must not be interpreted as the SDK's per-phase occupancy meter.

Normal tools/approvals, images, file links, live progress, Stop and direct-API overrides use the host's existing interfaces. Final-answer text is delivered after validation, not token-by-token. This remains a fresh SDK session with a replayed textual transcript per inference; it is not the proposed persistent-SDK redesign or proof of native API equivalence/token savings. Historical tool-call IDs/arguments/results are retained as replay data, but arbitrary native history import is not claimed.

Auxiliary tasks are separate inference calls. If left on `auto`, they may select Fusion too; displaying fewer runtime events does not remove their cost. Configure appropriate auxiliary provider/model choices from your account's actual catalog rather than assuming a universal cheap model. The isolated live candidate explicitly routed title generation to its existing direct-API provider.

Current package qualification is described in COMPATIBILITY.md. SDK/CLI versions and hashes are test receipts, not an instruction to permanently freeze updates. Update dependencies as separately qualified candidates and keep the last-known-good package when compatibility fails; no AI routine or host source-splicing step is part of this package.

Standalone Hermes **model-provider** plugin. It installs through ordinary provider discovery, registers only `copilot-fusion`, and supplies its own ACP client through `ProviderProfile.create_client`. It does not replace `copilot`, `copilot-acp`, or any global factory; no core/WebUI/bootstrap patches are included or needed.

## Behavior

* Normal model catalog rows: **Fusion Standard**, **Fusion High**, **Fusion Max**, only when their exact aliases are enabled in the bridge's live session catalog. No advertised alias is silently substituted. Enabled concrete leaf IDs remain selectable explicitly, but are not added to these three picker rows.
* `supports_streaming=True`: bounded live **native progress/reasoning** followed by the validated final answer/tool-call chunks. This is not token-by-token final-answer streaming. Actual model and native context occupancy are reported in ordinary reasoning text. Unknown context remains unknown; billed work is never treated as context occupancy.
* Inline PNG/JPEG/GIF/WebP images use actual native capability negotiation. Remote image URLs are not fetched. Verified workspace output links use existing `file:` URI formatting; the plugin adds no file server or WebUI module dependency.
* Hermes alone executes tools and handles approvals. The bridge must negotiate exact integer native-tool protocol v1 and acknowledge schemas. `session/new._meta` contains **only** `hermesToolSchemas`. Opaque call IDs/names/arguments are retained; malformed, undeclared, duplicate or ambiguous calls fail closed. Literal text examples never become actions. Direct ACP filesystem and permission requests are denied.
* One short-lived ACP/SDK bridge process per request. No persistent-session redesign. Cancellation retires only that turn's child. Streaming workers inherit ContextVars. A credential snapshot belongs to the constructed client, via the installed scope or existing `owner_secret_scope(home)` policy; no plugin-added ambient fallback.

## Requirements and supported launch declarations

Use a Hermes runtime with `ProviderProfile.create_client`, keyword `supports_streaming`, `supports_vision`, external-process provider metadata, secret scopes, `tui_gateway.launch_profile_policy.owner_secret_scope`, and the usual OpenAI/stdlib runtime dependencies. See [COMPATIBILITY.md](COMPATIBILITY.md) for what was actually tested.

The native bridge/CLI are external prerequisites, **not bundled or downloaded at import time**. Use the reviewed `weave-copilot` build with `--hermes-tools-only`. Reference build: weave-copilot commit `4cecc41f71a36ff124f32c720736fc80e6473b3e`, bridge SHA-256 `b3a2fa65f572846e3159bbc1d2abae4458c04b22eb157f4b2590a67d38c24ad4` (Linux executable; a receipt, not a forever-pin).

Default launch:

```text
weave-copilot --copilot-cli copilot --hydrafusion --hermes-tools-only
```

A package-local `bin/weave-copilot` / `bin/copilot` takes precedence over PATH. Supported profile/process environment overrides (read by the same core auth preflight and client):

```dotenv
HERMES_FUSION_BRIDGE=/absolute/path/weave-copilot
HERMES_FUSION_ARGS='--copilot-cli /absolute/path/copilot --hydrafusion --hermes-tools-only'
```

These are executable/argv settings, not enable flags. Use shell quoting **inside** the args value if an executable path contains spaces. The strict launch tail is validated; extra/native-executor flags and legacy ACP overrides are rejected. Set launch settings in the intended profile's environment so its normal host binding can provide them. No globally registered provider object is mutated.

The base URL is the inert marker **`fusion://copilot`**, never an HTTP destination. Do not configure `acp://...`: current core forcibly disables streaming for that scheme before consulting the declared streaming capability. The plugin-owned transport uses ACP internally, independently of this marker. This compatibility choice was verified against the actual core streaming gate; it is not a monkeypatch.

## Install into a NEW profile home

Run with the target Hermes runtime's Python. `HERMES_PYTHON` below means that executable, not a new virtualenv. `PACKAGE` is the extracted package directory. Choose an absolute, **nonexistent** home; its parent must exist. The helper atomically publishes a whole new home and refuses existing/default/active homes. It never writes secrets.

```sh
export PACKAGE=/absolute/path/copilot-fusion-provider
export HERMES_PYTHON=/absolute/path/hermes-runtime/bin/python
export NEW_HOME=/absolute/path/isolated-fusion-home
"$HERMES_PYTHON" "$PACKAGE/scripts/install.py" --home "$NEW_HOME"
```

To copy explicitly supplied executables into that new home's plugin, bind each to its independently verified checksum. The helper copies/hashes bytes before publishing, rejects mismatches, and never executes binaries during installation:

```sh
"$HERMES_PYTHON" "$PACKAGE/scripts/install.py" --home "$NEW_HOME" \
  --bridge /absolute/path/weave-copilot --bridge-sha256 EXACT_LOWERCASE_64_HEX \
  --cli /absolute/path/copilot --cli-sha256 EXACT_LOWERCASE_64_HEX
```

Configure **that home's** `COPILOT_GITHUB_TOKEN` using the host's supported secret setup or a private owner `.env`. Never copy another profile's credentials into the package. `GITHUB_TOKEN` is not required/forwarded. A missing owner token fails before launch. The default upstream credential sanitizer still runs; only this scoped Copilot credential is explicitly reintroduced. This does not claim that all unrelated LLM credentials are removed by upstream's sanitizer.

The generated config is:

```yaml
model:
  provider: copilot-fusion
  default: fusion-standard
  base_url: fusion://copilot
```

No existing runtime has been installed, restarted, or deployed by this package's build/tests.

## Ordinary install into an already prepared, explicitly selected test profile

The fresh-home helper intentionally refuses existing homes. An operator who already prepared an isolated profile may place the package directory under its existing supported discovery path:

```text
$HERMES_HOME/plugins/model-providers/copilot-fusion/
  __init__.py
  plugin.yaml
  fusion/
  LICENSE
  THIRD_PARTY.md
```

Stage beside the **nonexistent** final plugin directory and rename without replacement; preserve the profile's secrets/config. Parent/operator owns this step. Supply its binary launch metadata above, or checksum-verify and stage `bin/weave-copilot` and `bin/copilot` before publication. Select provider `copilot-fusion`, model `fusion-standard`, marker `fusion://copilot` using the normal configuration/picker. This is not permission to install into production.

## Executable tests and blackbox probes

The test runner accepts an optional unmodified source root when the runtime's editable source is not on its default import path. All temporary state is created inside this extracted package; no working profile is modified.

```sh
PYTHONDONTWRITEBYTECODE=1 "$HERMES_PYTHON" "$PACKAGE/scripts/test.py" \
  --core /absolute/path/unmodified/hermes-agent \
  --receipt "$PACKAGE/receipts/tests.json"
```

The test runner exits nonzero for failures **and empty suites**, and records executed testcase IDs and source/test hashes. `receipts/` includes actual local RED/GREEN development logs and final qualification. Port-regression fixtures are labeled separately from new-feature TDD slices. The copied local core has an unavailable PM venv stamp: only fixture subprocesses/launch tests replace that path-discovery lookup with the real executing venv. No such override exists in provider/installation/probe code.

For an installed selected home, use the normal Hermes command or the standalone no-tool-execution blackbox (set `PYTHONPATH` to that runtime's unmodified source only if required):

```sh
HERMES_HOME="$NEW_HOME" hermes chat --provider copilot-fusion --model fusion-standard -q 'Reply briefly.'
"$HERMES_PYTHON" "$PACKAGE/scripts/probe.py" --home "$NEW_HOME" catalog
"$HERMES_PYTHON" "$PACKAGE/scripts/probe.py" --home "$NEW_HOME" infer \
  --model fusion-high --prompt 'Describe the attached image.' --image /absolute/path/image.png --stream
```

`infer --tools-json /absolute/path/openai-tools.json` can inspect native intent responses, but the probe never executes tools. Real outer-Hermes dispatch, permissions, browser/mobile picker persistence and live SDK behavior are separate acceptance gates owned by the integration operator.

## Package and verify

```sh
"$HERMES_PYTHON" "$PACKAGE/scripts/build.py"
cd "$PACKAGE/dist"
sha256sum -c copilot-fusion-provider-0.1.0.tar.gz.sha256
```

The deterministic archive contains the actual current private transport/OpenAI shape library, source/tests/docs/receipts and an internal `SHA256SUMS`; `dist/manifest.json` binds each packaged input plus the archive hash. No credentials, bridge/CLI binaries, core runtime hooks or WebUI assets are bundled. Vendored MIT attribution is in [THIRD_PARTY.md](THIRD_PARTY.md).
