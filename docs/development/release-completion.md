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
The [v5 successor packet](solo-preview-qualification-v5.json) records current
readiness without modifying the predecessor, v2, v3, v4 or historical incomplete packets.

## Execution order

- [x] Preserve referenced evidence, verify restoration, and confirm a durable private archive destination before guest mutation.
- [x] Resolve A16: preserve FAILED79/80; diagnose and regress the listener-credential race, freeze the passcred10 successor, then pass two excluded correctness pilots and the full 80-trial ABBA campaign.
- [x] Freeze exact payloads and dependencies; resolve Robot Expat pin; qualify both selected payload byte sets on fresh exact target guests through disposable test-signed manifests.
- [x] Add host CI and obtain actual green push/PR checks; retain privileged target evidence separately and require the exact review head to remain green.
- [x] Qualify packaged guest service restart behavior on isolated overlays of both exact final installations.
- [x] Execute the frozen two-call A13 campaign once; retain its standalone PASS, combined stale-observation FAIL, uncertain debit, recovery and stopped custody without replay.
- [x] Qualify the reviewed execution-observation correction under one renewed call, close/export the consumed attempt, and install the two-binary successor on a fresh exact target.
- [x] Complete the separate maintainer installation rehearsal; original independent A14 is DEFERRED.
- [x] Complete the encrypted final-distribution archive/restore, run final host and hosted checks, and update PR #1 for review. Role-scoped signatures and fresh signed-bundle installation/bootstrap are complete.

## Solo implementation checkpoint

- The v5 successor packet has 35 bounded software PASS associations, original A14
  DEFERRED and no required gate open. It binds the two-binary Server successor,
  one-binary Robot recovery successor, completed maintainer installation and
  recovered release-key identity. The corrected off-host restoration and exact
  maintainer review make it ready for attestation without claiming release signing.
- Local successor validation verifies 188 small receipt references, all 107
  historical receipts, exact manifest projections and both payload archive hashes.
  The exact review is recorded. Both role manifests are now signed with the
  recovered release identity and their bundles pass fresh signed installation and
  non-starting bootstrap. Its final encrypted archive has been restored and the
  additive final receipt reports `PASS_SOFTWARE_PREVIEW_QUALIFIED` within the
  sole-maintainer, software-only boundary.
- A09 now composes actual host journal-fsync stall/EIO tests on selected unchanged
  robot-intent sources with earlier real-kernel SQLite contention. Host test
  authority and real-kernel evidence remain distinct; no physical-media claim.
- The frozen live campaign consumed exactly two provider calls with no retry.
  Standalone acceptance passed on the pinned model/artifact. The combined call
  settled 33 tokens, then the original one-second observation expired before
  dispatch and the agent reported `broker rejected proposal`; no operation was
  allocated and wheel outputs stayed zero. Later clock-checkpoint/mapping warnings
  occurred during retained-state inspection and are not assigned as the rejection
  cause. Local recovery passed while the uncertain debit remained charged, and
  both guests plus the fixture are stopped.
- One separately authorized A13-02 call consumed 27 tokens. The corrected Server
  captured observation 68 as model lineage, revalidated newer observation 91,
  executed operation 1 to `TargetReached`, and reconciled it with zero output.
  The installed predecessor CLI then rejected the newly added response fields.
  A current same-source CLI inspected, closed and exported the already-consumed
  attempt without another provider call. The exact successor package changes
  only `bin/actryn` and `bin/actryn-serverd`; it passes a fresh exact-target
  installation, offline lifecycle, restart/export and stopped custody. The
  tracked [qualification receipt](live-observation-qualification.json) preserves
  the composition boundary and does not claim a second live call.
- External-drive evidence custody passed on the dedicated filesystem UUID
  `0347-DCDB`: the encrypted 234,789,052-byte copy hash-matched, was decrypted
  from the drive, and all 3,474 inventoried files plus the qualification packet
  and both payload archives verified. The drive was not formatted.
- The human rehearsal completed on fresh test-signed Server and Robot guests. It
  retained the injected wrong-pin diagnosis, two reconciled operations under one
  grant, cancellation before proposal, restart recovery and hash-verified exports.
  The report is personal (`independent:false`); original A14 remains deferred.
- Final signed-distribution verification is a separate post-attestation receipt,
  so the frozen qualification hash does not depend on signatures of itself. The
  receipt passes signature, transfer, install, bootstrap, inhibited-state and
  stopped-custody checks on fresh exact-target guests. It composes the previously
  qualified identical payload workflow without replaying an operation or provider
  call. The final 106,106,880-byte plaintext archive was encrypted, copied to
  filesystem UUID `0347-DCDB`, decrypted from that drive copy, and all 68 entries,
  both signatures and the release key verified. Archive SHA256 is
  `a0830691a8ad02734e604a3adbe40ba2e82ec385f5e7ff6c5c68f61d375bbbab`;
  ciphertext SHA256 is
  `23092cfa49984cb34a6f4f59636953371f8dbc01cfb632e44d8b68bd3d0ef361`.
