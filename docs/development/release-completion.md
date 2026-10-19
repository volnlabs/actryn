# v0.0.1 release completion checklist

Approved continuation, 2026-10-19. Integration: `feat/v0.0.1`; existing PR #1.

Goal: qualified, signed software-preview candidates and a review-ready PR. Merge,
tagging, publication and physical qualification remain separate. Live motion stays inhibited.

## Approved solo amendment, 2026-10-19

The [solo plan](../superpowers/plans/2026-10-19-actryn-solo-preview.md) and
[maintainer handoff](solo-preview-handoff.md) govern current work. Utkarsh Maurya
owns credentials, release signing, external-drive evidence retention and a manual
fresh-install rehearsal. Original independent A14 is DEFERRED; technical gates
are unchanged. Earlier ledger entries below remain historical observations.
The [successor packet](solo-preview-qualification.json) records current readiness
without modifying the historical incomplete packet.

## Execution order

- [x] Preserve referenced evidence, verify restoration, and confirm a durable private archive destination before guest mutation.
- [x] Resolve A16: preserve FAILED79/80; diagnose and regress the listener-credential race, freeze the passcred10 successor, then pass two excluded correctness pilots and the full 80-trial ABBA campaign.
- [x] Freeze exact payloads and dependencies; resolve Robot Expat pin; qualify both selected payload byte sets on fresh exact target guests through disposable test-signed manifests.
- [x] Add host CI and obtain actual green push/PR checks; retain privileged target evidence separately and require the exact review head to remain green.
- [ ] Complete A13 with broker-only credentials and the separate maintainer installation rehearsal; original independent A14 is DEFERRED.
- [ ] Obtain role-scoped custodian attestations/signatures, verify final bundle installation and archived evidence, then update PR #1 for review.

## Solo implementation checkpoint

- Successor has 31 bounded software PASS associations, original A14 DEFERRED and
  four required gates open: A12 packaged restart behavior, A13 live execution,
  maintainer installation and key recovery.
- Local successor validation verifies 145 small receipt references, all 107
  historical receipts, exact manifest projections and both payload archive hashes.
  This is integrity/readiness checking, not maintainer approval or release signing.
- A09 now composes actual host journal-fsync stall/EIO tests on selected unchanged
  robot-intent sources with earlier real-kernel SQLite contention. Host test
  authority and real-kernel evidence remain distinct; no physical-media claim.
- Explicit combined live harness mode permits one provider call and preserves
  original observation freshness, accounting, lineage and kernel completion checks.
  Host regression passed; no provider call has run in this continuation.
- External-drive evidence custody passed on the dedicated filesystem UUID
  `0347-DCDB`: the encrypted 234,789,052-byte copy hash-matched, was decrypted
  from the drive, and all 3,474 inventoried files plus the qualification packet
  and both payload archives verified. The drive was not formatted.
- Signing and manual-installation instructions are ready in the handoff. No
  release identity was created and no personal/independent installation report
  was manufactured.
- Final signed-distribution verification is a separate post-attestation receipt,
  so a frozen qualification hash does not depend on signatures of itself.

## External inputs

| Input | Owner / location | State |
|---|---|---|
| Model credential | Utkarsh Maurya; `/etc/actryn/credentials/openai-api-key` via systemd server-only LoadCredential | Provisioning pending |
| Independent installer | Unassigned until another developer joins; original A14 | DEFERRED, not a solo-release gate |
| Maintainer rehearsal | Utkarsh Maurya personally follows shipped instructions on fresh guests | NOT_RUN, required |
| Signing custodian | Utkarsh Maurya; dedicated encrypted Ed25519 identity and trusted SPKI fingerprint | Key establishment/recovery pending |
| Durable private archive | Utkarsh Maurya; encrypted archive on filesystem UUID `0347-DCDB` | PASS; encrypted copy and full restored inventory verified |

## Acceptance work

