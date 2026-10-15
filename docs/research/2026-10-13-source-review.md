# Source review and selective adoption decisions

Review date: 2026-10-13; adoption guidance updated after independent review. Companion to the [revised system architecture](../superpowers/specs/architecture.md). These are source/documentation findings and design decisions. The [original snapshot](../reviews/2026-10-13-source-review-baseline.md) preserves historical line references; [remediation](../reviews/2026-10-13-review-remediation.md) records the changes. No integration, target kernel test or physical qualification was performed.

## 1. Inspected evidence and boundaries

| Source | Inspected identity | Scope |
|---|---|---|
| Local AxiomOS | `9be704c8ef9078c84b98efc5482cfef0389f89f0`, `feat/v0.5-runtime` | Artifact/instance, admission, installation, actuation, Shrike link and selected firmware/tests |
| Local Linux | `a5ebb76233b79db01e82e061173cb73c6d2b5c6b`, `master`; Makefile identifies `7.3.0-rc6` | BPF privilege checks, serdev/TTY/UART integration and Rust serdev presence; **not** the selected production kernel |
| WendyOS upstream | `d057dfc31fd81b64486645ee6f301ede3349da4f` | Existing-Linux install docs, agent/deployment protocol, selected OCI/containerd code, LICENSE/NOTICE |
| Copper upstream | `b3c4c83d79d61d0357e50d431dd4c5c9ec4fece6` | Task/message/monitor APIs, features, bare-metal example, ROS bridge, license |
| systemd upstream | `d93cbbbe76d4db88eb1d3eb194e7832fbef44deb` for inspected exec XML | Sandbox caveats and required-feature checks; not a chosen target version |
| ros2_control | `40592d945b47d43517a01561ba0aa9c820f60daf` for selected manifest | Integration/API reference; not a reviewed endpoint implementation |

Local source status: AxiomOS had one worktree and only untracked `papers/`; Linux was clean. Local branch names and cached tracking state are not a fresh remote-head audit. No reference checkout was modified. AxiomOS had a `.codegraph` directory, but `codegraph explore` reported no usable index; targeted source inspection followed. Indexing was not attempted. Wendy/Copper selected source copies were read under `/tmp/volnlabs-source`; no additional projects needed cloning into `ref/`.

The surviving earlier proposal/context were consulted. Intentionally deleted two-Pi/first-sellable documents were not recreated. The current user explicitly requires a custom kernel component in V1; that decision governs the companion design.

## 2. AxiomOS: extract contracts and tests, adapt mechanisms

Paths in this table are relative to [the inspected checkout](../../ref/axiomos/).

| Unit | Evidence | What transfers / what changes |
|---|---|---|
| Immutable artifact and effect contract | `kernel/crates/kernel_bpf/src/verifier/managed.rs:15–37,88–120`; `kernel/src/bpf/preparation.rs:231–264` | Preserve separation of declared, signer and slot ceilings. Authentication/allocation occurs outside the publication lock. The managed bytecode verifier does not verify arbitrary Python or establish Linux BPF compatibility. |
| Fresh instances and custody | `kernel/src/bpf/managed.rs:65–108,147–175,210–261` | Code may be shared; mutable instance state is fresh. Preserve preparation/reclamation settlement. Rework allocator policy and host lifetime machinery. |
| Exclusive publication | `kernel/src/bpf/installation.rs:280–298,803–886` | Expected-generation checks and matching consumed receipt precede mutation; previous artifact differs from previous instance memory. Rebuild synchronization for the Linux driver. |
| Admission and timing | `kernel/crates/kernel_bpf/src/verifier/admission.rs:211–257`; `kernel/src/bpf/control.rs:13–55,148–193` | Preserve overflow and transaction reasoning, not hardcoded rate/resource units. Modeled cost is not WCET. Source sensor freshness is receipt-based and insufficient by itself for acquisition age. |
| Fixed actuation monitor | `kernel/crates/kernel_bpf/src/actuation/mod.rs:530–563,647–728,974–1027`; `kernel/src/actuation.rs:342–405` | Adapt envelope/slew, ownership, stop latch and epochs. Wheel channels, scaling and board mappings are endpoint-specific. |
| Shrike protocol and handoff | `kernel/crates/shrike_link/src/handoff.rs:24–48,450–525,574–596`; `tx.rs:62–68,105–106`; `installer.rs:159–220` | Strong extraction candidate: bounded framing, exact correlation, timeout/commit behavior and retry identity. Local UART acceptance is not peer acknowledgement. CRC is corruption detection, not authentication. |
| Bounded recorder | `kernel/crates/kernel_bpf/src/actuation/recorder.rs:50–57,99–160` | Retain explicit gaps and latest-stop evidence. This is in-memory diagnosis, not a crash-persistent journal or complete replay mechanism. |

