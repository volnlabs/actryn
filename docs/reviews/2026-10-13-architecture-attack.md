# Independent architecture attack

Historical review of the preserved pre-patch baseline. See the [remediation record](2026-10-13-review-remediation.md) for the current design changes and remaining validation gates.

Date: 2026-10-13. Review of the complete [system architecture](baseline/2026-10-13-volnlabs-system-architecture.md) and [source review](2026-10-13-source-review-baseline.md). The reviewer did not author either design. The custom kernel component in V1 is a requirement; removing it is not the proposed correction.

This is a design review, not a reproduced vulnerability or qualification result. Architecture references below use its current line numbers. **Design blocker** means resolve before implementing the affected production contract, rather than forbidding a bounded feasibility experiment. **Qualification blocker** means measurements or target-specific evidence must precede that supported claim. A requirement already acknowledged as pending remains pending; its presence in a checklist is not a selected mechanism.

## Findings

### 1. High — reserved revoke capacity does not establish prompt invalidation

**Class:** missing design choice. **Architecture:** L194, L255–257, L345.

**Counterexample:** the single owner worker receives many submission/RX/completion events, then a revoke. Reserved capacity lets the revoke enter the queue, but a FIFO implementation can continue accepting authorized prefixes from older work before reaching it. Another implementation can return `locally-revoked` immediately from the syscall, while the worker still owns a live generation. Both fit “management syscalls submit bounded events” unless the linearization point and return semantics are specified. An expired receipt captured before its deadline but processed after it also needs a defined rule; callback capture time and transition time are different facts.

**Minimal correction:** define the event arbitration order, per-turn work bound, emergency invalidation mechanism, and separate accepted-request versus effective-revocation receipts. Choose whether urgent input invalidates eligibility before ordinary work or whether it enters a priority lane. Define timeout precedence over completion and recheck the absolute deadline at the actual transition. Do not claim a host scheduling deadline merely because the queue is bounded.

**Needed proof:** interleavings with full submission and RX queues, wakeup storms, simultaneous expiry/reply/revoke, and cancellation of a blocked write. Assert no experiment byte acceptance after the effective-revocation linearization point except the selected recovery allowance. Measure closure latency separately from downstream stop latency.

**Gate:** design blocker for driver/UAPI implementation; quantitative host and endpoint response limits are qualification blockers.

### 2. High — partial-frame recovery is still an unchosen protocol

**Class:** missing design choice plus empirical uncertainty. **Architecture:** L188–190, L259, L299, L394.

**Counterexample:** a nonzero motor frame has all bytes except its checksum accepted into the UART buffer. Revoke occurs. Completing the frame can cause a newly parsed old command; writing a stop frame directly can instead let its bytes complete or corrupt the old frame. Flushing cannot remove bytes already transmitted. “Finish, abort or resynchronize as permitted” leaves three materially different implementations open.

The existing extraction candidate selects one behavior: [Shrike `tx.rs`](../../ref/axiomos/kernel/crates/shrike_link/src/tx.rs):239–240 says a partial frame must finish before the safe pair. That is a residual effect to account for, not a property erased by adding the Linux gate.

**Minimal correction:** freeze one explicit protocol behavior for every byte offset. If old frames may finish, label their residual effect, bound it, and deny handoff completion until the downstream barrier covers it. If the controller rejects obsolete epochs, encode and check that identity in every effect-bearing frame. Keep protective traffic admissible during recovery without reopening task authority.

**Needed proof:** every-byte-offset cancellation with short/zero writes, stalled TX, CRC errors, concatenated stop traffic and delayed DMA/FIFO output; controller-parser differential tests; synchronized measurement of the worst retained effect on the selected fixture.

**Gate:** design blocker for backend/protocol implementation; buffer sizes, drain behavior and residual motion are qualification blockers.

### 3. High — nonrepeating host epochs do not establish controller freshness across reboot

**Class:** missing design choice supported by a concrete extraction mismatch. **Architecture:** L184, L237, L278–280, L299, L378. **Source review:** L31, L36, L65.

**Counterexample:** a module/daemon or controller restart resets the wire session counter, while an old response or motor frame remains in a hardware/software buffer. The new kernel runtime epoch is unique, but an old wire message need not carry it. Matching a newly reused session value or an ordinary valid motor sequence can accept stale work after a new session is established.