Snapshot from `final-qualification.json`; these are remaining tasks, not acceptance claims.
Every closure must name selected source/configuration/payload identities and immutable evidence.

| Gate | Required behavior | Remaining task |
|---|---|---|
| A01 | Two natural completions under one grant; reconcile before reuse | Fresh final-payload lifecycle01 passes two reconciled natural completions under grant 1 with operation IDs 1 then 2. Bind the retained receipt into the final qualification packet. |
| A02 | Cancellation absent/allocated before ID reply, races and lost acknowledgements | Manager10/module16 origin must remain distinct from selected e36; preserve pre-send/commit-race scope. |
| A03 | Expired, retired, replayed or changed duplicates cannot regain authority | Fresh final-payload lifecycle01 supplies selected-manager association; no replay of original unknown operations. Packet reconciliation remains. |
| A04 | Restarts preserve unknown outcomes and prevent automatic resend | Original finalization/abort uncertainty remains; cleanup cannot relabel task success or qualify every restart/media fault. |
| A05 | Broker reservations survive cancel, oversized replies, unknown work and restart | Bind source/config/global-accounting lineage; real-provider charge/streaming behavior remains A13. |
| A06 | Malformed UAPI, task/FD identity, owner exit, concurrent closure, detach and PM faults | Mocked PM/shutdown callbacks are not physical UART/platform poweroff qualification; retain actual configuration/source bindings. |
| A07 | Every-byte cancellation, short/error writes, retained bytes and invalid receipts | Mocked serdev byte-offset tests must not become measured physical stopping evidence. |
| A08 | Exhaustion preserves reserved closure and active-work semantics | Retain exact limits and source lineage; do not infer untested PID/IO/storage exhaustion. |
| A09 | Storage stalls cannot block urgent closure; failed durability cannot authorize effects | SQLite contention is not fsync-stall/EIO/media-power-loss proof; current-cohort closure/durability applicability remains explicitOPEN. |
| A10 | Forged/flooded/replayed gateway traffic and retained FDs cannot widen authority; offline recovery | Fresh final-payload lifecycle01 passes gateway death, old-namespace rejection, local recovery and retained evidence. Older failures/uncertain negative reply and capture-prefix boundaries stay; zero SAMPLE is not applied-motion proof. |
| A11 | Evidence origin, gaps and durable frontiers; complete-prefix replay only | No new raw decoding performed; metadata-only histories remain execution-replay-ineligible. |
| A12 | Clean installation, tuple rejection and interrupted update/rollback without grants | Fresh exact Robot and Server targets install the da6 and 9f payload bytes through test-signed derivatives and pass rejection, interruption, recovery, rollback, bootstrap and lifecycle. Both canonical manifests remain unsigned/uninstalled; runtime Restart=no overrides are not packaged on-failure. |
| A13 | Pinned live hosted-model proposals traverse real isolated/kernel-gated path | Authorized provider provisioning and actual pinned live-model execution are EXTERNAL/NOT_RUN; no credential inspection or reuse. |
| A14 | Independent developer installs, diagnoses, cancels/recovers and exports | An independent human developer and actual installation/use report remainEXTERNAL; agent execution is not a substitute. |
| A15 | KUnit/selftests and identified lockdep/KASAN/KCSAN runs | Bind unchanged selected module/hash/config and preserve nonphysical scope; not whole-release qualification. |
| A16 | Latency/overhead/loss and competent userspace comparison without superiority threshold | The original FAILED79/80 result remains immutable and its exact BIND cause remains unproven. A separately frozen passcred10 successor passes two excluded pilots and all 80 comparison trials on six distinct pinned-kernel boots, with 78/78 matches in every traced run and zero recorded loss/discontinuities. Final packet binding remains; no superiority, WCET or physical claim follows. |

## D2 predicate work

