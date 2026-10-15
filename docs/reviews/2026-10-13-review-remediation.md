# Architecture review remediation

Date: 2026-10-13. User request: patch the independent architecture review findings. **The design documents are revised; no product implementation or physical qualification is claimed.**

Current normative documents:

- [System architecture and project distribution](../superpowers/specs/2026-10-13-volnlabs-system-architecture.md): scope, ownership, repositories, CLI, integration and delivery gates.
- [Kernel/controller contract](../architecture/kernel-controller-contract.md): closure ordering, new wire protocol, operation/sample rules, lifetime and recovery.
- [Platform/release contract](../architecture/platform-release-contract.md): executable artifact, launch, evidence, enrollment and promotion.
- [Source/adoption review](../research/2026-10-13-source-review.md): inspected source facts with revised reuse guidance.

Both review rounds remain historical. The first review's five reports link to preserved [architecture](baseline/2026-10-13-volnlabs-system-architecture.md) and [source-review](2026-10-13-source-review-baseline.md) snapshots. The [brief cross-reference](2026-10-13-post-patch-brief-review.md) links to its own preserved [architecture](baseline/2026-10-13-brief-review-architecture.md), [kernel](2026-10-13-brief-review-kernel-baseline.md) and [platform](2026-10-13-brief-review-platform-baseline.md) targets. Original bytes/hashes and line numbers remain available; findings were not silently rewritten out of history.

## Selected corrections

V1 runs an untrusted server OCI image that invokes release-built native skills in `voln-robotd`. A robot artifact configures those skills and cannot upload code. Launcher-owned prepared attempt identity exists before the operator binds a local instance/grant. The backend has a fixed wheel-duty command class on a restrained fixture, without balance or powered-holding claims.

One kernel mutex orders dispatch and effective closure. Closure bypasses the ordinary submission FIFO; competing requests cannot weaken fault/revoke scope. Recovery finishes only the already-started immutable frame under its original deadline, then quiesces. This explicitly permits a bounded residual old effect; it never means zero physical motion after local closure.

The new fixture wire v2 is incompatible with existing Shrike motor frames. Effect-bearing messages carry session identity. Durable controller boot/per-boot session counters prevent epoch reuse; absolute controller deadlines never restart on delayed arrival. `SAMPLE_APPLIED` supplies actual controller-applied values/time and a known disabled-zero baseline. It remains distinct from independent physical evidence.

V1 has one started frame and one replaceable unsent sample; the next sample waits for a controller receipt. Arbitrary trajectories/chunks are rejected. Later policy streaming needs a separately qualified time/commitment contract. Normal operation cancellation retains an otherwise valid grant; expiry/owner loss/reset latch the endpoint and require recovery plus rearm. Neither retry nor rearm revives an old operation.

The earlier patch retained three repositories; the comparative remediation below supersedes that organization with one initial monorepo and independent immutable server/robot/target artifact promotion. Public upstream APIs precede extraction unless a concrete semantic gap warrants maintained code. No whole framework or training stack is imported by association.

## Finding-by-finding disposition

**Specified** means a concrete design rule exists, not implementation validation. **Scoped** excludes a capability from V1. **Gate retained** means missing source access, target feasibility, measurement, license clearance or buyer evidence cannot be supplied by a documentation patch.

A = [architecture attack](2026-10-13-architecture-attack.md), R = [robot-project audit](2026-10-13-robot-project-audit.md), P = [paper audit](2026-10-13-paper-audit.md), S = [platform audit](2026-10-13-server-platform-audit.md). Main section numbers refer to the revised architecture.