[Shrike `handoff.rs`](../../ref/axiomos/kernel/crates/shrike_link/src/handoff.rs):138–148 initializes local counters to zero and explicitly limits uniqueness to object lifetime. Its caller must inhibit peers, drain software/FIFOs/decoder and provide a 200 ms quiet interval. [Firmware `control.rs`](../../ref/axiomos/firmware/shrike/control/src/control.rs):435–482 binds offers/barriers to a session, while ordinary `MotorSetpoint` has sequence/left/right fields. The review does not establish that these source assumptions hold across the proposed Linux transport or any physical reboot.

**Minimal correction:** specify the wire-to-host identity mapping and wrap/exhaustion policy. Choose either a controller boot identity plus nonrepeating handshake identity carried by every command, or a proven inhibited drain/reset/quiet protocol that excludes all old messages before reuse. Define how the host discovers controller reboot before accepting a handoff receipt. A CRC is not endpoint authentication; a dedicated physical link can be the declared trust assumption without adding unnecessary crypto.

**Needed proof:** restart either peer independently and together, replay old offers/barriers/commands, retain buffered bytes through reset, and test identity wrap/exhaustion. Establish the quiet bound from actual queues/clocks rather than copying 200 ms.

**Gate:** design blocker for the V1 wire contract; reset/quiet/electrical behavior is a qualification blocker.

### 4. High — task death, endpoint teardown and power management need one concrete lifetime contract

**Class:** acknowledged but unresolved implementation feasibility. **Architecture:** L180, L184, L194, L247, L421.

**Counterexample:** the registered daemon thread exits while another thread or forked process retains its descriptor; alternatively the UART unbinds with an open authority FD and a scheduled write callback. A descriptor-close implementation revokes too late in the first case; a device-managed allocation freed during unbind can make the second case unsafe. Disabling system suspend also does not specify UART runtime power management. A sleeping transport can leave a started frame and pending timeout/revoke work in incompatible states.

**Minimal correction:** choose the owner identity as a defined process/thread-group lifetime, state the exec/fork/FD-transfer rules, and identify a supported kernel death-detection mechanism. Define a detached endpoint state whose storage survives outstanding FDs/work, the lock order and callback cancellation order, and runtime-PM ownership while output is eligible. PM/unbind error paths invalidate authority and never wait indefinitely for an unreachable controller. Ordinary module unload may be refused while references remain; forced unload is outside the supported profile.

**Needed proof:** fork/dup/pass/exec/thread exit, PID reuse, daemon stall, death during activation and partial write, device unbind/rebind with open FDs, runtime/system suspend and failed resume; selected-kernel lifetime/synchronization review with appropriate kernel race/memory tooling.

**Gate:** design blocker before driver implementation, as L421 itself requires. Timing and host-loss physical response remain qualification blockers.

### 5. High — surviving stabilization has no separate authority or fallback path yet

**Class:** missing design choice, conditional on the selected physical profile. **Architecture:** L178–184, L239, L257, L270, L303, L315.

**Counterexample:** a robot needs a continuing stabilizer to remain upright or hold a load. Daemon death, task expiry or recorder overflow revokes the runtime session's task authority and inhibits the group. If stabilization shares that handle, it stops too. If it bypasses the sole dispatcher, the claimed final ownership boundary fails. The statement that stabilization survives experiment expiry is a requirement, not a specified path.

**Minimal correction:** choose where trusted stabilization runs and how the fixed dispatcher distinguishes task targets, stabilization output and protection. Give its continuation/fallback budget and identify what survives task grant loss versus complete host loss. For a restrained wheel fixture that requires no active stabilization, say so and limit V1 to its qualified stop/disable behavior; do not infer support for an active hold or balance controller.

**Needed proof:** revoke only the task grant while stabilization is active; then kill the daemon, saturate evidence, stall the host and lose the controller link. Establish which component continues, which target it uses and the independent host-loss behavior.

**Gate:** design blocker for any stabilization-support contract. A simple wheel-fixture profile can resolve the choice by excluding active stabilization; physical fallback remains a qualification blocker.

### 6. High — continuous operations need identities below the immutable operation digest

**Class:** missing design choice; potentially contradictory if implemented with one digest rule. **Architecture:** L237, L255, L280–282, L338, L345.

