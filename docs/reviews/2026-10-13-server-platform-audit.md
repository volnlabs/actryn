# Independent server, platform and evidence audit

Historical review of the preserved pre-patch baseline. See the [remediation record](2026-10-13-review-remediation.md) for the current design changes and remaining validation gates.

Review date: 2026-10-13. This supplements the independent [architecture attack](2026-10-13-architecture-attack.md), [robot-project audit](2026-10-13-robot-project-audit.md) and [paper audit](2026-10-13-paper-audit.md). It reviews the proposed [architecture](baseline/2026-10-13-volnlabs-system-architecture.md); it does not implement its corrections.

The root designer performed this platform/source lane and synthesized the independent reviewers' results. This lane is therefore a fresh source audit, **not an independent second author reviewing their own design**. The separate attack, robot-project and paper lanes were delegated to reviewers who did not author the design.

Depth labels: **S** = selected implementation source inspected; **D** = primary documentation/model card inspected; **U** = identity or usable evidence unresolved. None means whole-repository security review, reproduced performance or a qualified deployment. Unpinned documentation describes the retrieved page on the review date; production revisions remain unselected. Rows group aliases only where stated.

## Findings that change the implementation plan

### S1 — High: select enforcement and denial evidence together

Architecture L167–174 and L208–216 correctly require installed coverage, but do not yet select enough of it to implement the server acceptance test. A successful policy compile, attached tracing program, killed process and pre-effect denial are different outcomes.

At inspected Actime revision `9c03598117af522c70e33695ca83dd4b38c12ff8`, `engine_supported_features` uses the conservative ActPlane 0.1.8 budget even when supplied a version string. Its enforcement preflight rejects rules needing unsupported file sinks/path matchers. ActPlane's broader engine capabilities cannot be assigned to this integration path. Its support matrix also distinguishes BPF-LSM blocking from tracepoint-triggered killing; argv-specific exec policies fall into the latter category. [Actime implementation](https://github.com/eunomia-bpf/actime/blob/9c03598117af522c70e33695ca83dd4b38c12ff8/crates/actime-core/src/enforceability.rs), [Actime policy documentation](https://github.com/eunomia-bpf/actime/blob/9c03598117af522c70e33695ca83dd4b38c12ff8/docs/policies.md), [ActPlane support matrix](https://github.com/eunomia-bpf/ActPlane/blob/404542899a2153af0952cbf0dc52aeab0b7c5034/docs/support-matrix.md).

**Correction:** start with a small executable coverage table: protected object/action, stock or custom enforcement point, install verification, process attribution, denial evidence source, unsupported routes, loss response. Choose concrete device-open, management-socket, network and syscall cases. Fail launch when a required denial cannot be installed. Do not describe an ordinary failed syscall as a policy-attributed denial without an attributable enforcement fact.

**Proof:** execute the known violation and an unrelated failure of the same syscall; disconnect the telemetry reader; fail enforcement installation; start descendants immediately. Check the claimed distinction in exported evidence. This is a software acceptance gate, not a reason to wait for robot hardware.

### S2 — High: specify the artifact execution path before designing a general behavior package

Architecture L224–229 names artifact/instance/proposal, but leaves the supported artifact's executable meaning unresolved. The practical first choice should be explicit: an untrusted agent image runs in a server sandbox and requests fixed, reviewed robot-local skills; only bounded targets cross to the robot. If generated robot-local code is required in V1, add a selected local launcher, sandbox, state owner and crash/replacement path now. Merely installing an immutable artifact does not select either model.

This agrees with architecture-attack finding 7. Keep a custom kernel component as required, but avoid accidentally inventing a robot plugin runtime while claiming to reuse the existing local controller. Model frameworks and Wasm do not resolve the choice by themselves.

**Proof:** trace one artifact digest through its real process, attempt identity, robot instance, grant and operation; replace/crash that process and demonstrate fresh state plus no inherited authority. A forged identity in a tool request must not change the launcher-assigned identity.

### S3 — Medium: provenance must state what is trusted and what is merely declared

Architecture L235 explicitly bounds a compromised server rather than trusting its model intent. Consequently, checking a recent observation ID cannot establish that a model proposal was derived from that observation. An agent can pair an old result with a newly available ID while its grant is still valid. This does not defeat the fixed local envelope; it defeats any stronger interpretation of “the model acted on this fresh image.”

**Correction:** have the trusted inference/tool bridge originate a request-context record binding request ID, attempt, observation IDs/digests, configuration and completion. Bind returned proposals to that context where the configured execution class permits it, and still recheck local state at admission/dispatch. Label agent-declared provenance separately. If the bridge shares the compromised server trust domain, this remains server-attested lineage, not robot-verifiable reasoning or proof of model attention. Do not add remote attestation unless the product actually requires that stronger claim.