The kernel wrapping assumes CPU0/single-online-CPU conditions and IRQ-masked locks (`installation.rs:20–22,64–74,184–215`; `actuation.rs:45–74`). Managed execution also uses raw map pointers and CPU-local context (`kernel/src/bpf/mod.rs:344–369,435–451`). These are not portable daemon or Linux-module synchronization guarantees.

For V1, adapt the semantic state machines into a portable Rust reducer and use shared production semantics with thin Rust kernel glue as the first candidate. Exact-target API/build/lifetime feasibility remains a gate; a documented C fallback may be selected for an actual support gap, without requiring two production implementations. This does **not** reproduce AxiomOS's in-kernel bounded-program execution. `no_std` is not Linux compatibility or a no-allocation guarantee. Shared code and matching codec vectors do not independently prove correctness or concurrency equivalence.

The brief-cross-reference patch also preserves resource admission as a userspace obligation: reserve candidate construction/state capacity before preparation, account active/staged/retiring objects together, and settle it on publication/failure/reclamation. This reuses the transaction reasoning without porting the AxiomOS allocator. Natural skill finish now shares close/quiesce with cancellation; trusted success, reconciliation and physical evidence remain distinct. Cancellation before an operation ID returns uses a durable request-key fence in the robot manager, not a second kernel persistence layer.

Independent review found a material extraction boundary: `shrike_link/src/handoff.rs:138–148` limits ID uniqueness to object lifetime and requires inhibited drain/quiet handling; `tx.rs:239–240` completes a started frame before the safe pair. Ordinary firmware motor setpoints do not carry the handoff session identity. The new [kernel/controller contract](../architecture/kernel-controller-contract.md) therefore selects an incompatible session-bound wire v2 with per-command absolute endpoint deadlines, explicit partial-frame residual effects and fresh reset identities. Existing code supplies regression material, not an implementation of these rules. Do not copy the old quiet interval as a Linux timing bound.

Wire v2 is the selected **custom-fixture realization**, not an automatic firmware requirement for every controller. D0 must first map an existing native API to the same typed command, exclusive route, identity/retirement, non-renewable expiry, queue, receipt and host-loss obligations. A conforming native protocol may use a separately qualified kernel backend; an unmapped obligation rejects the candidate. Firmware modification needs a demonstrated gap, and legacy fixture fallback remains forbidden. No native controller is declared conformant by this design patch.

Firmware evidence is similarly specific. `firmware/shrike/control/src/control.rs:565–634` queues a safe acknowledgement after sink application and post-apply clock/stop/watchdog checks. `fpga.rs:227–238` separately checks accepted-sequence status. The R0.4 board's `force_safe` ignores pin/PWM error results (`firmware/shrike/rp2040/src/main.rs:155–161`). Therefore a software safe request/receipt is not an independent physical measurement. The active plan retains `physical_acceptance: false` until its missing synchronized fault/phase evidence exists (`docs/plans/active/v0.5-bounded-runtime-evolution.md:1132–1138`).

Tests to preserve, located but **not run**:

- Effect identity/contract cases in `verifier/managed.rs`; reservation settlement/stale receipts in `verifier/admission.rs`.
- Fresh state, allocation failure and reclamation in `kernel/src/bpf/managed_tests.rs`.
- Stop/publication/cancel interleavings, stale A→B→A identities and rollback in `installation_interleavings.rs` and `installation_tests.rs`.
- Every-byte-offset cancellation, partial transmission and backpressure in `shrike_link/src/handoff.rs` and `tx.rs`.
- No motion before offer, expired command, sink failure and FPGA acknowledgement in `firmware/shrike/simulation/tests/paired_control.rs`.
- Recorder wrap, latest stop and malformed/exhaustion cases in `actuation/recorder.rs`.

Root Cargo metadata declares `MIT OR Apache-2.0 OR MPL-2.0`; root license files exist. Selected extracted crate manifests omit package-specific license metadata, so establish provenance/package declarations when extracting. Vendor Shrike firmware under `firmware/shrike/vendor/vicharak-shrike/763d0a7/` has separate GPL licensing. Do not inherit a single repository-wide license assumption into firmware bundles.