**Counterexample:** one admitted operation streams sample 1 at a low velocity and sample 2 at a different velocity. If every proposal uses the operation ID with its current payload digest, “same ID/different digest is rejected” blocks valid streaming. If only the parent digest is checked, a duplicated sequence can carry changed sample values. After cancellation, a delayed sample may still carry a valid grant generation and observation even though its parent operation ended. The current identities do not select the sample rule.

**Minimal correction:** separate the immutable operation/skill digest from per-sample identity and digest. Define sample sequence acceptance, duplicate handling, supersession versus FIFO, maximum downstream horizon, and whether one operation or several may occupy a group. Cancellation closes that operation's child stream as an ordered transition, without requiring an unrelated grant to be revoked. Preserve the durable request-key binding across restart and return the original operation/unknown outcome on retry; never allocate a replacement automatically.

**Needed proof:** changed-payload duplicate, reordered/late samples, cancel versus queued samples, parent expiry, sample sequence wrap, and daemon restart between durable intent and submission. Confirm a held velocity cannot persist beyond the admitted horizon merely because samples stop arriving.

**Gate:** design blocker for SDK/RPC/UAPI and local streaming implementation; controller horizon timing is a qualification blocker.

### 7. High — the installed artifact has no selected execution and isolation path

**Class:** missing design choice affecting the complete demo. **Architecture:** L147–150, L198, L224–229, L278, L331–336, L359.

**Counterexample:** the operator installs artifact A, prepares robot instance I, issues I a grant, then starts server agent attempt J with that grant. It is unclear whether A is generated Python/native code executed locally, a fixed local skill configuration, or only the server agent image. There is no selected robot-side behavior launcher/sandbox, nor a specified mapping of J to I and its kernel session. Giving an installed generated process a sensor/control component's trusted role would silently enlarge the threat model.

**Minimal correction:** define one artifact manifest and execution location/trust class for V1. Name the process that owns mutable instance state, the local executor and isolation policy when code is untrusted, and the mapping among server attempt, robot instance, authenticated principal and kernel handle. If V1 executes only trusted local skills with untrusted bounded targets, state that product scope explicitly and show the full demo with that class.

**Needed proof:** install/prepare/activate a real supported artifact; crash and replace its executing process; verify fresh state, grant binding and absence of raw-device/management access. Include malicious identity fields and a compromised paired server acting within its delegated bound.

**Gate:** design blocker for the full software sequence and behavior packaging. No hardware is needed to select this mechanism.

### 8. Medium — observation validity needs ordered revision changes, not just record fields

**Class:** missing design choice. **Architecture:** L237, L243–247, L255, L400.

**Counterexample:** an admitted queued command depends on calibration revision C. Calibration changes to C+1 while a previously copied kernel context still records C. A bridge updating its userspace cache alone does not invalidate dispatch eligibility. A buffered sample mapped through an obsolete clock calibration can likewise pass a receipt-age check while its acquisition-age bound is invalid. Slew checks also need the actual applicable previous accepted output and elapsed interval, not simply the latest requested value.

**Minimal correction:** install the current observation/clock/calibration revisions in the authoritative lane and invalidate dependent queued work atomically with a revision change. Define bounded uncertainty arithmetic, future/inconsistent timestamp rejection, observation-ID retention/reuse rules, and whether numeric limits use last admitted, UART-accepted or controller-applied state. Require an inhibited recalibration procedure if the first profile cannot update safely while active.

**Needed proof:** calibration or clock-map change between admission and each accepted prefix, future timestamps, drift/uncertainty limits, observation overwrite, stale ID reuse, short writes and dropped samples during slew enforcement. Sensor provenance/calibration accuracy require independent physical checks.

**Gate:** design blocker for the observation and fixed-limit interfaces; calibration/clock error bounds are qualification blockers.

### 9. Medium — reader acknowledgement cannot be the recorder health policy

**Class:** missing design choice; the document correctly rejects a zero-loss guarantee. **Architecture:** L282, L307, L311, L315.

**Counterexample:** the event reader keeps acknowledging kernel batches while its SQLite/MCAP writer is blocked or storage is full. The kernel stream appears healthy even though no recent authoritative record is durable. A long admitted stream can continue producing samples after “close new admission” unless the continuation limit applies to already admitted work. Crash recovery correctly yields unknown outcomes, but it does not repair evidence coverage before that crash.

