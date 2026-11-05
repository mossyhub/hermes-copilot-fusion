# Third-party notices and adaptation boundaries

* `fusion/transport.py`: adapted from Nous Research Hermes Agent generic ACP client (MIT, copyright 2025 Nous Research), using the unmodified generic reference identified in PROVENANCE.json. The plugin-owned version has its own native session declaration seam, disables direct filesystem/permission execution, and preserves historical tool identities. It does not import, replace or patch a core ACP implementation.
* `fusion/openai_bridge.py`: current shared first-party Hermes OpenAI shape bridge, vendored from the actual source and hash-matched to the fresh candidate's library. MIT, copyright 2025 Nous Research. The builder includes these actual bytes rather than an older embedded copy.
* `fusion/client.py`: adapted from hermes-labs-plugins GitHub Copilot adapter, MIT, copyright 2026 Nous Research. Retains the tested native schemas/intents, inline images, scoped credential snapshots, ContextVars, progress and cancellation behavior. Adds strict-only construction and catalog negotiation; removes host-specific runtime UI observers. Adoption tests are derived from that reference's contract suites.

The 2025 MIT notice is reproduced in LICENSE. The 2026 source notice follows in full:

MIT License

Copyright (c) 2026 Nous Research

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

No weave-copilot, Copilot SDK or proprietary CLI executable is bundled. Their own distribution/license requirements remain the operator's responsibility.
