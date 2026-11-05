# Publication provenance

## Two distinct artifacts

The v0.1.0 release contains the independently qualified original `copilot-fusion-provider-0.1.0.tar.gz`, with SHA-256 `3c92926ab5174fb209bfbbff6f477753e37c7a2ad1b83ade7f102f941cd3f0c9`. Its unchanged `manifest.json` binds all 48 original source, documentation and development-receipt inputs. The archive has an internal `SHA256SUMS`; its adjacent `.sha256` file verifies the archive itself. No dependency binaries or credentials are bundled.

This Git repository copies those original inputs, retaining MIT license and private-library attribution. The only modified original file is `README.md`, with an added publication/install section. `.gitignore`, this guide and the GitHub Actions workflow are additional publication files. `__init__.py`, `plugin.yaml`, every `fusion/*.py`, `scripts/*.py` and `tests/*.py`, and all license files remain byte-for-byte identical to the qualified manifest. The original archive is not claimed to be a build of the publication README or CI files. A future local `scripts/build.py` invocation builds its current checkout, not the historical release archive.

## External dependencies

The required bridge source is [mossyhub/weave-copilot](https://github.com/mossyhub/weave-copilot), branch `feat/hermes-external-tools`, qualified commit `4cecc41f71a36ff124f32c720736fc80e6473b3e`. Keep that fork and branch active: its main branch does not contain the required native-tool bridge feature.

The [hermes-tools-v0.1.0 release](https://github.com/mossyhub/weave-copilot/releases/tag/hermes-tools-v0.1.0) publishes the independently qualified Linux x64 self-contained SDK host `weave-copilot`, SHA-256 `96a5875e50e6ec14ae8e3a5463b3fd41544b013d102eaf191a3ff0a6f09569e8`, and `SHA256SUMS`. The checksum was independently compared to the qualification build manifest before publication. This is the live-qualified build; the original archive README's `b3a2` hash refers to a separate earlier build.

Install Copilot CLI only from [GitHub's official installation instructions](https://github.com/github/copilot-cli#installation) or [official release assets/checksums](https://github.com/github/copilot-cli/releases). It is not redistributed here. Qualification used official v1.0.105, executable SHA-256 `3bd8bdc75670d7b4ec445725f6a5b9af66ee7ec49e6194646e4a40a0bc09091c`. These dependency identities are receipts, not promises that dependencies must remain permanently frozen. Qualify changes and retain a last-known-good compatible set.

## Verification boundaries

The supplied development receipts are historical, sanitized fixture/build evidence, not private live logs. `COMPATIBILITY.md` describes the separately exercised clean stock WebUI integration and its limits. Publication checks rerun all 44 package contracts against the actual stock Agent image using its declared `HERMES_PYTHON`, without paid inference, replacement core stubs or production changes. Hosted CI likewise uses `nousresearch/hermes-agent:latest` and saves the inspected image identity and test receipt. A green contract run does not mean a new live SDK/browser qualification occurred on that CI runner.

The provider starts fresh SDK sessions with textual history replay per inference. Native progress is live, but final answers are not token streamed. No custom rich Fusion UI, persistent SDK sessions, API-equivalent token savings or universal future-version compatibility is claimed. Provider installation does not install its external bridge or CLI, authenticate the owner, or deploy a production service.
