# Changelog

## 0.1.0 (2026-11-09)


### Features

* add k8s-crew v1, a read-only triage crew built on k8s-skills ([ace60d8](https://github.com/k8s-servant/k8s-crew/commit/ace60d86529e2d1c94efca6e08e57b05e746f81b))
* add triage recipe, investigator role, runners and k8s-crew skill ([5bcad12](https://github.com/k8s-servant/k8s-crew/commit/5bcad126c81ceb4baa821b981aae30a39bd9fea2))
* add view-only crew identity, preflight and agent install ([e7cc4c7](https://github.com/k8s-servant/k8s-crew/commit/e7cc4c79bdcc8d582b664c0f2e2883232f3d331c))
* hold crew sessions to the viewer kubeconfig with a kubectl guard ([5ce6938](https://github.com/k8s-servant/k8s-crew/commit/5ce69388a21de9eeeb7bc8bd1bfd7d2fbd1490f1))
* **score:** record a run's cost from the last result event only ([d05a6ac](https://github.com/k8s-servant/k8s-crew/commit/d05a6ac7551bd32e113c5bcb8c64ff021bfb717e))
* **tools:** check crew reports for the fixed shape ([8d3fb65](https://github.com/k8s-servant/k8s-crew/commit/8d3fb6511f96459efd55418c0b08357196a1df4d))
* **tools:** check run transcripts against the run-freely tier ([b4e5734](https://github.com/k8s-servant/k8s-crew/commit/b4e573405d0370ebc0c0650bf1e45b7c6bdf576a))
* **tools:** load k8s-skills command checker from a pinned release ([601330a](https://github.com/k8s-servant/k8s-crew/commit/601330a5097d541958efb56a4184b84c6db13bd5))


### Bug fixes

* accept plugin installs of the investigator in preflight ([70e5fd9](https://github.com/k8s-servant/k8s-crew/commit/70e5fd9d19022c4e21684c7c07a978b58916e1ea))
* correct Copilot permission advice for 1.0.107 ([58714ad](https://github.com/k8s-servant/k8s-crew/commit/58714ad885d78f207e7d8a69a0f6448403868801))
* **crewcheck:** require the evidence rules in the agent and SKILL.md ([e53bb44](https://github.com/k8s-servant/k8s-crew/commit/e53bb446d0e62c91b44a159248fa4131d9d0de71))
* emit skills as a list so Copilot loads the investigator ([21e85a4](https://github.com/k8s-servant/k8s-crew/commit/21e85a408323c9b65f5de6c3cfae76fdc56cfc98))
* find project-level investigator installs in preflight ([8a9e35c](https://github.com/k8s-servant/k8s-crew/commit/8a9e35cf0484f6de9259ad465ce78f5a8a86af6f))
* give herdr helpers the hard rules inline ([ebd6390](https://github.com/k8s-servant/k8s-crew/commit/ebd639039f8160cf4e25cf564fd1520e3d2f4e8d))
* **launcher:** refuse non-viewer kubeconfigs, shell arguments and filter auto-allow ([669c5ce](https://github.com/k8s-servant/k8s-crew/commit/669c5ceb76e57d18038733e366cea750b2c35352))
* make Copilot kubectl rules deny-only unless auto-allow is chosen ([a0f4747](https://github.com/k8s-servant/k8s-crew/commit/a0f47475b6d52e00dfda2f42f164e2017c8de94a))
* make the boss run preflight as one plain command ([f8a9f6a](https://github.com/k8s-servant/k8s-crew/commit/f8a9f6a86e55eec2c55a6807a4534fe3c89639d1))
* make the herdr helper prompt safe to send through the shell ([03f5b5d](https://github.com/k8s-servant/k8s-crew/commit/03f5b5dee2c875c1d3643af9615546a968c3f5c1))
* **report:** require a fenced fix block and a non-empty undo ([8b5ed0d](https://github.com/k8s-servant/k8s-crew/commit/8b5ed0d84800908d2ba70e90cc44740f65a8a777))
* **score:** fail the transcript on an unknown Copilot tool ([2201b99](https://github.com/k8s-servant/k8s-crew/commit/2201b9954981bf103df53e9a27097f5af3a9411d))
* **scripts:** make preflight and viewer-kubeconfig fail closed for the right reason ([c31d2bf](https://github.com/k8s-servant/k8s-crew/commit/c31d2bfc49b8225fa35a3d78408138c2b115d324))
* **skill:** crew fix marker, viewer-only rules and a herdr runner without shell tricks ([5960337](https://github.com/k8s-servant/k8s-crew/commit/5960337668960e6688f262c3ad5b14782b3233d0))
* **skill:** keep findings to shown evidence and fixes to the cause ([4841648](https://github.com/k8s-servant/k8s-crew/commit/4841648c4c2d9af8256f21adb96d344a0404ffe3))
* **skill:** root cause is the trigger; prefer command shapes the check reads ([80ba10d](https://github.com/k8s-servant/k8s-crew/commit/80ba10dc6ea0d4dc85962c36a01cb752307a82e3))
* tell agents to run one plain read-only command per call ([93c2d59](https://github.com/k8s-servant/k8s-crew/commit/93c2d59827d67bc48768b7347756f8604c07f58a))
* **tests:** keep scenario runs away from other clusters and local files ([82f9502](https://github.com/k8s-servant/k8s-crew/commit/82f9502f0d3f83df8ce9b1f9f4f4dd6abc6a4a78))
* **tools:** close transcript check escapes through wrappers and substitutions ([273c451](https://github.com/k8s-servant/k8s-crew/commit/273c451d5fc43199d95141e4e5352550d167b23f))
* **tools:** never trust a restored k8s-skills checkout's git config ([c84f09a](https://github.com/k8s-servant/k8s-crew/commit/c84f09a7a7a2e7336595b199233a89d7bfe0b91a))
* **tools:** require a clean pinned k8s-skills checkout ([8b77650](https://github.com/k8s-servant/k8s-crew/commit/8b77650e86d7b9a71d0c6298272f3e7e419b9511))
* **tools:** verify the pinned k8s-skills commit before loading it ([19fda80](https://github.com/k8s-servant/k8s-crew/commit/19fda80ab983d7c4193c006cb4f80d7f22c4ec1b))
* **transcript:** allow crew scripts and helper starts only in their documented forms ([2663cf7](https://github.com/k8s-servant/k8s-crew/commit/2663cf74f9e5bd4e304e9338273003dda1077eee))
* **transcript:** fail closed on jq string interpolation and unknown jq options ([16461e8](https://github.com/k8s-servant/k8s-crew/commit/16461e8d4370b5c96f19bec4498674ba55588fbf))
* **transcript:** fail every command whose program is not allow-listed ([63f2459](https://github.com/k8s-servant/k8s-crew/commit/63f245995654af165b66ac460841a94ccad1c835))
* **transcript:** pin crew scripts, settings and viewer to the run's own paths ([55d5882](https://github.com/k8s-servant/k8s-crew/commit/55d588225d825c4c76c75725ac9e574b0d440247))
* **transcript:** read quoted shell text as literal before the pinned check ([18629a1](https://github.com/k8s-servant/k8s-crew/commit/18629a1baac81d5dd848e61c6520fe0f31e80b88))
* **transcript:** refuse comments, line breaks in quotes and $[ in the tokenizer ([a330b83](https://github.com/k8s-servant/k8s-crew/commit/a330b839fd929ed5ceb7812f110724448e4eea7c))
* **transcript:** refuse jq builtins only where jq would call them ([c90f84c](https://github.com/k8s-servant/k8s-crew/commit/c90f84c545734f2f7b67631904aae85524b2d5ae))


### Documentation

* add k8s-crew v1 design and implementation plan ([7d9c3b9](https://github.com/k8s-servant/k8s-crew/commit/7d9c3b9f398fac256f5efeacb548ce39c205aab7))
* add safety, gotchas, herdr release check, README and plugin manifest ([e8644b3](https://github.com/k8s-servant/k8s-crew/commit/e8644b307ac6b213d121b2be99ebe4222b00dc55))
* fix small inaccuracies ([60f60bc](https://github.com/k8s-servant/k8s-crew/commit/60f60bca3d3d46012999c839a0676ab7e0b2d724))
* keep k8s-skills independent and drop the triage table task ([63375eb](https://github.com/k8s-servant/k8s-crew/commit/63375eb0fe38607dda650337dfe3ef9a9ac2650f))
* **skill:** tell agents the jq limits the check enforces ([a6f6dc0](https://github.com/k8s-servant/k8s-crew/commit/a6f6dc086ffd33cc531f15a8683f0363cc63c8de))
* start crew sessions with crew-start.sh and state the residual risk ([3982c1c](https://github.com/k8s-servant/k8s-crew/commit/3982c1c6da2f998d54328971d3d0cdf4f8280a87))