**Minimal correction:** distinguish read watermark, bounded persistence backlog and durable watermark in the trusted manager's health contract. Select the maximum backlog/age and what happens to already admitted streams at that threshold. Preserve bounded stop/fault information separately from normal sample traffic; report gaps after recovery even if the final gap record was lost. Keep these storage rules in userspace except the small health/eligibility gate; no filesystem I/O belongs in the driver.

**Needed proof:** reader alive/writer stalled, ENOSPC, corrupt/unavailable metadata store, MCAP rollover, exhausted reserved records, and power loss at each intent/dispatch/checkpoint boundary. Show the exported report cannot substitute manager events for lost kernel facts.

**Gate:** design blocker for evidence-health semantics; durability behavior on the target storage and physical fallback are qualification blockers.

### 10. Medium — a useful denied-operation report needs a selected denial source

**Class:** missing design choice for the independent server product. **Architecture:** L167–174, L208, L212, L216, L395.

**Counterexample:** a container receives `EACCES` on opening a device. A syscall-result probe attributes the failed call, but cannot necessarily distinguish the installed device policy from file permissions or a driver's error. Seccomp or another enforcement mechanism may deny without emitting the particular event the planned reporter consumes. The sandbox can be correctly restricted while “which operation our policy denied” remains unsupported.

**Minimal correction:** choose the initial denied-operation classes and an explicit reporting source for each. Separate observed failure, policy-attributed denial and unobserved coverage. Freeze the preparation/attribution-before-execution ordering for the selected containerd integration, including runtime-created helper processes; do not make unsupported causal claims from errno alone.

**Needed proof:** known device, network, syscall and management-socket violations in real attempts, probe loss/unavailability, and failures unrelated to policy. Verify attribution from the first instruction through descendants and cleanup.

**Gate:** design blocker for D2's report/acceptance contract. This work can proceed independently of the robot protocol and hardware.

### 11. Medium — UART and C are plausible candidates, but the alternatives table selects too much

**Class:** missing decision evidence, not an objection to C or the required kernel component. **Architecture:** L20, L24–30, L178, L188, L192, L286, L376, L393, L421.

**Counterexample:** the first interested team has a recoverable USB/CAN/vendor controller on an existing supported Linux host and no suitable dedicated UART. The present layout and starting stack already make a custom Shrike UART driver the center of the product. It can pass a fixture demo while requiring new controller hardware/firmware for that buyer. Conversely, preserving Rust protocol code might reduce divergence on a supported Rust-capable kernel, but the inspected development kernel does not prove that capability on the selected distribution.

**Minimal correction:** retain a mandatory custom kernel ownership/dispatch boundary, but evaluate at least two concrete first-target candidates before freezing the endpoint. Compare integration burden, recoverability, installed-Linux fit and the buyer's workflow. Also compare a smaller kernel gate with trusted userspace policy preparation and downstream controller expiry/recovery, versus the proposed fuller in-kernel lifecycle/parser. C can remain the default if the supported kernel/toolchain favors it; record that selection after a minimal build/API feasibility check. Do not import all bare-metal Rust machinery or create a universal backend abstraction.

**Needed proof:** exact-kernel module/API preflight, endpoint ownership inventory, supported wire semantics, and a target comparison with installation/maintenance costs. Golden vectors alone do not prove state-machine equivalence between C and Rust; include event/interleaving traces and independent expected outcomes.

**Gate:** design blocker before selecting the production endpoint/language support tuple. UART timing and buyer demand are empirical uncertainties; a fixture experiment may proceed under those labels.

### 12. Medium — three repositories need one reproducible promotion record, with an independent server exit

**Class:** missing release mechanism. **Architecture:** L36–46, L89, L106, L216, L362–366, L394–398.

**Counterexample:** userspace merges new wire vectors while the kernel repository tests an older artifact and the target package still pins older firmware. All repositories pass their local CI, but no one has tested the published tuple. A single product release train can also accidentally make a server security fix wait for unavailable physical robot qualification, despite the promised independent server product.

**Minimal correction:** one versioned promotion manifest names immutable component/vector digests and the conformance results for the exact tuple; consumers never test a moving sibling branch. Define separate server and robot promotion eligibility under the same CLI/schema compatibility policy. A server release can pass its profile without upgrading the robot tuple. Separate repositories are defensible; they are not evidence that integration is automatic.

**Needed proof:** reconstruct one release from the manifest without mutable source dependencies, reject a deliberately incompatible UAPI/wire tuple, upgrade/downgrade userspace while keeping the qualified robot tuple fixed, and ship the server profile with robot qualification unavailable.