| Finding | Patch / authoritative location | Disposition and remaining proof |
|---|---|---|
| A1 — revoke ordering | Kernel serialization; main §§4/6 | Specified direct locked closure, monotonic pending slots, timeout precedence and bounded turns. Kernel interleaving/latency tests remain. |
| A2 — partial frame | Kernel partial-frame rule; main §§4/6 | Specified one immutable started-frame completion then quiesce; failure faults. Every-offset TX/parser and residual-motion tests remain. |
| A3 — reboot freshness | Kernel wire protocol; main §§4/7 | Specified incompatible v2, boot/session epoch and absolute deadlines. Firmware persistence/clock/reset tests remain. |
| A4 — owner/PM/teardown | Kernel lifetime; main §4 | Specified leader checks, exec denial, references/detached FDs and callback/PM order. Exact kernel exports, synchronization and build/race tests remain feasibility gates. |
| A5 — stabilization | Main §§1/3/7; kernel scope | Scoped restrained wheels; no balance/holding. Independent expiry/disable required; electrical response remains unqualified. |
| A6 — sample identity | Kernel operations; main §6 | Specified request-key allocation, immutable parent, sample digests/retirement/cancel/horizons. Scoped no arbitrary chunks. Crash/reorder/duplicate tests remain. |
| A7 — executable artifact | Main §§1/3/6/9; platform §1 | Specified server OCI plus fixed skill configuration, prepared identity before grants and fresh robotd state. Launch/replacement tests remain. |
| A8 — observation/slew | Main §6; kernel observations/receipts | Specified inhibited revisions, acquisition uncertainty, applied-output baseline and controller slew enforcement. Clock/calibration/ACK tests remain. |
| A9 — recorder health | Main §8; platform §3 | Specified read/queued/durable frontiers and finite pending age/bytes; health failure revokes existing streams. Crash/storage/writer-stall tests remain. |
| A10 — denial origin | Main §5; platform §2 | Specified broker-attributed denial versus failed OS access, plus prepare-before-start. Early-descendant/negative/install-failure tests remain. |
| A11 — endpoint/kernel placement | Main §§4/7 | Narrow gate selected; two concrete endpoint candidates compared qualitatively. Production endpoint and C/Rust target build selection remain explicit D0 gates. |
| A12 — release tuple | Main §§2/9; platform §5 | Specified immutable manifests and independent server/robot promotion. Reconstruction/mismatch/upgrade tests remain. |
| A13 — useful demos | Main §11; platform §5 | Specified diagnosis and restrained encoder-step stories; mobile alignment buyer hypothesis. Customer task thresholds, second installation and demand remain gates. |
| R1 — endpoint readiness | Main §7; kernel scope/wire | Full protective chain required; FPGA source alone insufficient. Hardware and physical timing remain gates. |
| R2 — recovery effects | Main §§6/7; kernel transitions | Specified normal cancel versus fault/rearm; home/open-gripper/hold/brake/disable are distinct authorized effects. Physical tests remain. |
| R3 — raw writers | Main §§3/7; target route manifest | Specified final route ownership and replacement of framework writers; no inherited UART claim for vendor/ROS routes. Actual route closure remains target-specific. |
| R4 — whole-host loss | Main §§1/3/7; kernel scope/PM | Independent endpoint expiry required; same-host watchdog supplies no whole-host guarantee. Electrical/controller/power tests remain. |
| R5 — duplicate lifecycle | Main §§3/10 | Specified launcher/skill/kernel/controller/operator ownership; self-healing cannot arm. Optional integration conformance remains. |
| R6 — version drift | Main §§9/10; promotion manifest | Exact binary/API tuple required for selected integrations. Current source audits do not select supported releases. |
| R7 — competitor overlap | Main §§10/11 | Governed userspace baseline retained on same controller; no novelty claim from leases or kernel presence. Comparative results not run. |
| R8 — benchmark evidence | Main §§8/11 | Model/data/prompt/judge pinned separately from actuator qualification. No benchmark or inherited safety claim. |
| P1 — motion suitability | Main §6 skill preconditions | Admit means fixed predicates; skill geometry/contact/support preconditions required. Fixture excludes general collision/arm safety. |
| P2 — chunk commitment | Main §6; kernel samples | Scoped no V1 chunks; mailbox/started/applied frontiers fixed. Future chunks require local time alignment, accepted-history conditioning and elapsed-sample rejection. |
| P3 — learned state | Main §§1/6; platform context | Attempt/model/context/demo/request/operation/subtask lineage and fresh-state reset specified. No unversioned live weight changes or remote-attestation claim. |
| P4 — measurement support | Main §6 perception | Support interval, visibility, derivation/frame/scale/uncertainty required; inference time cannot refresh occlusion. Calibration tests remain. |
| P5 — failure attribution | Main §8 outcomes | Learned distribution/version/unknown/multiple causes separate from facts; retain interventions/clamps/gaps. Attribution quality unestablished. |
| P6 — metrics | Main §11 evaluation | Scene/episode/reset/intervention units, budgets and shifts specified; generated/feedback/dispatch/physical rates separated. Measurements not run. |
| P7 — source depth | Main §10; historical inventories | Per-reference depth retained. PACE/H-GenPO full texts and some deployment code/terms remain unavailable; no adoption depends on them. |
| S1 — enforcement evidence | Main §5; platform coverage | Initial labels/fail-launch rules specified; Actime/ActPlane optional coverage separately qualified. No runtime denial test claimed. |
| S2 — execution class | Main §§1/6/9; platform §1 | Fixed local skills; ordinary agent cannot prepare/activate/issue grants. No generated robot code in V1. |
| S3 — provenance | Main §6; platform context | Request/observation/response/key binding with explicit server-attested trust and local rechecks. Compromised-server truth/model attention unproven. |
| S4 — enrollment | Main §§6/9; platform §4 | Local CSR/fingerprint/issuer, scopes, finite sessions and revocation/rotation/lost-key/decommission rules specified. Crypto/clock/recovery tests remain. |
| S5 — capture/replay | Main §8; platform §3 | Capture manifest, interval eligibility, gaps and isolated playback specified. No inference-reproducibility guarantee; persistence tests remain. |
| S6 — extraction default | Main §10; source review; platform rule | Standard facility/public API before justified adapter/extraction/fork. Dependency/license inventories remain release work. |

