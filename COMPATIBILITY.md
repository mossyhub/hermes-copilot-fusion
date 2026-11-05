# Compatibility and qualification

## Supported architecture

This is a provider-only package. Normal Hermes provider discovery loads `copilot-fusion`; its private client speaks to the reviewed SDK-backed bridge. No Hermes/WebUI source splice, global provider replacement, startup hook or custom frontend asset is required.

Required host surfaces include `ProviderProfile.create_client`, declared `supports_streaming`/vision support, external-process launch metadata, secret scopes, and `owner_secret_scope(home)`. Older cores without these interfaces are unsupported rather than silently patched. Copilot itself may be bundled or separately installed in different Hermes versions; this plugin preserves whichever sibling-provider baseline the selected home actually has.

The `fusion://copilot` base URL is an inert provider marker, not a network endpoint. It avoids the legacy host rule that disables streaming for all `acp://` markers while still using the supported custom-client interface.

## Clean upstream integration exercised

The integration operator used independent state/workspace and stock upstream images:

| Component | Qualification identity |
|---|---|
| WebUI | 0.52.642; `ghcr.io/nesquena/hermes-webui@sha256:ff98c05b6a6a369e2c1f502317db40084b88c1c3ad477a5a006294537d34547f` |
| Agent | `nousresearch/hermes-agent@sha256:a86ace4d4177485ce136c1160ad65a641211268e733e7ea6078fe6761bacb06e` |
| Bridge source | `4cecc41f71a36ff124f32c720736fc80e6473b3e` |
| Live bridge binary SHA-256 | `96a5875e50e6ec14ae8e3a5463b3fd41544b013d102eaf191a3ff0a6f09569e8` |
| CLI | Official v1.0.105; binary SHA-256 `3bd8bdc75670d7b4ec445725f6a5b9af66ee7ec49e6194646e4a40a0bc09091c` |

The live bridge matches its qualified build manifest and source commit. The b3a2 reference in README identifies a separate build, not the live binary above. Versions/hashes are qualification receipts, not permanent update pins. Bridge and CLI remain external prerequisites and are not bundled in the source archive.

Actual integration checks, not synthetic SDK answers, exercised:

- Standard/High/Max selection and inference through three stock picker rows, including native solver/judge reports; saved selection survived reload.
- Real outer-Hermes file and terminal actions and result follow-up; the stock rendered download link returned HTTP 200 and exact expected bytes.
- Browser-uploaded image containing randomly chosen visible text, correctly identified; native model/context information rendered in the stock Processed → Thinking section.
- Native progress visible before final completion; Stop, idle, successful recovery; direct API override and return to Fusion.
- Mobile 412px and desktop 1440px picker layouts, without custom Fusion assets.
- Manual Deny preserving a disposable fixture file and Allow once executing its removal with exit code 0; no approval-policy source modifications.
- Gateway-default inference; checksum-bound fresh-home installation followed by real inference.
- Cold recreation of the stock WebUI container, retained plugin discovery and actual terminal execution afterward. Relevant core/WebUI source hashes remained equal to the initial clean baseline; protected existing services were unchanged.

These checks qualified the initial package behavior. The independent package review then found wrong-session text/reasoning acceptance (L1) and duplicate JSON-member acceptance before intent validation (L2). The original failed review is preserved. Corrective regressions and post-correction integration are separately source/hash-bound by the operator's final qualification receipt; do not treat an older passing subset as qualification of later modified bytes.

## Executable package tests

`scripts/test.py` rejects both failed and empty suites and records executed test IDs plus source/test hashes. It covers discovery, real host streaming/auth-preflight decisions, process-pipe blackbox fixtures, schemas/intents, inline images, event ordering, cancellation, credential scope, installation and deterministic packaging.

The historical worker receipt contained 34 passing tests. Later corrections can add tests; the current `receipts/tests.json` and matching input hashes—not that historical count—are authoritative for the delivered archive.

Some locally copied Hermes source metadata points to a host-only PM environment path. Relevant fixture subprocesses substitute only `pm.environments.selected_venv` at that discovery boundary while using the real sanitizer. The provider, installer and live probe contain no PM override. This fixture accommodation does not establish that the copied local tree is a correctly installed standalone distribution; live integration used the actual clean candidate runtime.

Historical RED/GREEN logs under `receipts/` are development evidence, not current failures or a second full-suite inventory. `port-first.txt` is adoption regression qualification. `followup-green.txt` retains an intermediate failed fixture attempt; current JSON verdicts and matching final source hashes take precedence over a filename containing GREEN.

## Explicit limitations

- Fresh SDK session and text-transcript replay per inference; no native arbitrary-history import or persistent-session redesign.
- Live native progress, then validated final answer/tool-call chunks—not tokenwise final-answer streaming.
- No guaranteed token savings, cache parity, minimum number of model-selected tool actions or exact equivalence to a hypothetical Fusion HTTP API. The adapter adds no translator model; Fusion and ordinary Hermes auxiliary tasks may perform multiple inferences. Historical tool results are replay data, not a second executor.
- No custom Fusion/Effort widget, dedicated runtime row, per-phase context ring or `_fusionRuntime` persistence. Use the three model rows and Thinking text; ordinary usage must not be relabeled as phase occupancy.
- No promise of every future upstream update working immediately. Retain the last-known-good package and qualify SDK/CLI/core compatibility changes normally.
- Linux live qualification only. Other platforms, including Windows, remain unqualified. The atomic installer fails closed when its no-replace primitive is unavailable.
- Package behavior is lab-qualified, not production-migrated. Cold recreation does not qualify every future image or deployment environment.