**Gate:** design blocker for release/CI ownership before production distribution, not for isolated prototype code.

### 13. Medium — the fixture sequence is not yet a buyer demo for either product

**Class:** product-scope uncertainty and missing acceptance choice. **Architecture:** L9, L20, L216, L286, L393–406.

**Counterexample:** a hosted model proposes a wheel pulse, the UART fixture rejects a stale retry, and a timeline shows revoke/rearm. This demonstrates important mechanisms, but may not show the commercial robotics team's repeated task becoming easier. A server report showing CPU counters and one deliberate denial may similarly be indistinguishable from a prepared container/tracing tutorial. The current design does not name a task or failure whose explanation is the customer's reason to install.

**Minimal correction:** define two small user stories: one server-only attempt with a real diagnosis/cleanup question, and one repeated robot experiment with a useful local effect, interruption and recovery. For the robot, specify exactly what observation informs the proposal and what result can be judged independently. Keep the restrained fixture as an engineering gate, then identify the additional supported endpoint/workflow needed for the customer demo. Define the complete install-pair-observe-propose-admit-local-execute-interrupt-reconcile-rearm-inspect scenario, artifacts and expected outcomes rather than only listing commands.

**Needed proof:** an operator other than the author performs both stories on a second installation and can explain the failure/outcome from the exported evidence; measure installation, diagnosis and recovery effort. This does not by itself establish willingness to pay.

**Gate:** choose the demonstration/workflow acceptance contract before implementation scope freezes. Customer usefulness and willingness to pay remain empirical; they need not block bounded engineering experiments.

## Verdict and retained strengths

**Verdict: revise before implementing the production contract.** The direction is feasible enough to justify bounded endpoint/kernel experiments; the document does not yet justify freezing the UART wire protocol, UAPI and full behavior/evidence interfaces. Resolve findings 1–7 first, select the initial observation/evidence/server reporting rules in 8–10, and make the endpoint/release/demo decisions in 11–13 explicit. None requires abandoning the mandated kernel component.

The design already gets several important boundaries right: local authority with remote inference; an independently useful server product; no raw actuator path for generated agents; a competent userspace comparison; admission versus delivery versus physical evidence; fresh instance state; unknown unfinished operations after crash; no automatic rearm; exact supported kernel tuples; and no inference that simulation or a controller receipt proves physical safety. These strengths reduce the corrections needed, but do not substitute for the missing cross-boundary rules.

**Remote identity/attestation limit:** L180, L198 and L235 deliberately trust the manager's executable/principal registration and scope a compromised server to its delegated envelope. TLS peer authentication, artifact digests and kernel receipts therefore do not attest which remote model/code actually caused a proposal. That is an honest V1 boundary, not an architecture contradiction. Reports should label manager-registered provenance and authenticated peer identity distinctly from independently attested execution; no new remote-attestation subsystem is required for the stated threat model.

**Implementation alternative:** first keep fixed host ownership, typed limits, generation invalidation and the selected final byte-acceptance boundary in the kernel. Keep artifact execution policy, authentication, preparation, durable intent and evidence policy in userspace. Put host-loss expiry and any required stabilization in the independently progressing controller. Move additional protocol/lifecycle logic into the kernel only where it is required to validate the authoritative handoff facts. This preserves the custom-kernel product and shrinks the first trusted kernel implementation without pretending userspace receipts are controller facts.

## Review evidence and limits

- Read all 425 architecture lines and all 135 source-review lines. Spot-checked local Linux serdev API documentation and AxiomOS handoff/transmit/controller source for the identified contract mismatches.
- CodeGraph was attempted first for AxiomOS code; it reported no usable index despite the directory, so targeted source reads followed. No index was created. The workspace and Linux reference did not expose a usable root index for this review.
- No product or reference source was edited. No builds, tests, model requests, installations, flashing or hardware experiments were run. This report is the only owned artifact.
- The source review's historical verification record remains historical. This review establishes design counterexamples and required proofs; it does not establish an actual concurrency defect in code that has not been written.
- First-party account quota tools were unavailable; quota is unknown. No child agents were launched by this reviewer.

Not checked: target runtime, physical response, dependency/license inventory, live upstream heads or commercial demand.
Risk: implementing the open choices as incidental defaults can invalidate the authority and recovery contract even when the happy-path fixture works.
