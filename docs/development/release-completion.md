# v0.0.1 release completion checklist

Approved continuation, 2026-10-19. Integration: `feat/v0.0.1`; existing PR #1.

Goal: qualified, signed software-preview candidates and a review-ready PR. Merge,
tagging, publication and physical qualification remain separate. Live motion stays inhibited.

## Execution order

- [ ] Preserve referenced evidence, verify restoration, and confirm a durable private archive destination before guest mutation.
- [ ] Resolve A16: preserve FAILED79/80; diagnose, regress/fix a supported defect, freeze a successor and run correctness pilots plus the full 80-trial ABBA campaign. Passing diagnostics alone cannot resolve the original failure.
- [ ] Freeze exact payloads and dependencies; resolve Robot Expat pin; qualify selected installed bytes using reviewed reuse or targeted new cases.
- [ ] Add host CI and obtain actual green checks at the final head; retain privileged target evidence separately.
- [ ] Complete A13 with broker-only provisioned credentials and A14 with an independent developer.
- [ ] Obtain role-scoped custodian attestations/signatures, verify final bundle installation and archived evidence, then update PR #1 for review.

## External inputs

| Input | Owner / location | State |
|---|---|---|
| Model credential | Provisioning owner unconfirmed; `/etc/actryn/credentials/openai-api-key` via systemd server-only LoadCredential | BLOCKED_EXTERNAL |
| Independent installer | Unconfirmed; another developer using shipped instructions on fresh supported guests | BLOCKED_EXTERNAL |
| Signing custodian | Unconfirmed; externally managed Ed25519 identity and trusted SPKI fingerprint | BLOCKED_EXTERNAL |
| Durable private archive | Destination and retention owner unconfirmed; no raw upload authorized to an identified destination | BLOCKED_EXTERNAL |

## Acceptance work

Snapshot from `final-qualification.json`; these are remaining tasks, not acceptance claims.
Every closure must name selected source/configuration/payload identities and immutable evidence.

| Gate | Required behavior | Remaining task |
|---|---|---|
| A01 | Two natural completions under one grant; reconcile before reuse | Associate manager11-to-e36 reconciliation delta with selected Robot; do not substitute a one-operation combined demo. |
| A02 | Cancellation absent/allocated before ID reply, races and lost acknowledgements | Manager10/module16 origin must remain distinct from selected e36; preserve pre-send/commit-race scope. |
| A03 | Expired, retired, replayed or changed duplicates cannot regain authority | Final selected manager/source association remains open; no replay of original unknown operations. |
| A04 | Restarts preserve unknown outcomes and prevent automatic resend | Original finalization/abort uncertainty remains; cleanup cannot relabel task success or qualify every restart/media fault. |
| A05 | Broker reservations survive cancel, oversized replies, unknown work and restart | Bind source/config/global-accounting lineage; real-provider charge/streaming behavior remains A13. |
| A06 | Malformed UAPI, task/FD identity, owner exit, concurrent closure, detach and PM faults | Mocked PM/shutdown callbacks are not physical UART/platform poweroff qualification; retain actual configuration/source bindings. |
| A07 | Every-byte cancellation, short/error writes, retained bytes and invalid receipts | Mocked serdev byte-offset tests must not become measured physical stopping evidence. |
| A08 | Exhaustion preserves reserved closure and active-work semantics | Retain exact limits and source lineage; do not infer untested PID/IO/storage exhaustion. |
| A09 | Storage stalls cannot block urgent closure; failed durability cannot authorize effects | SQLite contention is not fsync-stall/EIO/media-power-loss proof; current-cohort closure/durability applicability remains explicitOPEN. |
| A10 | Forged/flooded/replayed gateway traffic and retained FDs cannot widen authority; offline recovery | Older failures/uncertain negative reply and capture-prefix boundaries stay; zero SAMPLE is not applied-motion proof. |
| A11 | Evidence origin, gaps and durable frontiers; complete-prefix replay only | No new raw decoding performed; metadata-only histories remain execution-replay-ineligible. |
| A12 | Clean installation, tuple rejection and interrupted update/rollback without grants | Unsigned final9f/da6 exact bundles are uninstalled; runtime Restart=no overrides are not packaged on-failure. Robot observedExpat2.9 vsmanifest2.8.3 remains an explicit tuple-equality gap. |
| A13 | Pinned live hosted-model proposals traverse real isolated/kernel-gated path | Authorized provider provisioning and actual pinned live-model execution are EXTERNAL/NOT_RUN; no credential inspection or reuse. |
| A14 | Independent developer installs, diagnoses, cancels/recovers and exports | An independent human developer and actual installation/use report remainEXTERNAL; agent execution is not a substitute. |
| A15 | KUnit/selftests and identified lockdep/KASAN/KCSAN runs | Bind unchanged selected module/hash/config and preserve nonphysical scope; not whole-release qualification. |
| A16 | Latency/overhead/loss and competent userspace comparison without superiority threshold | Historical BIND role/errno/cause remains unobserved; diagnostic success does not repair FAILED79/80 or authorize replay/superiority/WCET/physical claims. |

## D2 predicate work