## Independent patch check and validation scope

A read-only follow-up examined the revised main document and both contracts. Its five material corrections were incorporated: closure requests merge monotonically; sample receipts report applied values/time; normal-cancel and fault/rearm sequences differ; first proposal uses a request key before robot operation allocation; device-open failure does not imply a causal policy denial. The reviewer confirmed research requirements for measurement support, normalization, lineage, uncertain outcomes and evaluation denominators were present.

A final focused recheck found no remaining material contradiction in those five fixes. Sample-receipt naming was aligned with `SAMPLE_APPLIED`, and daemon seccomp installation was assigned to its own startup code rather than an external launcher. This is document review, not proof of the eventual implementation.

Documentation validation passed across 13 Markdown documents: 90 local links, one local anchor, balanced fences, exactly 34 finding IDs, all 40 original problem IDs, all 15 paper entries and both baseline hashes. Stale conflicting worker/revoke/release/CLI rules were checked in the active architecture. This is not kernel/firmware synchronization, real-clock, storage-durability or physical verification. Historical source inspections were not rerun as runtime tests.

## Brief cross-reference remediation

The subsequent independent review mapped all 40 brief items and all 15 research references against the first patch. The user authorized correcting its five remaining findings and the narrower replay clarification. This section records that second patch; the validation counts above describe the earlier round only.

| Finding | Current contract / changed surface | Disposition and required acceptance |
|---|---|---|
| B1 — cancel before ID return | Platform §1 request identity; kernel operations; main §6/§9 SDK and CLI | Specified authenticated key lookup/cancel, stable handle before send, bounded terminal tombstones, terminal-wins persistence revisions and final submission ordering. Allocated closure never waits for storage; durable key closure, local closure and reconciliation differ. Test delayed request/lost response, cancel versus commit/submission, crash before acknowledgment, exhausted key storage and storage-stalled cancellation. |
| B2 — natural completion | Kernel urgent closure/transitions; main §6; platform demo | Specified internal `operation.finish` with `SKILL_FINISHED`, shared close/quiesce, first normal reason and stronger fault/revoke/expiry precedence. Group reuse waits for matched timely reconciliation; physical success remains separate. Test two naturally completed steps under one grant, delayed barriers and all finish/cancel/expiry races. |
| B3 — delegated resources | Platform §2 broker reservations/coverage; main §5 and D2 | Specified per-attempt/global lifetime reservations and durable external-dispatch records using SQLite. Cancellation/restart cannot reclaim unknown provider work; settled consumption remains charged. Test approved-call flooding, oversized responses, cancellation/restart, unknown outcomes and accounting recovery while another admitted attempt runs. |
| B4 — preparation capacity | Platform §1; main §6/§9 and D3 | Specified active/staged/retiring high-water reservations, bounded preparation workers/inputs/deadlines, stopped-sandbox limits and actual cleanup before release. Deterministic rejection preserves A; daemon failure follows owner loss. Test exhaustion, allocation failure, abandonment, failed activation, replacement and restart without leaks/overcommit. |
| B5 — native endpoint reuse | Kernel semantic obligations; main §7/D0; source/adoption review | Fixture v2 remains selected for the custom fixture. Native APIs may qualify through a named exclusive kernel backend after mapping identical required semantics and running common fault traces. Incompatible command modes or missing obligations reject; firmware forks need demonstrated gaps. No native endpoint is declared conformant. |
| Replay clarification | Platform §3; main §8 | V1 execution replay requires activation plus complete ordered input prefix. Partial captures permit event playback with unknown state; replay-only checkpoints are deferred. Test a requested interval beginning after an earlier clamp/intervention; reconstruct its prefix or refuse execution replay. |