| Gate | Required behavior | Remaining task |
|---|---|---|
| D2-01 | Installed exact tuple, doctor/config validation and rejected incompatible/unapproved inputs | Fresh Robot and Server final-payload installs/bootstrap pass under exact pinned tuples. Server rejects unsigned, incomplete, wrong-host and wrong-role candidates before managed-path mutation; its canonical 9f manifest remains unsigned/uninstalled. |
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
- In progress: A12 packaged restart, A13 live execution, maintainer rehearsal and signing-key recovery. A14 remains deferred; A16 successor, both exact final payload software campaigns and external archive restoration are complete below.

### Checkpoint 1: host CI and evidence preservation

- Added `ci/check.py` and GitHub Actions for Rust, Python and kernel-host suites. Local Rust format/Clippy/workspace tests passed; kernel-host checks passed (5 bridge and 116 A16 Python checks plus C sanitizer assertions); Python passed 292 tests after correcting the stale documentation snippet inventory. Original failed run remains in `artifacts/release-completion-host01/python`; corrected run is `artifacts/release-completion-host02/python`.
- Five CI helper tests verify failure retention, continued checks, no overwrite,
  missing-command failure and historical packet claim/reference checks. Actionlint
  1.7.12 passed; independently resolved action SHAs are pinned. Both push and PR
  workflows on code head `2b322fc` completed all Rust, Python and kernel-host jobs
  successfully. Later documentation/evidence head `5cf318d` also completed all six
  jobs successfully; the PR exact-head rollup remains the review-time authority.
- `ci/qualification.py --receipt-root .` verified 107 receipt references and both 44-entry manifest projections; CI without local artifacts reports zero receipt files verified. Neither mode qualifies the release.
- Preserved 105 unique files (107 receipt references, four larger sources, two payloads and the packet, with shared paths deduplicated) in a 122,890,240-byte local archive and restored/hash-verified every entry. Receipt: `artifacts/release-evidence-preservation01/result.json`; archive SHA256 `9fa503ad49dd24cf261db284e360975eb30899e489a980e1320e6f1ee47b75ce`. This is a selected-evidence snapshot, not a complete raw/VM backup or durable off-host archive. No private key or VM image was read.
- Independent checkpoint review found no actionable important CI findings. It did not verify hosted CI or target qualification.
- A16 read-only review found an actual host-reproducible post-accept/pre-SO_PASSCRED credential race. Historical causality remains unproven. Next: preserve frozen sources and add a separately numbered regression/fixed derivative, then qualify that derivative on the pinned guest after archive prerequisites are met.

### Checkpoint 2: A16 listener credential race

- Host RED: a BIND sent after `accept4` but before accepted-socket `SO_PASSCRED`
  reached the actual receiver/dispatcher as PID0, UID/GID65534 and returned
  `-EPERM`. This is consistent with the historical failure class, but the old
  record did not retain enough data to prove causality.
- Numbered derivative10 enables `SO_PASSCRED` after listener bind and before
  listen; the frozen comparison gateway remains byte-unchanged. The forced race
  then preserves the real sender credentials and all four BIND roles pass.
- Ruling: retain FAILED79/80 and treat derivative10 as a candidate correction,
  not A16 closure. Cost if wrong: the release stays blocked until the pinned-guest
  pilot and complete newly frozen comparison establish applicability.
- No guest, fixture, credential, manifest or selected payload changed. Target
  build/review, successor freeze and the full ABBA campaign remain pending.
- Recorded host receipt `artifacts/release-completion-host03/kernel-host/result.json`
  is PASS with three checks: kernel wire sanitizer assertions, five fixture-bridge
  tests, and the complete A16 host suite with 118 Python tests plus its C sanitizer
  assertions and fixed-profile check. The receipt correctly records a dirty
  worktree at source revision `02d8cf3`; the commit below binds the tested delta.

### Checkpoint 3: fresh Robot target correction

- The exact Debian13 ARM64 base image is present and independently rehashed to
  the manifest SHA512 `a34e1c1e…f915c4`.
