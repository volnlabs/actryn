# Independent cross-reference: revised architecture versus the product brief

Historical review of the preserved pre-remediation targets below. Its B1–B5 findings and replay clarification were subsequently addressed in the [remediation record](2026-10-13-review-remediation.md#brief-cross-reference-remediation). Original findings, line references and target hashes remain unchanged; the current normative contracts are linked from that record.

Date: 2026-10-13. Target: the revised architecture and its two normative contracts, after the previous remediation. **Verdict: keep the overall architecture; resolve five remaining contracts before freezing the V1 interfaces.** The design addresses the brief substantially, but the coverage table is not proof of implementation or completeness.

The mandatory custom Linux kernel component remains a fixed user requirement. The restrained fixture, fixed local skills and hosted-inference starting mode are defensible scope choices. They do not establish an existing-controller integration, a useful paid deployment or physical qualification.

## Review method and exact target

Three fresh reviewer agents separately examined product/reuse, kernel/control and server/platform behavior. None authored the patched documents. They inherited conversation context, so this is independent examination by separate agents, not a blind review or external certification. The original designer checked their counterexamples and synthesized this report. Agreement between agents is supporting review evidence, not a correctness proof.

Reviewed files:

- **A:** [system architecture](baseline/2026-10-13-brief-review-architecture.md), 468 lines.
- **K:** [kernel/controller contract](2026-10-13-brief-review-kernel-baseline.md), 94 lines.
- **P:** [platform/release contract](2026-10-13-brief-review-platform-baseline.md), 97 lines.
- [Current extraction/reuse decisions](../research/2026-10-13-source-review.md), [previous project inventory](2026-10-13-robot-project-audit.md), [platform inventory](2026-10-13-server-platform-audit.md) and [15-reference paper audit](2026-10-13-paper-audit.md).

SHA-256 of the normative review targets:

```text
A a4974b70998fb2dbb287d7ac6a0c8b098f75064b0be0464b7ebe7b07fcfcf5d1
K 9b994083a7edfafca4aea8eb3e9d08f0bd9e7876e545466450a260614df0a850
P ac0048d7934964b4ae4c6122db618573dcbf1328af6703dd3b2e51f0486e0e48
```

All 40 brief items and all 15 research references are cross-referenced below. The source inventories retain their original read-depth limits: selected source and documentation, not exhaustive project audits. This pass refreshed the MIT essay, RTC v2, LaST-R1 v3 and the pinned GPT-Policy license; it did not reread every paper or refresh every repository HEAD. No implementation, benchmark, model call or hardware experiment ran. Account quota telemetry was unavailable; the review used three bounded parallel lanes. The workspace root is not a usable Git repository.

## Remaining findings

P1 means close before implementing/freezing the affected production contract. P2 means a material specification or product-integration gap; it is not a demonstrated exploit. These findings describe missing rules and concrete possible implementations of them, not failures observed in running Voln software.

### B1

**P1 — Cancellation cannot identify a proposal whose operation ID has not returned.** Brief 12, 26, 27, 37. Evidence: A:252, 302–304, 373–375; K:68; P:20.

The initial proposal carries a stable request key. Query/cancel subsequently use the robot-issued operation ID. If the first proposal is delayed, an ordinary agent can decide to cancel before receiving that ID. Closing the broker context does not define a robot-side cancellation of the key. The delayed proposal can still arrive during valid grant/observation windows. If the response was lost, retrying `propose(key)` to discover its ID can itself perform first admission. Operator grant revocation is available but is a broader privileged action, not the promised operation-cancel API.

**Minimum correction:** allow authenticated query/cancel by `(attempt, stable request key)`. Serialize it with key allocation/admission. An allocated key uses existing operation cancellation; an unallocated key receives a durable terminal tombstone. Retain cancellation identity until the enclosing attempt/epoch cannot create work. Acknowledge request acceptance, effective key/operation closure and downstream reconciliation separately. Do not report effective cancellation before its required persistence/ordering conditions hold.

**Acceptance:** delay the first proposal, lose its response, race cancel with allocation, and crash after tombstone persistence but before its acknowledgment. After effective key cancellation, delayed/retried proposals with that key must never create an effect. Read-only lookup must never perform first admission.

### B2

**P1 — Natural completion has no defined operation-retirement transition.** Brief 12, 15, 21, 25–26, 32, 34, 39. Evidence: A:188, 298–306; K:52–72; P:91.

Cancel, revoke and fault recovery are specified. A “completed” parent is said to reject late samples, but the transition that makes it completed is absent. The proposed demo terminates one operation by cancellation and another by expiry. A skill reaching its target while a last nonzero sample remains applied must not release the group merely by returning success. Conversely, waiting for ordinary expiry would fault and require rearm after a successful task.

**Minimum correction:** a trusted skill's completion indication requests the existing close/quiesce path with a completion reason. Close its stream, discard unsent work, apply the selected partial-frame rule, reconcile the matching barrier, then release the group for another operation under a still-valid grant. Keep task-success evidence independent of reconciliation: target reached followed by a failed handoff is representable. Specify completion/cancel/expiry precedence; a late success cannot clear a fault.

**Acceptance:** perform two naturally completed index steps under one live grant without cancellation or rearm. Delay the first quiesce receipt and verify the next operation remains ineligible. Race completion with cancellation/expiry and deliver late samples and callbacks.

### B3

**P1 — Sandbox budgets do not bound trusted work performed on an attempt's behalf.** Brief 6, 9–10, 17, 24. Evidence: P:28–35, 43–44; A:220, 226.

Approved inference/tools run through a broker outside the agent cgroup. An agent can remain within its own limits while filling broker buffers, provider calls, response storage or shared inference work. Method/resource authorization and generic queue bounds do not define lifetime accounting after dequeue. Repeated cancellation must not return capacity while uncancellable downstream calls keep consuming it. Cgroup-only reports would also fail to explain that attempt's delegated consumption.

**Minimum correction:** reserve per-attempt and global capacity before broker dispatch. Bound outstanding work, request/response bytes, execution deadlines and applicable provider/inference budgets. Carry the attempt identity and reservation through execution and retained output. Attempt termination closes publication contexts and rejects new work; late results cannot publish robot proposals. Release capacity only when the actual work/buffers terminate, including outstanding work that the provider cannot cancel. Use ordinary counters and limits, not another scheduling platform.

**Acceptance:** flood an allowed method with delayed/oversized replies, cancel repeatedly and terminate the attempt while calls remain outstanding. Assert admitted bounds, correct late-result rejection, accounting settlement and continued service for another admitted attempt.

### B4

**P2 — Candidate preparation lacks aggregate reservations and promises too much isolation from active work.** Brief 10, 19, 24–25, 37. Evidence: P:14–16; A:154, 208, 298, 381.

Several prepared instances are permitted inside the same `voln-robotd` that owns active skill state. The specification does not assign finite prepared-instance/state capacity, preparation work budgets or release rules. Repeated valid preparation can exhaust the daemon, causing owner loss and faulting active A. “Failed preparation leaves A alone” is therefore stronger than the specified resource contract. Controller expiry handles daemon loss; it does not make A unaffected.

**Minimum correction:** reserve capacity before candidate construction, covering active, staged and retiring state at their simultaneous high-water mark. Bound preparation work outside the control worker. Publish by consuming an existing reservation with the generation check; define abandonment, failed activation, replacement and restart settlement. State that deterministic preparation rejection preserves A, whereas daemon failure follows the owner-loss response. No AxiomOS scheduler or allocator port is required.

**Acceptance:** exhaust staging capacity and inject allocation/preparation failures while A executes. Rejection preserves A's state and authority; capacity neither leaks nor overcommits. Separately kill the daemon and verify fault/expiry rather than claiming that A continued unaffected.

### B5

**P2 — The customer-controller comparison is unnecessarily tied to the fixture's new wire protocol.** Brief 4, 30, 38–40 and the stated reuse boundary. Evidence: A:159, 200, 314–317, 332, 413–421; K:32–44, 94.

The custom fixture is legitimate. The gap is requiring “v2 adaptation” of the existing-controller alternative before demonstrating that its native interface cannot satisfy the necessary semantics. The design has no conformance route inside its kernel-enforced profile for a native protocol that can establish the same required facts. This can turn an integration product into mandatory controller-firmware development, despite the public-API-before-extraction policy. A separately labelled userspace adapter does not answer the kernel-enforced integration question.

**Minimum correction:** separate endpoint semantic obligations from their fixture-wire realization. Keep v2 for the custom fixture. For each existing-controller candidate, map native identity, expiry, queues, cancellation, receipts and restart behavior to the required contract; compare a suitable kernel backend with firmware modification. Missing obligations still disqualify the endpoint. Do not assume OpenCR or another current candidate actually meets them, and do not weaken the first profile's claims merely to accept it.

**Acceptance:** produce one concrete native-controller conformance map and run the same stale-work/interruption/restart traces. Any unmapped obligation blocks qualification. Require evidence of a native semantic gap before accepting a firmware fork. This preserves mandatory kernel inclusion without promising universal controller support.

### Clarification before implementing replay

P:68 and A:350 allow partial replay, while skills have mutable state (P:16; A:300). Separate **event playback** from **execution replay**. A mid-skill interval can contain its visible inputs but lack earlier state altered by a clamp/intervention. Execution replay should require the activation boundary and complete input prefix, or a compatible replay-only checkpoint; otherwise label reconstructed state unknown and retain timeline inspection. The current design already permits partial intervals with unknowns and does not promise deterministic reproduction, so this is a narrower clarification, not a sixth P1 finding or a request for physical checkpoint restore.

## What should remain

- Keep `voln`, `voln-linux` and `voln-targets`. These separate userspace delivery, kernel compatibility and physical-profile qualification without creating a repository for every process. Keep independently promotable server and robot manifests.
- Keep one kernel authority/dispatch order, urgent closure outside the ordinary FIFO, and separate requested/locally-closed/reconciled/physically-observed facts. A custom component has a named job; no new OS, JIT or general kernel policy runtime is needed.
- Keep the partial-frame residual allowance explicit. Preserve original identity/deadline, controller absolute expiry, boot/session retirement, applied-output receipts and fresh state on activation.
- Keep the server-only product, prepare-before-execution attribution, constrained broker, truthful denial labels and cleanup/export acceptance story. B3 completes its resource boundary rather than replacing it.
- Keep observation acquisition provenance, geometry-specific skill checks, uncertain outcomes, durable parent intents, bounded asynchronous evidence and replay without live authority.
- Keep fixed skills and the restrained fixture as V1 scope. Action chunks, live robot code, powered holding, balance and humanoid locomotion need separate supported profiles; their absence is not by itself a violation of the brief.
- Keep the competent userspace baseline and second-installation requirement. Kernel inclusion is required; its incremental benefit and buyer demand remain empirical questions.

## All 40 problems cross-referenced

**C** = concrete design coverage, not tested correctness. **P** = remaining contract gap above. **D** = explicit and defensible V1 deferral. **G** = target choice, implementation, source clearance or measured acceptance still required. A row may have several statuses. No row is a physical PASS.

| # | Brief requirement | Status | Current design and remaining obligation |
|---|---|---|---|
| 1 | Named complete hardware | C/G | A §7, D0/D4: two candidates and full manifest fields; no selected complete qualified configuration yet. |
| 2 | Repeatable installation on Linux | C/G | A §9; native packages/offline bundle/containerd, optional Wendy comparison; second operator must install it. |
| 3 | Identity separate from motion | C/G | P §4; local enrollment, credential scopes, finite delegation, recovery; enrollment/expiry tests outstanding. |
| 4 | Narrow adapter, reuse drivers | P/G | A §7/§10 specifies route inventory and limitations; B5 supplies the missing native-semantic conformance route. |
| 5 | Physically consistent updates | C/G | A §9, P §5; inhibited complete tuple, recovery access, fresh epochs, preserved evidence; power-cut tests needed. |
| 6 | Untrusted generated code isolation | C/P/G | A §5, P §2 selects one OCI profile; B3 extends budgets to delegated work. |
| 7 | Denial versus observation | C/G | P coverage table; attributable broker denial differs from OS failure and unavailable coverage; attachment/loss tests needed. |
| 8 | Trusted attempt attribution | C/G | P launch ordering and A §5 bind identity before start; verify actual create/start and lifetime behavior. |
| 9 | Diagnose slow/failed attempts | C/P/G | A §5 and P server story cover pressure/process facts; B3 adds delegated consumption attribution. |
| 10 | Bound interference with control | P/G | B3/B4 complete admission accounting; dispatch/recorder bounds already specified; stress measurements still required. |
| 11 | Explicit inference location | C/G | A §3 hosted-first, alternatives deferred; exact provider/model remains unselected and unbenchmarked. |
| 12 | Typed tools and structured results | P | A §6/§9 selects describe/observe/propose/query/cancel and fixed skills; B1/B2 complete interruption and normal success. |
| 13 | Acquisition-time freshness | C/G | A §6 and K observations use retained IDs, oldest acquisition bound and inhibited revision change; clock/camera qualification pending. |
| 14 | Perception and action representation | C/G | A:266–270 defines support intervals, frames, masks and normalization; target-view/geometry tests pending. |
| 15 | Meaningful failure categories | C/P | A §8 separates factual and learned outcomes; B2 prevents conflating normal task completion with cancellation. |
| 16 | Local control independent of remote RTT | C/D/G | Local fixed skill/controller expiry; high-rate or stabilizing control is outside this fixture, not claimed solved. |
| 17 | Inference contention | D/P/G | OxyGen/GPU optimization appropriately deferred; B3 bounds hosted/shared outstanding work now. |
| 18 | Asynchronous action chunks | D/C | A:306 and K:70 reject chunks; future extension must preserve predicted/authorized/committed/applied distinctions. |
| 19 | Predictable runtime/lifecycle | C/P/G | Single trusted runtime and optional Copper comparison; B4 supplies preparation admission and cleanup. |
| 20 | Bounded communication semantics | C/P/G | Separate bulk/control, typed RPC, expiry/receipt and one started/one unsent sample; B3 covers broker in-flight work. |
| 21 | One effective owner | C/P/G | Kernel grant/group ordering and independent protection; B2 closes normal operation retirement before next use. |
| 22 | Physically suitable admitted behavior | C/G | Fixed typed ceilings plus skill geometry/preconditions; no collision/safety proof inherited from numeric admission. |
| 23 | No actuator gateway bypass | C/G | Kernel backend and complete route inventory; exact console/debug/bus/socket/controller closure remains D0 work. |
| 24 | Artifact, instance and grant separation | C/P | Separation selected; B4 restores resource charging before publication without porting AxiomOS execution machinery. |
| 25 | Controlled replacement | C/P/G | Expected generations, fresh state, handoff and preauthorized new grant; B4 bounds staging, B2 defines ordinary completion. |
| 26 | Queued/transmitted revoked work | C/P/G | K finish-one/barrier rules are concrete; B1 covers cancel before identity return, B2 covers successful retirement. |
| 27 | Retry, restart and restore | C/P/G | Durable key/ID/digest, retired epochs and unknown outcomes; B1 adds pre-allocation cancellation identity. |
| 28 | Bounded programmable guards | C/D | Fixed V1 predicates; arbitrary guards/JIT/program runtime explicitly deferred. |
| 29 | Agent loss without losing stabilization | C/D/G | Continuing bounded skill or independent zero/disable for no-balance fixture; active stabilization/holding explicitly excluded. |
| 30 | Whole-host progress loss | C/G | Controller expiry/disable chain selected, not physically verified; B5 avoids unnecessary firmware replacement for future fitting endpoints. |
| 31 | Human takeover | C/G | Same grant/handoff path; normal takeover differs from fault recovery; endpoint-specific residual/takeover measurement required. |
| 32 | Coherent attempt evidence | C/P/G | Source identity, clock/sequence, durability and event meanings specified; B2 adds an explicit completion path to record. |
| 33 | Offline replay | C/G | Capture eligibility and no-live-path profile; clarify initial state for execution replay as above. |
| 34 | Honest episode labels | C/P/G | Proposed/admitted/applied/intervened/unknown retained; B2 separates successful closure from cancel/fault labels. |
| 35 | Rare interleavings | C/P/G | K fault matrix and differential tests specified; add B1–B4 counterexamples, then actually execute them. |
| 36 | Physical qualification | C/G | D4 separates software/controller/electrical/physical evidence; exact configuration and thresholds remain unmeasured. |
| 37 | Usable CLI/SDK/recovery | C/P/G | A §9 and P operator stories; B1/B2/B4 needed for complete workflow, then second-operator demonstration. |
| 38 | Shippable dependency obligations | C/P/G | Pinned extraction and release-specific terms/owners; B5 enforces public-API-first reasoning for controller reuse. |
| 39 | Repeatable paid deployment | P/G | Buyer/mobile visual-alignment hypothesis and D5 metrics present; B2 fixes repeated success path; fixture alone validates no demand. |
| 40 | Measurable differentiation | C/G | A:447 requires same-controller competent baseline; B5 allows fair native integration comparison. No superiority established. |

## Every supplied project family: consequence for the revised design

This is a disposition cross-check, not a new whole-source audit. Detailed source depth, pins, project identity ambiguities and per-project adoption tests remain in the linked project/platform inventories. Naming a project here does not make it a dependency.

| Projects/facilities from the brief | Disposition and specific architectural consequence |
|---|---|
| AxiomOS; Shrike/RP2040; AxiomOS FPGA gate | Extract state-machine/validation/regression knowledge; re-establish Linux synchronization and qualified controller/electrical behavior. B4 must preserve admission reasoning; B5 separates fixture protocol from general endpoint obligations. |
| TurtleBot3/OpenCR | Provisional existing-robot/controller comparison, not confirmed equipment. D0 must inspect the actual native paths and recovery semantics; B5 prevents assuming firmware replacement before that inspection. |
| Wendy CLI, wendy-agent, WendyOS; Transitive; RAUC | Evaluate deployment integration against native packaging; retain a single activation/update owner. Existing-Linux trial stays possible; image OTA/fleet delivery is optional. |
| ros2_control; Copper CuBridge; Viam | Candidate established integration APIs. Own typed admission, cancellation/recovery meanings and final route closure; B5 is required before declaring controller reuse handled. |
| Docker; Podman; containerd; namespaces; seccomp; cgroups | Choose containerd and a closed tested profile, not three sandbox managers. Standard mechanisms remain dependencies; B3 accounts for service work outside the sandbox. |
| Firecracker; Wasm | Deferred execution classes with different threat/compatibility obligations; no implicit arbitrary-native-code equivalence. |
| ActPlane; BPF LSM; Actime | Optional denial integrations with explicit hook/path coverage. Actime does not become the launcher; telemetry or post-event action cannot be relabelled pre-effect denial. |
| AgentSight; Huatuo; libbpf/libbpf-rs | Compare selected capture/diagnostic facilities to ordinary counters and necessary probes. Preserve trusted attempt lineage, privileges, privacy and measured overhead. |
| PREEMPT_RT; timerlat | Target qualification inputs, not end-to-end deadlines. B3/B4 close resource admission before scheduling optimization. |
| llama.cpp; Qwen3-VL-2B-Instruct; SmolVLM2-500M-Video-Instruct; hosted Astra option | One hosted direction first; exact provider/model unresolved. Local candidates remain measured alternatives, not Pi performance promises. |
| RAI; DimOS; EMOS/EmbodiedAgents; OpenMind OM1 | Potential clients of the small Voln tool API, not default robot writers or runtime dependencies. Retain original inventory's exact project identities and version caveats. |
| Copper; dora; HORUS; EMOS/Sugarcoat | Native-loop baseline; Copper earns adoption through measured benefit. No nested schedulers, competing restart managers or automatic rearm. |
| Zenoh/Zenoh-Pico; iceoryx2; Agnocast; OpenCyphal/libcanard | Defer specialized transport until a measured or named hardware need; preserve authority, queue, memory-lifetime and expiry checks. |
| Spot leases/Keepalive; ROSClaw; OpenRAL; AEROS; APYROBO; Nav2 Collision Monitor | Serious semantic/comparison references or later named integrations. Native fallback, lease recovery and “stop” effects must match the profile; neither README governance nor collision filtering proves physical qualification. |
| agent-check-restore-safety | Durable identity/unknown-result lessons are retained; B1 extends them to cancelled requests before robot ID return. No exactly-once physical-effect claim. |
| upstream eBPF; bpftime; llvmbpf; Copilot/Ogma; ROSMonitoring | Ordinary fixed BPF facilities where needed; defer custom programmable guard/runtime/JIT work. Monitor specification and compilation do not replace enforcement placement. |
| moteus; Zephyr watchdogs; F Prime health monitoring | Endpoint-specific expiry/liveness references, not a universal independent protective mechanism. Actual firmware, clock and electrical failure response must be qualified. |
| Interlatent; HIL-SERL; LeRobot; Gymnasium | Learn intervention/stream/dataset/task API semantics; all motion/reset routes remain governed. B2 matters to terminated/cancelled/truncated labels; streaming remains deferred. |
| OpenTelemetry; MCAP; Rerun; Copper recording/replay | Reuse correlation, records and viewers. Voln retains origin/durability/completeness/authority semantics; clarify replay initial state. |
| RAI Bench; TDBench/VLMEvalKit; EmbodiedEvalKit | Offline task/model evaluation candidates; exact scene/model/scorer identity and uncertainty remain separate from actuator admission. |
| AxiomOS host tests; Loom; Miri; fuzzing; QEMU; Renode | Preserve/adapt deterministic regression cases and use each tool at its actual layer. Host/model/emulated success cannot qualify unmodeled devices or physical response. |

## All 15 research references cross-referenced

The prior [paper audit](2026-10-13-paper-audit.md) contains exact versions, primary links and adoption tests. Its depth remains eleven selected full-text reads, one essay, one project/specification review and two abstract-only references; no result reproduction. The following checks whether each lesson survived the patch.

| # | Reference | Consequence in current architecture / unresolved boundary |
|---|---|---|
| 1 | MIT robot-use agents | General agents use existing tools above local control. A §3/§6 preserves this; B5 prevents unnecessarily replacing native controller APIs. The essay's latency/reliability limitations do not establish remote stabilization. |
| 2 | GPT-Policy | A:266–268 and P:20 bind tools/context/outcomes and retain skill geometry checks. Interface reference only; B1/B2 complete tool lifecycle. Source redistribution/commercial permission remains unresolved at the inspected revision. |
| 3 | UnifoLM-WLA | A:270 binds units, masks, normalization, joint/quaternion conventions; no universal vector-to-motor API. Model adoption remains separate. |
| 4 | Egocentric vision locomotion | A:254/336 preserves local policy/protection distinction; active locomotion is deferred. A restrained wheel fixture inherits no quadruped result. |
| 5 | Embodied-R1.5 | A:268/346 scopes planning/correction and learned outcomes to an operation. Same-model correction is not independent physical confirmation; B2 supplies actual lifecycle completion. |
| 6 | LaST-R1 | Versioned model/compute/task evaluation and no unversioned live weight swaps are appropriate. Training deferred; the brief's simulation-only description must not be used for v3, which includes real-world arm experiments. |
| 7 | LessMimic | A:266 requires skill-specific geometry/contact observability. Humanoid/control adoption deferred; inspected source availability is still an unresolved release input. |
| 8 | Point4D | A:266 preserves measurement-support intervals, occlusion and model derivation. Tracking/reconstruction freshness is not fresh sensor evidence or a qualified servo estimator. |
| 9 | GTP-FA | A:346 retains probabilistic/multiple/unknown failure attribution separately from runtime facts; no automatic learned blame or success label. |
| 10 | OxyGen | Specialized shared-cache/GPU scheduling deferred until a compatible measured workload; A:445 separates emitted actions from fresh-feedback decisions. B3 bounds present-day delegated requests independently. |
| 11 | PACE | Operation-scoped progress may inform a future client; no unreviewed mechanism or performance adopted. Full text/code remain unresolved in the existing audit; do not count this as a completed paper review. |
| 12 | TDBench | A:445 requires target viewpoint/rotation/occlusion evaluation and correct scene-level units; benchmark consistency is not a control-safety score. |
| 13 | PaPE | Deferred model-internal positional encoding, not a patch to hosted inference or a runtime coordinate validator. |
| 14 | H-GenPO | Hierarchical skill learning deferred; learned option commitment cannot define grant lifetime. Full text/code remain unresolved in the existing audit. |
| 15 | RTC | A:306 explicitly rejects V1 chunks and names future commitment frontiers. This is a justified deferral for fixed skills, not implementation of the brief's asynchronous-policy scenario. Compatible flow/diffusion policy integration needs a later contract and qualification. |

Selected primary-source refresh supports those limits: the [MIT essay](https://web.mit.edu/phillipi/www/writing/robot-use-agents.html) discusses tool use and latency/reliability; [RTC v2](https://arxiv.org/html/2506.07339v2) conditions future chunks on an executing prefix; [LaST-R1 v3 §3.3](https://arxiv.org/html/2604.28192v3) reports real-world arm experiments. The [pinned GPT-Policy license](https://raw.githubusercontent.com/cheng-haha/GPT-Policy/2ca201638e1139fe35973c8a2d209a894b389db1/LICENSE) leaves redistribution/commercial permission unresolved. None establishes Voln hardware support or task performance.

## First-demo and release decision

The prescribed install → pair → observe → propose → admit → local execution → interrupt → reconcile → rearm → inspect sequence is mapped to CLI and contracts. Disconnect, stale reply, CPU/I/O pressure, host/controller restart, partial transmission and recorder overflow are named tests. They remain specified, not executed.

Add three cases to make the demonstration representative of repeated operation: **normal success followed by another operation** (B2), **cancellation before receiving an operation ID** (B1), and **trusted broker/preparation overload while work is active** (B3/B4). A fixture fault demonstration alone does not exercise the happy path or establish recurring buyer value.

Before interface freeze: close B1/B2 in the shared operation contract and SDK, B3/B4 with finite reservation/settlement rules, and B5 in the endpoint conformance comparison. Clarify replay eligibility without adding live checkpoints. These are bounded amendments; they do not require another framework, OS, scheduler or JIT.

Before any release claim: select the actual controller/host/kernel/model, demonstrate complete route closure, implement the protocol/backend, run the software/race/recovery fixtures, and retain physical measurements for the exact target. The custom kernel's incremental benefit must be measured against the same-controller userspace baseline. The selected buyer workflow and a second installation must establish product usefulness separately.

The normative design files were left unchanged in this review. This report records new findings; it does not silently mark the previous remediation ledger reopened, patched or validated.

Document checks passed: exactly 40 requirement rows, 15 research-reference rows and five numbered findings; all 15 local links across this report and the updated README resolve; fenced blocks balance. Hash checks confirmed all three normative review targets and both historical baseline snapshots are unchanged. These are document-integrity checks, not execution tests. Only this report and its README index entry were added by this review.