## 3. Linux: a concrete custom endpoint boundary

The custom component is required by the user. Source supports a narrow serdev-based module as an architectural candidate; an actual supported board/kernel build is still unselected.

| Question | Inspected local Linux evidence | Architectural consequence |
|---|---|---|
| Does asynchronous write mean delivered? | [serdev core](../../ref/linux/drivers/tty/serdev/core.c), lines 214–255 | `write_buf` can accept a short prefix into a driver buffer. Track bytes accepted and revalidate each transition. No remote-acceptance claim. |
| Does drain/flush prove cancellation? | `drivers/tty/serdev/core.c:354`; `drivers/tty/serdev/serdev-ttyport.c:87`; `drivers/tty/serial/serial_core.c:607,664` | Buffer drain/flush cannot undo transmitted bytes or controller work. Need endpoint receipts/expiry and residual-work bounds. |
| Can normal TTY access coexist? | [TTY registration](../../ref/linux/drivers/tty/tty_port.c), lines 196–215; serdev core supports one child | Successful serdev registration skips normal TTY cdev creation. Verify actual binding and absence of console/debug/alternate paths. Binding failure must never enable motion via a fallback TTY. |
| Does this cover USB serial? | `drivers/usb/serial/bus.c:53`; serdev enumeration in `drivers/tty/serdev/core.c` | No. The first profile needs a dedicated suitable UART. USB/other routes need distinct backend design and qualification. |
| What callback constraints matter? | [serdev header](../../ref/linux/include/linux/serdev.h), lines 23–32 | Receive may sleep; write-wakeup must not. Wakeup means readiness for more data, not frame drain or controller application. It schedules the owner lane; no blocking wait under authority locks. |
| Can a module call the APIs? | GPL exports in serdev core; [Kconfig](../../ref/linux/drivers/tty/serdev/Kconfig) | Use a GPL-compatible module with the actual `SERIAL_DEV_BUS`/TTY-port support. Do not assume every distro kernel has it. |
| Is kernel Rust unavailable? | [Rust serdev abstraction](../../ref/linux/rust/kernel/serdev.rs) | It exists in this tree. Prefer shared Rust where the selected production kernel passes the complete API/build/lifetime gate; retain a narrow C fallback for demonstrated support gaps. |

The remaining source-to-hardware gap includes serial driver's callback bounds, FIFO/DMA/queue capacities, Device Tree binding, bootloader/console behavior, wire timing, controller parsing/expiry and electrical response. A source-supported integration path is not a timing proof.

For server isolation, keep stock mechanisms. BPF program privileges depend on the actual program type: the inspected `kernel/bpf/syscall.c:2863–2910,2977–3008` checks BPF capability and additional networking/performance privileges as applicable. Do not advertise a universal `CAP_BPF`-only collector.