- `.cache/qemu/install-robot` is not the never-launched target described by its
  initial `prepared.json`: retained launch/provision/update receipts, serial,
  fixture and manager state prove it has been used. It remains preserved and was
  not launched or changed in this checkpoint.
- Ruling: do not restore Expat or run A14 on that disk. Create a new uniquely
  named overlay/seed from the verified base, provision the exact supported tuple,
  and keep the retained Robot as historical evidence. Cost if wrong: reusing it
  would invalidate clean-install and package-equality claims.
- The current selected candidate pins Expat 2.8.3 while the retained Robot has
  2.9.0. The new guest independently reports the exact ten-package tuple,
  including `libexpat1 2.8.3-1~deb13u1`; no package mutation was required and the
  manifest was not rewritten to bless retained-disk drift.
- A new 16 GiB copy-on-write target at `.cache/qemu/install-robot-final01` binds
  the independently rehashed base, kernel, initrd, DTB, source-bound fixture and
  final Robot manifest/payload `da6b6862…cc5a9` / `1e71fe91…66bb`. Preparation,
  one launch and host-key/exact-tuple preflight are retained separately. The old
  `.cache/qemu/install-robot` disk was not read through QEMU or changed.
- The existing installer harness produced test-only campaign
  `ff560d50cff448c0a4ff898e651a08ba`. Its exact final payload passed unsigned,
  incomplete, wrong-host and wrong-role rejection; stage/activate; an injected
  exit after durable pointer publication; explicit recovery and rollback;
  sentinel preservation and persistent inhibition. This does not sign or promote
  the canonical final manifest.
- The reviewed bootstrap harness changed only campaign/manifest/key identities
  and its unique receipt path. It verified module `a49fd1a…112`, manager
  `e36d5b…72a`, gateway `8705d2…22f` and the installed ARM CLI, then recovered to
  an inhibited healthy state without issuing authority.
- The unchanged full lifecycle passed in 132 seconds: two natural operations
  reconciled under one grant; absent and pre-send cancellation became durable;
  gateway death revoked; manager death retained terminal `OutcomeUnknown`
  without resend; identity rotation retired the old session; CLI/SDK exported
  and hash-verified 35 files; the independent capture reader passed. The final
  read-only state had no grant, operation or preparation and required a fresh
  recovery mapping before future authority. The guest and fixture then completed
  normal shutdown. Failed postflight validators that over-required a still-fresh
  recovery mapping remain preserved beside corrected local validation.
- All new Robot evidence remains local, test-signed, nonpromotable and explicitly
  `release_qualification=false`; it is not A14 independent-operator evidence or
  physical qualification.

### Checkpoint 4: A16 passcred10 successor qualification

- The original comparison remains FAILED79/80 at receipt
  `d4f3ef18…1b8e`; no trial was retried or relabelled. Its stopped parent disk
  remains byte-identical at `cf7b67ab…87de`.
- The supported defect is the actual gateway listener window between `accept4`
  and accepted-socket `SO_PASSCRED`. Frozen derivative source
  `7858e167…273e` enables credentials on the bound listener before `listen`, so
  accepted sockets inherit collection from their first queued message. Host race
  tests pass 2/2. The exact pinned ARM64 guest built target gateway
  `18fc5861…3835` with GCC 14.2.0-19 on kernel 6.12.111; workload
  `40f75fe9…2398` and module `a49fd1a…1112` remained unchanged.
- A new copy-on-write guest and fixture use isolated ports, units, evidence labels
  and state. One initial launch with a changed MAC reached multi-user but left the
  provisioned interface down; its no-workload failure and normal QMP poweroff are
  preserved. The numbered correction restored the provisioned MAC before any
  build or test action.
- Frozen successor source12 (`e0392fb7…b47f` runner,
  `8cc7d05f…bf76` campaign) passed focused host checks and a full read-only
  baseline/VM/fixture/instrumentation preflight. Separate kernel and userspace
  trace pilots each pass 10/10 with 78/78 correlations.