- The final pre-archive host sweep first failed under the restricted agent sandbox:
  local Unix/TCP socket creation returned `EPERM` across Python, Rust and C tests.
  That run is retained. A separately numbered rerun with ordinary local-socket
  permission passes all 11 Python groups, all four Rust checks and all three
  kernel-host checks. PR #1 qualification commit `fed6058` has six green hosted
  checks: Rust, Python and kernel-host on both push and pull-request workflows.

## External inputs

| Input | Owner / location | State |
|---|---|---|
| Model credential | Utkarsh Maurya; `/etc/actryn/credentials/openai-api-key` via systemd server-only LoadCredential | A13-02 used one separately authorized call; credential remained confined to the stopped disposable Server overlay |
| Independent installer | Unassigned until another developer joins; original A14 | DEFERRED, not a solo-release gate |
| Maintainer rehearsal | Utkarsh Maurya personally follows shipped instructions on fresh guests | PASS; human test-signed two-guest workflow and evidence export retained |
| Signing custodian | Utkarsh Maurya; dedicated encrypted Ed25519 identity and trusted SPKI fingerprint | PASS; both final manifests signed and independently verified against SPKI `3bc25f59…ce6735` |
| Durable private archive | Utkarsh Maurya; encrypted archive on filesystem UUID `0347-DCDB` | PASS; base, successor and corrected Robot addenda restored, and the final signed distribution was copied, decrypted from the drive copy and verified |

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
| A12 | Clean installation, tuple rejection and interrupted update/rollback without grants | Fresh exact Robot and Server targets install the da6 and 9f payload bytes through test-signed derivatives and pass rejection, interruption, recovery, rollback, bootstrap and lifecycle. Disposable overlays confirm all five packaged guest services retain one-second on-failure restart behavior and restart exactly once after controlled failure without creating Server work or widening Robot authority. Host VM wrappers use Restart=no; both canonical manifests remain unsigned/uninstalled. |
| A13 | Pinned live hosted-model proposals traverse real isolated/kernel-gated path | PASS by bounded composition for the corrected successor: one renewed call consumed 27 tokens, revalidated observation 68 with newer observation 91, completed/reconciled kernel operation 1 and closed/exported without retry. The predecessor packaged CLI schema failure is preserved. The exact two-binary successor separately passes fresh install/lifecycle/restart/export; it did not consume another provider call. The v4 packet binds this subject and evidence. |
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
- In progress: maintainer rehearsal. A14 remains deferred; successor-packet rebinding, A12 packaged restart, corrected A13 software behavior, A16 successor, exact payload campaigns, successor external archive restoration and signing-key recovery are complete below.

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

### Checkpoint 6: packaged service restart behavior

- New disposable overlays back the stopped final Server and Robot installation
  disks. The backing disks remain read-only through the overlays; unique QEMU,
  fixture and host-systemd identities avoid changing the retained campaigns.
- Guest inspection confirms `Restart=on-failure` and `RestartSec=1` in all five
  packaged services, with only the installer preflight drop-in and no
  `Restart=no` guest override. Host VM wrappers intentionally retain
  `Restart=no`; that host lifecycle policy is outside the guest packages.
- One controlled main-process SIGKILL per service produced an exact restart
  delta of one and a changed PID. Server had no container tasks or attempt
  cgroups before or after. Robot reported `live_actuation=false`, no operation
  and kernel operation zero after both restarts, then the Robot VM and fixture
  stopped normally.
- The first Robot start correctly failed closed because a fresh boot had not yet
  loaded the authority module required by the shipped runbook. That attempt is
  preserved. The exact installed module `a49fd1a…1112` and loaded build-ID note
  were verified with the character-device, serdev, DT-compatible and no-TTY
  checks; one unchanged exercise then passed.
- Receipt `338fdf6a…fb170` binds both exact selected payloads and the raw inspection,
  restart and failed-precondition records. This closes A12 for the test-signed
  mechanical campaign only. Final release-key-signed distribution verification
  remains post-attestation, and no physical qualification follows.

### Checkpoint 7: corrected live observation and package compatibility

- Clean source `a4ccbc4` retains the original model-input observation and captures
  exactly one newer execution observation after inference. It rejects regressed
  identity/time or changed encoder/context values before dispatch. Host checks and
  the exact corrected Server build passed before the renewed live call.
- A13-02 consumed its sole authorized call with no retry. The pinned model returned
  a bounded 500 ms zero-delta proposal using observation 68. Execution observation
  91 matched the model context, kernel operation 1 reached `TargetReached`, and
  Robot reconciliation removed the outstanding debit. The old installed CLI then
  rejected the added `execution_observation` field; that transport failure remains
  retained and is not relabelled as a clean same-package harness pass.