The CLI examples, Python request-handle contract, normal-success demonstration, preparation/broker stress cases, source/adoption guidance and README now agree with these rules. Native protocol conformance does not weaken deadline, stale-work, receipt or physical-evidence requirements. The custom kernel remains mandatory. No additional framework, controller claim or physical qualification was introduced.

A separate read-only reviewer examined the amended main document and both contracts and found no material contradiction in B1–B5 or replay. The root integration review additionally aligned context closure on skill finish, historical key queries after retirement and retained attempt identity while external reservations remain. This is a design review, not an executed concurrency proof.

Second-round document checks passed across 17 Markdown files: 128 local links, two local anchors, balanced fences and all five preserved baseline hashes. The ledger retains the original 34 finding rows and adds B1–B5 plus replay; the historical brief review retains all 40 problem rows and 15 research-reference rows. Required-contract and stale-rule checks covered request-key cancellation, normal finish, resource accounting, native-protocol conformance and replay state. No runtime, kernel, firmware, model or physical test was executed by these checks.

## Comparative architecture remediation

The user subsequently requested comparison with `/home/utkarsh/Downloads/arch.md`, then authorized applying the recommendation. That file remains the comparison input; active workspace documents carry the reconciled design. Historical reviews and preserved baselines remain unchanged.

| Comparison finding | Selected change / retained boundary |
|---|---|
| Repository count and distribution | One initial `volnlabs/voln` monorepo, named subsystem owners, canonical UAPI under `kernel/`, and independent server/robot/target artifact promotion. Target publication cannot silently change a qualified robot tuple. |
| Network gateway | Separate unprivileged encrypted-stream relay; mTLS and original-principal authorization remain in the manager. No kernel handles/keys are delegated to the gateway. Manager-side resource limits, process-lifetime binding, explicit session closure and direct local recovery are specified in the platform contract. |
| Shared Rust | Portable Rust reducer and thin target-supported kernel glue are the first candidate. An exact-build/export/lifetime gate may select a narrow C fallback. Independent expected transitions and fault vectors remain required; shared implementation is not its own correctness oracle. |
| CLI and delivery | Guided view uses existing stable identities and separately authorized grant/rearm/activation operations. Package/profile boundaries are concrete; server delivery runs alongside robot feasibility work. |
| Repeatability and buyer evidence | A second operator installs the same supported target/profile before expansion to another controller. Independent displacement and operational-cost evidence remain required. An open-core split is not validated demand; customers need applicable acceptance and qualification evidence. |
| Unsafe source assumptions | Reject wakeup-as-drain, harmless-flush/COBS, close-as-owner-death and program-tag-as-full-integrity arguments. Preserve immutable partial-frame recovery, task-bound ownership, fixed V1 predicates and exact observation provenance. The source review records supporting locations. |
| Extraction and physical protection | Existing allocation/panic/dependency behavior must be inventoried before adaptation. The FPGA watchdog spans top-level logic and an assumed clock; a rewrite needs fresh qualification. No measured timeout or qualified BOM is inferred. |
| Scope and reuse | Keep selective upstream dependencies, existing SQLite/MCAP/crypto/runtime machinery and all fifteen research-reference dispositions. No new VMM, general verifier/JIT or blanket dependency ban is introduced. |

The patch preserves urgent closure, durable request-key cancellation, natural completion/quiescence, broker/preparation reservations, recorder-health revocation, native endpoint equivalence and replay prerequisites. Gateway compromise may deny network service; only the direct local path and finite independent authority bounds provide the declared recovery behavior.

Validation for this round is document consistency and link checking only. The new gateway lifetime/authentication/resource fixtures, shared-Rust target build and every existing runtime/physical gate remain unexecuted. Earlier validation counts above apply only to their recorded rounds.

## Remaining gates

The revised contracts can guide bounded implementation/feasibility work. Exact release support still requires D0 source/build/route selection, software conformance and physical qualification. Required quantitative fields cannot use guessed safe defaults; missing values keep physical activation inhibited.

No product or reference source, dependencies, models, pairing, firmware or actuators were changed/run by this patch. The root workspace is not a usable Git repository; documents are saved, with no commit claimed. Account quota telemetry was unavailable, so usage was unknown; at most three bounded subagents were used.