- Four distinct ABBA boots then run the fixed evidence/trace ordering once. All
  80 planned trials begin, end and pass; each traced run matches 78/78 eligible
  requests, with zero recorded event loss, sequence discontinuities or reversed
  clock pairs. Block 3, including the old failure position, passes 20/20.
- Independent local analysis receipt `27104456…d9e8` reparses raw trial logs,
  verifies denominators, boot uniqueness, trace correlations and source/binary
  pins, and preserves the old failure. Final stopped custody
  `216e3586…d7a8` records both successor units inactive/PID0/empty cgroups,
  free ports and no repository VM/fixture actor.
- This closes the A16 software comparison for the successor only. Evidence is
  local and ignored by Git, `release_qualification=false`, with no physical,
  UART-drain, WCET or superiority claim. It does not close A13, A14, signing,
  durable archive custody or whole-release qualification.

### Checkpoint 5: fresh final Server target

- The exact final Server manifest/payload remain
  `9f749ca3…a90f` / `7b596c87…fe71` (70,666,240 bytes). Disposable fixture job
  `6b8c14cf…bf23` rebuilds that payload byte-identically and adds only test
  qualification metadata/signatures; it does not sign or install the canonical
  incomplete manifest.
- A new copy-on-write guest at `.cache/qemu/install-server-final01` uses the
  independently rehashed Debian 13.7 amd64 base `d4721b56…345d`, kernel
  `6.12.111+deb13-amd64`, QEMU 11.1.1 and all 14 exact package pins. The initial
  read-only preflight correctly found the base image lacked containerd, runc and
  Python venv support. That failure is preserved; one explicit pre-installation
  provisioning step installed the pinned packages, after which the same
  boot/machine identity passed and still contained no Actryn state.
- Campaign `fa45517ec6f644abb5298e441be5ee07` passes unsigned, incomplete,
  wrong-host and wrong-role rejection; stage/activate; injected exit after
  durable pointer publication; explicit recovery and rollback; sentinel
  preservation; and inhibited preflight/resume rejection. No service starts and
  no authority is issued during installation.
- Explicit bootstrap verifies installed launcher `3ead4e49…fe30`, imports the
  shipped offline OCI artifact and clears the installation gate without
  auto-start. The unchanged reviewed lifecycle then rejects a tampered artifact,
  observes uid/gid 65532, zero capabilities, no-new-privileges, seccomp mode 2,
  distinct PID/mount/network/IPC/UTS/cgroup namespaces, zero IPv4 routes,
  read-only root, device-policy programs and exact CPU/memory/PID/I/O limits.
  The fixed skill returns one server-attested offline proposal; both attempts
  cancel and reap with loss-free observer summaries and removed cgroups.
- A complete service stop/start preserves byte-equivalent Launcher/Broker rows,
  reaped outcomes and closed publication without agent reexecution. Export
  `6e152833…1d8e` verifies all six evidence artifacts and remains
  execution-replay-ineligible. Normal poweroff and stopped custody
  `19a02faa…f56` record the VM inactive/PID0/NRestarts0, free port, no repository
  actor, unchanged base pin and overlay `2a716a43…a5d5`.
- This closes exact-final-payload Server installation, positive isolation,
  cancellation, restart and export applicability. Broader negative/fault rows
  still rely on their explicitly mapped component/source evidence. The campaign
  is local, test-signed and `release_qualification=false`; it does not supply an
  independent installer, live provider credential, release custodian signature,
  durable off-host archive or physical qualification.
- Local addendum `204e7468…9ff8` archives and restore-verifies 80 new public
  scripts/receipts (276,480 bytes). It excludes VM images, payload duplicates and
  all private test/SSH keys. It is ignored local storage, not the still-required
  durable off-host archive.