- The current same-source CLI performed read-only inspection and one explicit
  cleanup path only. The attempt is reaped, its publication is closed, the cgroup
  is absent, both stores have zero pending/open/outstanding rows, observer loss is
  zero, Robot recovery is ready, and Server plus Robot evidence exports passed.
  Cleanup made zero provider calls. Both guests and the fixture then stopped with
  free ports and hashed overlays.
- The successor unsigned Server candidate changes exactly `bin/actryn` and
  `bin/actryn-serverd`. Manifest `cf886513…9f87` binds payload
  `45829a38…3e82`; the other 25 entries retain their previous bytes, modes and
  licenses. CLI tests, clippy, section preservation and exact target-symbol checks
  pass. The candidate remains incomplete, unsigned and non-promotable.
- A fresh Debian 13.7 amd64 guest on kernel `6.12.111+deb13-amd64` passed all 14
  package pins, negative installer cases, durable-pointer interruption/recovery,
  rollback, bootstrap, two isolated offline attempts, service restart, state
  comparison, evidence export, normal poweroff and stopped custody. The fresh
  run executed both corrected package binaries but did not repeat the provider
  call. This bounded composition closes the software behavior while preserving
  the exact same-run package limitation.
- Tracked receipt `live-observation-qualification.json` binds the raw local
  evidence and limitations. The v2 solo packet now selects the two-binary Server
  successor and validates the old-to-new manifest delta, exact payload and A13
  composition while retaining the predecessor packet. Maintainer rehearsal,
  dedicated-key recovery, genuine signing and physical
  qualification remain separate.

### Checkpoint 8: successor evidence archive restoration

- A 91,740,160-byte addendum at source `a1c0c2b` contains 1,081 allowlisted files
  and 89,584,622 source bytes. It includes the exact successor payload, both A13
  campaigns, A12 restart, fresh-target and packet checks, and the current tracked
  tree. Private client keys, the disposable test-signing key, duplicate payloads
  and redundant build binaries are excluded explicitly.
- Symmetric AES-256 ciphertext `f8706573…11f99` was copied to external filesystem
  UUID `0347-DCDB`, flushed and compared byte-for-byte. Its drive copy decrypted
  to plaintext `84aa8450…cfc997` in a fresh restore directory.
- Safe regular-file overlay on the previously verified 3,474-file base passed all
  1,081 addendum inventory hashes. The restored v2 checker verified 168 receipt
  files, all 107 historical receipts and both selected payload archives. The v3
  packet records ARCHIVE-RESTORE PASS; no physical or independent claim follows.

### Checkpoint 9: dedicated release-key recovery

- Utkarsh created a passphrase-encrypted Ed25519 identity in a private local path.
  The encrypted key, public key and public hashes were copied to external filesystem
  UUID `0347-DCDB`; the encrypted local, drive and restored files are byte-identical
  at SHA256 `71d7be92…c6147b`.
- The original and restored public keys have SPKI SHA256 `3bc25f59…ce6735`.
  A fresh challenge verified with the restored key; the same signature was rejected
  after the challenge changed. The [public custody record](release-key-custody.json)
  contains no private key or passphrase.
- The v4 packet records KEY-RECOVERY PASS. No release manifest has been signed;
  final signing and distribution verification remain after maintainer attestation.

### Checkpoint 10: serialized recovery and sole-maintainer rehearsal

- Human rehearsal 01 exposed a real recovery race: `Recover` used a nonblocking
  clock-writer lock and rejected a request while the durable checkpoint was in
  progress. Source `b5aa65e` now serializes that boundary. Host tests, an ARM64
  build and the installed guest recovery regression pass; the original failure
  remains immutable.
- The successor Robot candidate changes only `bin/actryn-robotd`. Manifest
  `965928af…12e11` binds payload `2a2d9689…198e8`; its other 16 entries match the
  predecessor exactly. It remains unsigned, incomplete and nonpromotable.
- Utkarsh executed the fresh two-guest workflow through disposable test signatures.
  The deliberate wrong certificate pin failed before authority, two operations
  reached `TargetReached` under one grant with reconciliation before reuse, and
  cancellation before proposal remained durable. Explicit revoke/retire/recovery,
  service restart with changed PIDs and post-restart recovery passed with zero
  outputs and no live provider call.
- The first post-restart inspection correctly rejected the retired manager epoch.
  Numbered continuations rediscovered the new epoch without replay. A host/guest
  `--local` driver mistake and a missing guest export parent each stopped before
  cancellation; both failures remain preserved. The corrected guest-local export
  verified all 53 files and 365,650 bytes, then the first server cancellation
  reconciled and exported the attempt.
- The [recovery receipt](robot-recovery-qualification.json),
  [maintainer receipt](solo-maintainer-installation.json) and
  [v5 packet](solo-preview-qualification-v5.json) bind this composition. Original
  A14 remains deferred. The final Robot-successor archive/restore, maintainer
  review, release signing and signed-distribution verification remain open; no
  physical qualification follows.