**Proof:** replay an old response with a fresh observation ID, change calibration during inference and return a result after context closure. Test both normal trusted-bridge handling and deliberately untrusted metadata; report the different assurance levels. These tests establish association under an honest bridge; a compromised bridge can fabricate both records, so they cannot prove the model received or used the observations.

### S4 — Medium: enrollment and credential recovery need an actual protocol

Architecture L233–235 separates pairing/deployment/motion rights, but TLS plus finite delegation does not specify first enrollment, issuer trust or recovery after losing an administrator key. Installing a device-management tool is not permission to inherit its entire trust model.

**Correction:** choose one local enrollment flow with an operator-confirmed device fingerprint or equivalent physical/local bootstrap, explicit issuer and stored trust roots. Define scoped certificate renewal, local revocation, offline delegation expiry, lost-key recovery and decommissioning. Bind grants to the authenticated principal and current robot policy; reconnect or re-enroll must not rearm. Keep deployment credentials outside the motion administrator role.

**Proof:** wrong device during pairing; copied deployment credential attempting a grant; rotated/revoked identity offline; expired delegation on reconnect; replacement of trusted configuration while inhibited. These are design/negative-test requirements, not a claim that the current proposal leaks keys.

### S5 — Medium: evidence capture policy and replay eligibility must agree

Architecture L214 defaults to metadata, while L307–321 promises useful recorded-input/model-output replay. Those can coexist only if every attempt declares what was actually captured. A hash of a missing image cannot replay its content; an OTel trace cannot replace an omitted controller receipt. A viewer's available timeline is also not the authoritative retention record.

**Correction:** define an attempt capture manifest with required streams, source identities/clock domains, capture/retention policy, ranges and gaps, and an explicit replay eligibility result. Keep kernel-origin, controller-origin, manager-origin and agent-origin events distinguishable after export. Use read, queued-for-persistence and durable watermarks separately; architecture-attack finding 9 specifies the liveness failure case. Expensive image export and viewer work cannot share dispatch resources without measured bounds. Recorded-output playback differs from rerunning inference: complete capture neither guarantees reproducible model outputs nor authenticates records from a compromised server.