| Gate | Required behavior | Remaining task |
|---|---|---|
| D2-01 | Installed exact tuple, doctor/config validation and rejected incompatible/unapproved inputs | Runtime04 installation/source association retained; final assembled9f is not installed. |
| D2-02 | Identity/attribution before Create; paused Create before Start; fixed OCI options and no agent hooks | Original literal pre-Create gap remains historical. Approved025e contract adopts gatedCreate/FIFO then live enforcement/listeners beforeStart; staged3ead GREEN04 supplies common verification cleanup and preserves admission refusal. Root final mapping still required. |
| D2-03 | Unavailable host files, credentials and engine sockets; identity/mount/capability/FD isolation plus attributed failures | Frozen03 scoped contribution retained; selected final9f applicability remainsOPEN. |
| D2-04 | Only approved character devices; existing forbidden-node failed-open control | Existing device/OOM composite is a scoped case proof, not original campaignPASS; launcher17a0-to3ead source/build association remains final-review input. |
| D2-05 | No direct external/controller network; topology, no inherited network socket and negative connect evidence | Later association05 accepts separate trusted netnsENETUNREACH plus original agentAF_INETdenial/noinheritedsocket evidence as preview coverage. Frozen03literalOPEN is not rewritten; no agent externalconnect is claimed. |
| D2-06 | Privileged bpf/perf/mount/namespace operations unavailable, with selected syscall entry/return evidence | Frozen03 scoped contribution retained; selected final9f applicability remainsOPEN. |
| D2-07 | Explicit finite CPU, memory, PID and I/O limits; counters and pressure diagnosis | Existing device/OOM composite is a scoped case proof, not original campaignPASS; launcher17a0-to3ead source/build association remains final-review input. |
| D2-08 | Authenticated fixed broker methods/resources; allowed control and attributable forbidden-method denial | Frozen03 scoped contribution retained; selected final9f applicability remainsOPEN. |
| D2-09 | Atomic finite per-attempt/global broker reservations, request/output/deadline caps and overload cancellation | Frozen03 scoped contribution retained; selected final9f applicability remainsOPEN. |
| D2-10 | Unknown external work stays charged through cancellation/restart; no redispatch; publication stays closed | Frozen03 scoped contribution retained; selected final9f applicability remainsOPEN. |
| D2-11 | Prepared/retiring capacity and allocation/reclaim failure preserve admitted work and reserved closure | Frozen03 scoped contribution retained; selected final9f applicability remainsOPEN. |
| D2-12 | Required-enforcement installation failure rejects launch and destroys/quarantines preparation safely | CAP_BPF-absent EPERM required-load failure and later Start cleanup remain separate; original FAILED/unknown reply stays intact. |
| D2-13 | Loss of required enforcement closes launches, quarantines channels and terminates affected attempts | Frozen03 scoped contribution retained; selected final9f applicability remainsOPEN. |
| D2-14 | Diagnostic-reader death/loss is explicit, enforcement persists, new diagnostic launches close | Frozen03 scoped contribution retained; selected final9f applicability remainsOPEN. |
| D2-15 | Measured observation overhead and loss, with explicit workload/configuration and denominator | Frozen03 scoped contribution retained; selected final9f applicability remainsOPEN. |
| D2-16 | Cleanup/export preserve attribution, kill/reap descendants, revoke local channels, retain unresolved accounting | Frozen03 scoped contribution retained; selected final9f applicability remainsOPEN. |
| D2-17 | Independent Server operator diagnosis story: memory pressure, forbidden access, unauthorized method, inspection/export without Robot grant | Root accepts fixed offline case composition only; exact single multimodal-batch story/live provider remainsNOT_RUN. |

## Execution ledger

- Start: clean branch at `3b2aed5`; PR #1 is draft. Goal API still reports historical paused state and has no resume operation; user continuation is authoritative.
- Ruling: implement in the requested integration checkout; leave existing linked worktrees and their user changes untouched.
- Ruling: existing tracked qualification packet remains an immutable checkpoint. New checks do not flip its historical flags or manufacture custodian approval.
- Preflight: 16 GiB free on repository filesystem. No duplicate VM images or guest mutation before evidence custody is ready. Account quota telemetry unavailable.
- Baseline: `cargo test --workspace --locked` passed; retained local log `/tmp/actryn-release-baseline-rust.log`.
- In progress: host CI with source/exit/log receipts; A16 read-only investigation and host-only reproducer.

### Checkpoint 1: host CI and evidence preservation

- Added `ci/check.py` and GitHub Actions for Rust, Python and kernel-host suites. Local Rust format/Clippy/workspace tests passed; kernel-host checks passed (5 bridge and 116 A16 Python checks plus C sanitizer assertions); Python passed 292 tests after correcting the stale documentation snippet inventory. Original failed run remains in `artifacts/release-completion-host01/python`; corrected run is `artifacts/release-completion-host02/python`.
- Five CI helper tests verify failure retention, continued checks, no overwrite, missing-command failure and historical packet claim/reference checks. Actionlint 1.7.12 passed; independently resolved action SHAs are pinned. Remote execution remains pending the push.
- `ci/qualification.py --receipt-root .` verified 107 receipt references and both 44-entry manifest projections; CI without local artifacts reports zero receipt files verified. Neither mode qualifies the release.
- Preserved 105 unique files (107 receipt references, four larger sources, two payloads and the packet, with shared paths deduplicated) in a 122,890,240-byte local archive and restored/hash-verified every entry. Receipt: `artifacts/release-evidence-preservation01/result.json`; archive SHA256 `9fa503ad49dd24cf261db284e360975eb30899e489a980e1320e6f1ee47b75ce`. This is a selected-evidence snapshot, not a complete raw/VM backup or durable off-host archive. No private key or VM image was read.
- Independent checkpoint review found no actionable important CI findings. It did not verify hosted CI or target qualification.
- A16 read-only review found an actual host-reproducible post-accept/pre-SO_PASSCRED credential race. Historical causality remains unproven. Next: preserve frozen sources and add a separately numbered regression/fixed derivative, then qualify that derivative on the pinned guest after archive prerequisites are met.