Required denial and diagnostics have separate lifetimes. Protected policy links must survive reader loss; trace ring-buffer failure is an evidence gap. [Kernel ring-buffer documentation](https://docs.kernel.org/bpf/ringbuf.html) describes reservation failures. `CO-RE` relocation is not universal hook availability, as the [libbpf overview](https://docs.kernel.org/bpf/libbpf/libbpf_overview.html) makes clear through its build/load/attach model.

Systemd restrictions require feature checks: network filtering may be unavailable on an unsupported kernel; network namespaces do not hide visible pathname UNIX sockets; `NoNewPrivileges` does not constrain an external service doing privileged work on behalf of an agent. The launcher must deny management sockets and descriptor escapes. Inspect the [pinned exec documentation](https://github.com/systemd/systemd/blob/d93cbbbe76d4db88eb1d3eb194e7832fbef44deb/man/systemd.exec.xml) and [resource-control documentation](https://github.com/systemd/systemd/blob/main/man/systemd.resource-control.xml) when implementing the selected profile. Configuration directives alone are not evidence they took effect.

## 4. Wendy: deployment mechanics, not inherited authority

**Decision: evaluate a narrow external integration first; adapt source only for a measured integration advantage.** Its [existing-Linux installation](https://docs.wendy.dev/latest/installation/linux/) means WendyOS reimaging is not inherently required.

Useful candidates are discovery, architecture-aware deployment, OCI artifact transfer and resource/output streaming. The [pinned container service schema](https://github.com/wendylabsinc/WendyOS/blob/d057dfc31fd81b64486645ee6f301ede3349da4f/Proto/wendy/agent/services/v1/wendy_agent_v1_container_service.proto) is a useful API reference. Do not expose its generic exec/start/admin surface to an experiment agent or create a second owner of robot activation.

The [base OCI specification](https://github.com/wendylabsinc/WendyOS/blob/d057dfc31fd81b64486645ee6f301ede3349da4f/go/internal/agent/oci/spec.go#L213) already contains namespaces, seccomp, no-new-privileges and a deny-all base device rule. It would be inaccurate to say Wendy supplies no sandbox. However, those mechanisms must be assessed with the entitlements actually applied.

At the inspected revision, a network entitlement without a mode chooses host networking. [Containerd integration](https://github.com/wendylabsinc/WendyOS/blob/d057dfc31fd81b64486645ee6f301ede3349da4f/go/internal/agent/containerd/client.go#L1530) explicitly warns about this behavior. The [entitlement implementation](https://github.com/wendylabsinc/WendyOS/blob/d057dfc31fd81b64486645ee6f301ede3349da4f/go/internal/agent/oci/entitlements.go) also supports privileged-equivalent build access and broad camera device access. These are useful development capabilities but unsuitable as our default experiment permissions.

Our integration would translate a closed Actryn manifest into reviewed deployment operations, require explicit isolated networking, restrict actual devices and privileges, and keep grant/activation decisions in Actryn's kernel contract. Keep OS flashing, cloud enrollment, unrestricted shell/admin/build access and direct actuator entitlements outside the agent's API.

Acceptance experiment: compare a reproducible native-package/containerd installation with the narrow Wendy backend on install time, artifact transfer/recovery, privilege inventory, footprint and upgrade behavior. Inject failed transfer/start and confirm that deployment never activates a grant. Accept only if it reduces maintained delivery work without broadening authority; otherwise retain the simple installer.

Wendy's [top-level license](https://github.com/wendylabsinc/WendyOS/blob/d057dfc31fd81b64486645ee6f301ede3349da4f/LICENSE) is Apache-2.0, but its [NOTICE](https://github.com/wendylabsinc/WendyOS/blob/d057dfc31fd81b64486645ee6f301ede3349da4f/NOTICE#L90) identifies statically linked LGPL libusb in CLI binaries and other third-party terms. Any redistributed selection needs its own source/binary inventory; this review did not complete that inventory.

## 5. Copper: local execution experiment behind our contract

**Decision: optional integration and benchmark candidate, not the authority core.** The inspected workspace is development code, not a selected supported release.

The [task API](https://github.com/copper-project/copper-rs/blob/b3c4c83d79d61d0357e50d431dd4c5c9ec4fece6/core/cu29_runtime/src/cutask.rs) offers explicit task lifecycle hooks; message and [monitor interfaces](https://github.com/copper-project/copper-rs/blob/b3c4c83d79d61d0357e50d431dd4c5c9ec4fece6/core/cu29_runtime/src/monitoring.rs) offer validity/error-handling context. These can organize trusted local sensing/control. They do not supply Actryn's endpoint grant or reconcile a controller queue on their own.

Keep motor sinks above the typed Actryn kernel interface. A Copper graph may produce a proposal or local-control target, but cannot hold a raw UART/device bypass. Changing the trusted graph is an inhibited trusted-stack update initially, not an unrestricted agent behavior swap. Avoid nesting Copper and another local task scheduler.

Footprint depends on graph/features. The [feature manifest](https://github.com/copper-project/copper-rs/blob/b3c4c83d79d61d0357e50d431dd4c5c9ec4fece6/core/cu29/Cargo.toml) and [minimal bare-metal example](https://github.com/copper-project/copper-rs/blob/b3c4c83d79d61d0357e50d431dd4c5c9ec4fece6/examples/cu_min_baremetal/src/main.rs) do not establish a no-heap runtime: the example installs an allocator and configures a 128 KiB heap. That value is an example choice, not a measured minimum. Its [ROS bridge](https://github.com/copper-project/copper-rs/blob/b3c4c83d79d61d0357e50d431dd4c5c9ec4fece6/components/bridges/cu_ros2_bridge/README.md) is transport integration, not a ros2_control authority adapter.

Acceptance experiment: identical observation→local policy→Actryn submission flow using a simple native loop and Copper, with the same kernel gate. Compare scheduling distribution, queue behavior, dropped/deadline-missed work, CPU/RAM, recording overhead and recovery complexity under pressure. Add Copper only when those results or materially reduced application code justify it. Recording integration does not make replay a physical experiment.

Top-level [Apache-2.0 license](https://github.com/copper-project/copper-rs/blob/b3c4c83d79d61d0357e50d431dd4c5c9ec4fece6/LICENSE) is recorded; optional dependency/SDK/codec terms remain feature-specific release work.

## 6. Remaining candidates: deliberate disposition

These entries are **design dispositions**, not claims of a complete source audit of every listed project. The user-supplied paper mechanisms and license observations are not silently promoted to newly verified facts.

| Candidate/function | Decision now | What would earn adoption |
|---|---|---|
| Linux/systemd/containerd; libbpf | Ordinary dependencies; own closed configuration, launch registry and probes | Exact target feature/denial/attribution tests; delegated-work and preparation reservations extend resource admission beyond cgroups |
| SQLite, MCAP, OpenTelemetry | Reuse storage/format/correlation mechanisms | Power-loss/overflow/compatibility tests; authoritative event semantics remain ours |
| Rerun | Read-only viewing integration | Faster actual diagnosis without a duplicate authoritative datastore |
| AgentSight, Huatuo | Evaluate narrow public capture/diagnostic APIs before source extraction | A specified failure becomes measurably easier to diagnose than with counters/tracing, without unnecessary privilege or another platform |
| Actime, ActPlane | Integration references | Exact covered hooks, privilege/failure behavior and useful reduction in our own integration code |
| ros2_control/vendor SDK | Named endpoint integration only; map native semantics before requiring firmware changes | Routes, typed commands, cancellation/normal completion, identity/expiry and controller queue/receipt conformance; ROS support alone is insufficient |
| RAI, DimOS, EMOS, OM1 | Client-side references; small Python client first | A required task/tool workflow that the small client cannot reasonably support |
| Transitive, Viam | Deployment/resource/teleoperation references | Specific customer integration advantage with compatible identity and authority semantics |
| dora, HORUS, Sugarcoat | Compare only if native loop/Copper leaves a demonstrated gap | Consequential lifecycle/timing benefit without duplicate ownership/scheduling |
| Zenoh, iceoryx2, Agnocast | Defer transport specialization | Measured bandwidth/copy/queue bottleneck and preserved lifetimes/permissions |
| OpenCyphal/libcanard | Defer to a named CAN target | Actual hardware/protocol need and new endpoint qualification |
| RAUC/WendyOS | Optional future image delivery | Customer requires image OTA; inhibited upgrade/reconciliation still ours |
| bpftime, llvmbpf, programmable guards | Defer beyond fixed V1 predicates | A defined program class, verified effect model and measured need; no new verifier/JIT by default |
| llama.cpp/local models | Later measured inference profile | Task success, memory, observation-age and latency gates on actual equipment |
| RTC/Interlatent, OxyGen | Later policy-streaming/scheduling experiment | Compatible policy or measured inference contention; no generic hosted-tool acceleration claim |
| LeRobot/HIL-SERL/Gymnasium | Dataset/task API references and optional exporters | Preserve proposed/admitted/executed/intervened/unknown distinctions |
| Other supplied papers | Per-reference interface/evaluation/research dispositions in the independent paper audit | A named implementation question, exact source depth and later validation gate; abstract-only entries remain limited |

ROSClaw currently documents permits/leases, restart generations and receipts; it is a serious comparison, not evidence that these concepts originate with VolnLabs. [Current repository](https://github.com/ros-claw/rosclaw). OpenRAL describes a userspace C++ validation boundary and deadman process; compare actual endpoint behavior before asserting an advantage. [Current repository](https://github.com/OpenRAL/openral). AEROS's current README distinguishes repository and integration-surface licensing; inspect the particular files before reuse. [Current licensing section](https://github.com/s20sc/aeros-core#license). These README statements are not independently reproduced qualification results.

## 7. Initial design review and historical verification record

Two independent bounded reviews identified and corrected: expiry bypassing explicit rearm in the state diagram; unspecified old operation-ID discrimination; optimistic classification of unfinished operations after a crash; missing lifetime rules for required enforcement links; conflation of sandbox egress with other-host controller access; and incomplete launcher caller authorization. The architecture was then revised to honor the user's required kernel component, including kernel ownership, exact transport boundary and a separate module release.

Source inspections and document checks are the evidence produced in this turn. Validation passed for all three authored Markdown files: 12 local links resolve, fenced blocks balance, and the confirmed kernel decision/recovery rules are present with no stale stock-Linux-first decision text or TODO/TBD placeholders. This is structural document checking plus source/design review, not runtime verification. Tests were located, not executed. No product scaffolding, dependency installation, kernel/module compilation, runtime integration, model request, device pairing, flashing or motion occurred. The workspace root is not a usable Git repository in this session, so these new design documents are saved but not committed. Account quota telemetry was unavailable; review work used at most three bounded parallel lanes.

The later [independent project audit](../reviews/2026-10-13-robot-project-audit.md), [paper audit](../reviews/2026-10-13-paper-audit.md) and [platform audit](../reviews/2026-10-13-server-platform-audit.md) extend this initially selective review. They are historical evidence inventories; the current normative choices are in the main architecture and its two contract companions. In particular, adoption uses standard facilities/public APIs before adapters/extraction; server reports distinguish observed OS failures from attributable denials; recorded-output replay requires a capture manifest; server/robot promotions are independent immutable tuples.

The subsequent [brief cross-reference](../reviews/2026-10-13-post-patch-brief-review.md) prompted five further contract corrections plus replay clarification: key-addressed cancellation, natural completion, lifetime accounting for broker work, preparation reservations and native-protocol equivalence. Execution replay requires activation and a complete input prefix; partial event playback retains unknown state. These are design amendments, not new upstream source inspections or executed adoption tests. The remediation record separates their checks from the historical validation above.

Outstanding risk: exact kernel/controller feasibility, boot-identity persistence, clock mapping, transport/PM/callback behavior and electrical response remain unbuilt/unmeasured. The requested design patch resolves mechanisms and rejects incompatible fallbacks; it does not qualify the inspected source or hardware. See the remediation record for current document checks rather than interpreting the historical three-file checks above as validation of this revision.

## Comparative review corrections

The subsequent comparison with the supplied `arch.md` checked the following claims against these pinned local sources. These are source/design findings, not executed target tests. Source locations do not qualify the proposed release kernel, firmware or electrical path.

| Compared assumption | Source evidence and selected consequence |
|---|---|
| `write_wakeup` proves one previous frame drained | [serdev operations](../../ref/linux/include/linux/serdev.h) describe readiness for more data. Preserve the one-started-frame rule and actual controller receipt; do not derive a wire-queue bound from wakeup. |
| Flushing a truncated Shrike frame is harmless COBS recovery | [Shrike codec](../../ref/axiomos/kernel/crates/shrike_link/src/lib.rs) explicitly uses counted SYNC/version/type/length/payload/CRC framing without COBS. Parser recovery and stop delivery require a designed protocol; preserve immutable partial-frame completion and original expiry in fixture v2. |
| Any descriptor close means owner-death revocation | [Linux file release](../../ref/linux/fs/file_table.c) follows reference lifetime. Preserve registered manager task ownership despite duplicate/passed references; the gateway receives no authority handles. |
| Existing `no_std` code is already allocation-free | [kernel_time](../../ref/axiomos/kernel/crates/kernel_time/src/lib.rs) allocates fixed-capacity storage at construction using `Box`/`Vec`. Inventory/adapt initialization, panic and overflow paths; preserve bounded no-allocation hot paths without claiming unchanged extraction. |
| The retained small FPGA gate contains the complete 50 ms watchdog | [Gate](../../ref/axiomos/firmware/shrike/fpga/shrike_safety_gate.sv) consumes `command_valid`; the [top-level implementation](../../ref/axiomos/firmware/shrike/fpga/forgefpga/ffpga/src/top.v) contains the counter and assumed clock. Rewriting the latter changes the protective implementation and requires renewed HDL, clock and electrical qualification. |
| V4L2 supplies a universally usable monotonic acquisition timestamp | [Official V4L2 buffer contract](https://docs.kernel.org/userspace-api/media/v4l/buffer.html) makes clock/source driver-dependent. Inspect flags and exact capture path; retain conservative acquisition bounds and reject unknown age. |
| A program-tag allowlist is equivalent to approved executable/configuration integrity | [BPF tag calculation](../../ref/linux/kernel/bpf/core.c) normalizes map references and hashes instructions, not map contents. Do not substitute this for complete program/configuration binding. V1 retains fixed predicates; any later programmable hook needs a separate trust contract. |

Adopt the comparison's simpler initial monorepo and separate network relay, while preserving independent artifact promotion, manager-verified identity, qualified controller semantics and standard-library/public-API-first reuse. Do not import its zero-external-code rule, unmeasured protection timing or a second-controller port as proof of repeatable installation.