**Proof:** disable image capture, lose a model response, fill the recorder, stop its writer while the reader remains alive, crash before a durability checkpoint, and export a partially retained attempt. The UI must say what cannot be reconstructed and must never turn replay into a live proposal. [MCAP specification](https://mcap.dev/spec), [Rerun sinks](https://rerun.io/docs/concepts/logging-and-ingestion/sinks), [OTel trace API](https://opentelemetry.io/docs/specs/otel/trace/api/).

### S6 — Medium: adapting a project is not synonymous with copying its internals

The architecture's “extract useful probe patterns” direction is too broad as an adoption rule. AgentSight exposes a capture library; libbpf, MCAP and normal container runtimes already offer bounded APIs. Copying selected implementation files can increase our maintenance burden and lose upstream corrections. Conversely, Huatuo's full privileged deployment is much broader than a few per-attempt signals. [AgentSight README](https://github.com/eunomia-bpf/agentsight/blob/85bdb152653999bb5bf24a5b13c863bf8c949581/README.md), [Huatuo README](https://github.com/ccfos/huatuo/blob/fc7dac3247079707caaa33696462e3f287ac6cdd/README.md).

**Correction:** compare standard mechanism → supported narrow API → adapter → extracted source → maintained fork, in that order. Customize configuration, trust placement and our contracts before changing upstream code. Any source extraction must identify the exact unit, retained assumptions, changed semantics, tests, license provenance and patch owner. This honors the user's requirement to select and tailor every adopted component without making a fork a product requirement.

**Proof:** a dependency decision record must show the concrete user problem, rejected simpler option and maintenance/qualification cost. No full framework enters V1 merely because its README overlaps our vocabulary.

## Complete platform/reference disposition

Each named platform reference from the brief assigned to this lane is accounted for below. Hardware/robot frameworks are in the robot-project audit, and the 15 research references in the paper audit. This is a coverage ledger, not a dependency manifest.

| Reference | Depth and primary evidence | What earns a place / required adaptation |
|---|---|---|
| Linux kernel; BPF LSM | S+D: [pinned local source review](2026-10-13-source-review-baseline.md), [LSM docs](https://docs.kernel.org/bpf/prog_lsm.html) | Mandatory custom robot component; ordinary OS/BPF controls on server. Hook availability, privileges and final endpoint boundary remain target-specific. No general motor validator comes from an LSM hook. |
| Docker | D: [security](https://docs.docker.com/engine/security/) | Baseline comparator and developer packaging. Do not expose daemon socket, broad mounts or privileged mode to agent. Its isolation needs configured namespaces/caps/cgroups/filters. |
| Podman | D: [manual](https://docs.podman.io/en/latest/markdown/podman.1.html) | Alternative execution backend if it improves selected host operations. Rootless alone is not proof all needed limits/attribution are available. Avoid maintaining Docker, Podman and containerd launchers simultaneously. |
| containerd | D: [getting started](https://github.com/containerd/containerd/blob/main/docs/getting-started.md) | Initial existing runtime candidate. Voln must own attempt identity and prepare-before-start ordering; source-level lifecycle integration still required. No agent access to unrestricted daemon API. |
| Linux namespaces | D: [kernel namespace documentation index](https://docs.kernel.org/admin-guide/namespaces/index.html) | Standard isolation mechanism; select namespace set and host mounts in a concrete sandbox profile. Shared kernel remains trusted. |
| seccomp | D: [kernel filter documentation](https://kernel.org/doc/html/latest/userspace-api/seccomp_filter.html) | Reduce allowed syscall surface; combine with other access controls. Not a complete sandbox or typed pointer-content validator. Test target architecture/ABI and denial reporting. |
| cgroups / cgroup v2 | D: [kernel admin guide](https://docs.kernel.org/admin-guide/cgroup-v2.html) | Attempt resource accounting/limits, hierarchy/lifetime and pressure. Separate these from control-loop timing claims; deny untrusted migration and delegation escape. |
| Firecracker | D: [design](https://github.com/firecracker-microvm/firecracker/blob/main/docs/design.md) | Later stronger isolation profile if required; include jailer, image/kernel update and guest attribution costs. Host VM process identity is not guest per-agent identity. |
| Wasm | D through concrete runtime reference [Wasmtime security](https://docs.wasmtime.dev/security.html) | Different supported execution class with explicit host capabilities. Do not promise arbitrary Python/native compatibility or choose a new runtime just to gain a plugin label. |
| ActPlane | S+D: pinned support matrix/security model, revision `404542899a2153af0952cbf0dc52aeab0b7c5034` | Optional supported denial/policy engine; preserve monotonic policy constraints. Pre-effect block and post-event kill need different report semantics. See S1. |
| Actime | S+D: pinned enforceability implementation and policies, revision `9c03598117af522c70e33695ca83dd4b38c12ff8` | Optional orchestration around a selected execution environment; not its sandbox manager. Test its actual attachment/delta path, not the broader ActPlane language. |
| AgentSight | D: pinned README, revision `85bdb152653999bb5bf24a5b13c863bf8c949581` | Evaluate capture library and agent/system correlation against our minimum report. Native agent files, TLS tracing and kernel facts have different trust/privacy. No broad source extraction selected. |
| Huatuo | D: pinned README, revision `fc7dac3247079707caaa33696462e3f287ac6cdd` | Selected host diagnostics may earn integration; its quick start uses extensive host privilege and its BPF licensing differs from top-level licensing. Project overhead claims are not our measured overhead. |
| upstream eBPF; libbpf | D plus selected Linux source: [libbpf overview](https://docs.kernel.org/bpf/libbpf/libbpf_overview.html) | Use normal fixed probes/loading facilities. CO-RE is not hook-semantic compatibility or a reason to ship arbitrary uploaded probes. |
| libbpf-rs | D: [repository](https://github.com/libbpf/libbpf-rs) | Ordinary Rust integration candidate around libbpf. Pin toolchain/build artifacts and loader rights; do not write equivalent bindings without a gap. |
| PREEMPT_RT | D: [theory](https://docs.kernel.org/core-api/real-time/theory.html) | Target option only after workload/driver analysis. Kernel preemptibility does not bound every application, transport and actuator stage. |
| timerlat | D: [tracer](https://docs.kernel.org/trace/timerlat-tracer.html) | Measure host scheduling/interrupt latency with declared probe conditions; not end-to-end physical response or a proof of WCET. |
| llama.cpp | D: [multimodal docs](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md) | Local inference candidate with matching model/projector/input processing. Pin exact runtime/weights, then measure task quality, memory and observation age. |
| Qwen3-VL-2B-Instruct | D: [model card](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct) | Benchmark candidate. Model-card examples are not a tested Pi/laptop deployment; its version advice may be historical. No runtime/quantization compatibility inferred without a load test. |
| SmolVLM2-500M-Video-Instruct | D: [model card](https://huggingface.co/HuggingFaceTB/SmolVLM2-500M-Video-Instruct) | Smaller multimodal text-output candidate. Author-reported GPU memory is conditional, not full Pi RSS or deadline evidence. Test actual camera/task and preprocessing. |
| hosted Astra option | U: no unambiguous provider/model/version supplied | Keep hosted inference as a deployment class. Do not infer a model API, pricing, latency or capabilities from this name; exact identity needed before the live model experiment. |
| agent-check-restore-safety | D: [repository](https://github.com/eunomia-bpf/agent-check-restore-safety) | Reuse design lessons on external durable operation identity, restore-external history and frozen routes. Its prototype/VM/payment demonstrations do not prove physical exactly-once effects or production sandboxing. |
| bpftime | D: [runtime components](https://github.com/eunomia-bpf/bpftime#components) | Later userspace instrumentation/extension candidate. Injection, helpers, verifier and runtime ownership need their own threat model; not an independent kernel actuator boundary. |
| llvmbpf | D: [README](https://github.com/eunomia-bpf/llvmbpf) | Compiler/VM candidate only if a justified future extension requires it. Its documented scope excludes verifier, application loader and map/helper implementations. No V1 JIT dependency. |
| Copilot | D: [project](https://github.com/Copilot-Language/copilot) | Bounded monitor specification/code-generation reference. Generated monitor correctness still depends on input provenance and integration timing. |
| Ogma | D: [NASA repository](https://github.com/nasa/ogma) | Monitor integration/code-generation reference, including ROS/F Prime/cFS paths. Compare generated monitor against a fixed hand-written predicate before adopting toolchain. |
| ROSMonitoring | D: [repository](https://github.com/autonomy-and-verification-uol/ROSMonitoring) | Current docs include ROS1/ROS2 topic/service workflows. External oracle/monitor integration does not establish exhaustive route blocking or controller interruption. |
| OpenTelemetry | D: [trace API](https://opentelemetry.io/docs/specs/otel/trace/api/) | Standard correlation/export format. Trace context can be supplied by participants; preserve trusted source facts and sampling/loss labels separately. |
| MCAP | D: [specification](https://mcap.dev/spec) | Existing recording format, including schema/message metadata. Add our event meanings, completeness, persistence and recovery policy; format support alone supplies none of those guarantees. |
| Rerun | D: [sinks](https://rerun.io/docs/concepts/logging-and-ingestion/sinks), [memory limits](https://rerun.io/docs/howto/visualization/limit-ram) | Optional inspection frontend fed retained records. Viewer eviction/stream buffering must not define durable evidence or decide whether an episode is complete. |
| Loom | D: [repository](https://github.com/tokio-rs/loom) | Explore instrumented Rust-model concurrency within modeled bounds. Does not exercise Linux C driver IRQ/workqueue behavior. |
| Miri | D: [repository](https://github.com/rust-lang/miri) | Rust unsafe-code/undefined-behavior checking for supported execution. Not proof of all concurrency, driver correctness or hardware I/O. |
| fuzzing | D through [Rust fuzz book](https://rust-fuzz.github.io/book/introduction.html) | Target malformed schemas, wire parsers and reducer events; preserve regressions. Kernel fuzzing requires separate target facilities; randomized success is not exhaustive proof. |
| QEMU | D: [system emulation](https://www.qemu.org/docs/master/system/introduction.html) | Kernel/UAPI and fault-fixture experiments on modeled devices. Exact UART/controller/electrical equivalence is not implied. |
| Renode | D: [supported platforms](https://renode.readthedocs.io/en/latest/introduction/supported-boards.html) | Deterministic embedded/network fixtures if exact peripherals are modeled. Do not infer Raspberry Pi 5/OpenCR/Shrike physical timing from generic multi-node support. |
| AxiomOS, including FPGA gate and qualification artifacts | S: [extraction review](2026-10-13-source-review-baseline.md), [new source counterexamples](2026-10-13-architecture-attack.md) | Keep state-machine/test extraction, revise Linux synchronization, wire epochs and quiet/drain assumptions. FPGA source and software receipts remain separate from implemented electrical timing. |

The extra platform choices introduced by our architecture—systemd, SQLite, Protobuf/RPC/TLS, Python/Rust/C and package tooling—also need a release-specific dependency inventory. They are not hidden inside an “all projects reviewed” claim: selected systemd source was reviewed previously; SQLite/RPC/package implementations were not audited in this pass. Ordinary standard dependencies do not all require a source security audit to be selected, but none is yet a tested shipped tuple.

## Validation performed and remaining work

Read the current architecture and independent attack report, refreshed the primary sources above, and inspected the selected Actime/ActPlane implementation/docs plus local Shrike protocol source. No code was executed from fetched repositories. The review did not install products, run BPF policies, benchmark models, reproduce project results or exercise physical hardware. No whole-tree dependency/license/security review was performed.

Before production contract implementation, close S1–S5 alongside the attack report's wire/lifecycle findings. S6 governs each adoption decision. Server launch/report work can proceed independently under an explicit incomplete robot qualification status.
