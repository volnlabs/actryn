# Remaining software acceptance inventory

## Current disposition

Follow-up audit through Server/Robot source `8d6e71d` and diagnostic fix `42537e2` supersedes the historical
NOT_RUN entries below where actual evidence now exists. It closes no whole
release row; the final source/configuration/binary cohort still needs an explicit
evidence map. See [progress](progress.md) for the individual results and failures.

| Rows | Actual evidence now available | Remaining boundary |
|---|---|---|
| A01/A03 | Manager guest08 lifecycle; installed manager11 lifecycle03 passes, including two reconciled natural completions under one grant and later durable terminal rows. Module16 covers stale/duplicate/replayed transport. Manager11's exact target recovery regression passes once. | Earlier installed run01 remains failed. Final source/artifact reconciliation remains. |
| A02/A09 | `robot-a02-replyloss-02` withholds the initial reply while durable cancellation/reconciliation succeeds. `robot-a09-contention-04` closes the allocation during a measured 611 ms SQLite exclusive lock, with zero STARTs. Both select manager10/module16. | Preserve separate evidence for absent/pre-send cancellation and commit races. SQLite contention is not fsync stall, EIO or media-power-loss proof. |
| A04/A05/A08 | Existing daemon-death/accounting, installed capacity, freeze/crash and pressure evidence remains separate. Diagnostic fix `42537e2` passes 5 Rust/28 Python checks and its corrected OCI reports the exact retained-capacity error. Closed-gate startup drains four retained streams with zero forwarded bytes. Four matched historical queries settle all four old debits while preserving OutcomeUnknown. After the new operation's cancellation, separate existing-handle cleanup passes one Recover and matching historical settlement. Final custody verifies 22 launcher/21 broker rows, 16 namespaces/21 Robot records, zero debits, 374 preserved entries, no tasks and inhibited disabled-zero output. Server cold-stop02 then passes with all three services inactive and full rows unchanged. | Finalize-run01 remains FAILED: identity checks passed in 29 ms, then recorder-inclusive guard exceeded 1.5 s at 3.736 s before the next result request. Its consumed abort remains unknown; never resend or replay an operation. Separate cleanup does not relabel that failure or manufacture task success. Recorder fsync versus scheduling cause is unresolved; uncommitted tails remain unknown. Final artifact reconciliation remains. |
| D2 isolation | Existing sandbox bindings verify configured cgroup/device limits; missing `/dev/mem` returns ENOENT. Separate owner05 restoration passes all 14 runtime/35 tool pins. Run04 preflight/build/import/start pass, but its campaign fails: existing unapproved `/dev/full`1:7 opens successfully in child8777, traced results3,-2,3, sequences1..177/lost0. Attempt958787b26f3546d03c6ca58736042d2c naturally exits105 and is reaped without Cancel; old full seven-table rows stay unchanged, Server23/22, zero debits/no Robot calls. Separate post-failure stop passes with all three Server services cold and custody unchanged. | No D2 PASS. Memory stage never begins and OOM counters remain0: OOM NOT_RUN. Source deny-all plus1:3/5/8/9 conflicts with observed1:7 success; upstream runc1.1.15 appended virtual defaults offer a strong source explanation, but exact Debian BPF827 is undumped. No generic escape/all-policy-off/physical-risk inference. Normal finish/capture04 NOT_RUN; launcher-owned fixed-filter correction selected, new qualification waits for its corrected cohort, no retry. |
| A06/A07/A15 | Module16 aggregate binds 16 actual ARM cases and 17 cases each in plain, lockdep, KASAN and KCSAN, including owner/leader exit and PID reuse. Current driver/header hashes match the aggregate. | Keep mocked-serdev byte-offset and PM/shutdown callback proof distinct from actual UART and platform suspend/poweroff behavior. Reconcile final artifacts without a blanket diagnostic rerun. |
| A10 | Traffic03 unchanged-capture reanalysis passes its corrected validator; prior lifecycle verifies gateway death, rotation and offline recovery. Lifetime09 passes retained-FD replacement, observed stale-binding no-effect checks, gateway-offline local recovery and export on installed manager11/module16. | Earlier failed campaigns remain failed. Lifetime09 preserves the uncertain negative reply; its old capture prefix does not cover that later request. Its zero SAMPLE records do not establish applied motion. Final cohort reconciliation remains. |
| A11 | Actual source omission records the 80→82 gap and durable fault. Hot-journal recovery retains only committed records plus the raw remnant and unknown tail. | Recorder overflow/media-loss boundaries remain explicit; metadata-only execution-replay ineligibility is intentional. |
| A12 | Fresh Server and Robot installer transitions/bootstrap pass. Server03 also passes installed execution/export/restart and BPF loading. Robot candidate04 update/resume/startup preserves all three slots and prior history; manager11 lifecycle03 passes with SDK/CLI export and retained crash history. | Final coherent artifact binding remains; disposable test signing is not release signing. |
| A13/A14 | Pinned live-policy/missing-credential checks and operator-executed installation recipes. | Authorized live-provider credentials and an independent developer are still external inputs. |
| A16 | `observer-installed-01` passes three readiness/death/loss cases and eight descriptive OFF/ON trials, preserving positive loss. Amendment7 source/native build/hash freeze pass. Excluded kernel pilot07 retains nine passed trials and one initial-handshake failure. Diagnostic8 case01 accepts one cold handshake; independent raw review verifies two loss-free events and the matched reply. | Pilot07 remains FAILED; production pilot qualification and the comparison remain open. Diagnostic8 is an instrumented non-reproduction, not a fix or explanation of the original failure. Its 3.266542 ms sampled interval is not whole-agent overhead or WCET. |

Work resumed at the user's request on 2026-10-17. Actual Server run06 compiled
the pressure inputs but stopped at artifact import: umask077 changed published
file modes. `ec2dfde` fixes file publication; `544c382` also fixes fresh registry
directory modes and rejects unsafe existing registries without changing them.
The focused tests and strict Clippy pass; the CLI/new unsigned bundle are built
and all 138 versioned imports match the captured target libraries. A separate
same-trust disposable test package passes actual installed inspect/stage/activate/
resume while preserving old slots/config/databases. The unapproved invalid slot
is quarantined by one guarded same-parent rename; its evidence and capacity
charge remain intact. One installed import of the same OCI under umask077 and
configuration validation as UID987 pass, preserving eight rows in each store.
Pressure setup run07 fails before instrumentation because text property output
omits an empty DeviceAllow array. `fabd894` preserves the typed array; 48 host
tests pass. Run08 ready checks pass, then setup rejects a pre-start timestamp
left by descriptor normalization after installing the shim. Its eight original
rows per store remain unchanged; no pressure attempt runs. The failed setup is
preserved; parser fix `f3953a0` passes 50 host checks. Run09 verifies the existing
instrumentation, then its pressure validator fails because it counts durable
rejection tombstones as approved reservations. Raw accounting confirms four
settled approved calls and four zero-reservation tombstones; four burst replies
remain uncertain. Its one attempt is cancelled once and reaped in both stores,
preserving all eight older rows. Run09 remains FAILED; allocation/reclaim phases
were not run. Correction `6eac6ab` passes 55 host tests. Run10 passes its active
call-pressure check, then unexpectedly accepts the preparation intended to fail
with ENOSPC. Actual namespace/mapping/relocation evidence shows the test library
on a `noexec` mount never intercepted directory calls; the earlier setup check
was insufficient. Both new attempts are now reaped, with eleven histories per
store and zero outstanding work. Run10 remains FAILED. Fixture fix `343572e`
uses protected executable storage and exact executable-mapping checks; 58 host
tests pass. Separate failed-run finalization verifies both exports, restores
original properties, stops the services and captures all eleven histories and
both failed campaigns. The 91-file archive is independently hash-checked;
run10 remains FAILED. Corrected run11 passes approved-call pressure, one ENOSPC
allocation failure and EBUSY retirement pressure with active-work preservation
and autonomous cleanup. Its verified 213-file capture preserves all older rows,
fifteen launcher/fourteen broker histories and zero outstanding work; original
properties are restored and the VM is powered off. This instrumented result
does not close all A08. The outstanding-debit/guest-restart campaign remains.
A16 diagnostic8 native build01 and actual cold case01 pass. Its one RECOVER
receives a matching ACK with no lost events; raw capture and teardown are
verified. Both diagnostic VM and fixture are stopped. This non-reproduction
does not repair or relabel pilot07, which remains FAILED; production pilot
qualification and the required comparison remain open. The real unsigned
candidate is still unqualified.
The remaining target queue includes outstanding-debit/crash/pressure and the amended
authority comparison, followed by final artifact, provenance and evidence mapping.
The corrected ARM universal CLI is built, with all 28 allocated sections
preserved after stripping; all 136 versioned requirements match four libraries
collected from the exact installed Robot. Its packaged Describe and Recover
paths now execute during the reviewed update; full CLI acceptance remains open.
Earlier Server/Robot cold readbacks preserve all 17/16 Server rows and
11/18 Robot histories. The supported fresh test enrollment and pinned pairing
passed after old certificates expired, preserving all old generations and
revocations. Retained-debit campaign01 remains FAILED after its readiness cutoff;
both charges remain. Reconciliation replacements are built and reviewed; Server
is installed; all three services were active at the recorded lifetimes before the later intentional stop below.
Robot activation and the separate read-only
existing-service verification pass, preserving all old history; the failed
freshness and capability-parser phases remain recorded. The module is unchanged.
Retained-debit continuation-run02 passes startup/drain and both-sentinel readiness,
then fails a checker before any new preparation; it remains FAILED. The checker
fix passes offline reanalysis without repeating the export. Subsequent residual01
performs two pressure operations and the failed fifth attempt; fresh read-only
inspection verifies20/19 Server rows,14/20 Robot history and four charges. Its
distinct abort Revoke is consumed. Fix `42537e2` restores the missing agent diagnostic
with bounded reasons; the old failure remains FAILED. The corrected OCI import/startup and exactly two new preparations are now
recorded below; no further preparation or proposal may be added to this campaign. The separately reviewed Robot-only guard/recorder/SDK
sample passes in 0.118052 seconds, with known cleanup and no preparation; this
does not close campaign acceptance. Release signing, live credentials and independent
installation remain separate external gates. No software result qualifies motion.

Diagnostic source `42537e2` has one successful static build/OCI assembly and
independent root payload checks. Public staging, one additive import and the
subsequent closed-gate startup pass, preserving all older registry entries and
four then-outstanding charges under capacity 8. The new capacity diagnostic and
four historical settlements pass. Finalize-run01 then fails the local recorder
cutoff during the restored operation's cancellation checks; the following result
request was never sent. Read-only inspection verifies the terminal, retired/ready
operation, one remaining debit and zero output. All failed runs remain FAILED.
The custody checker also had an independent historical transport-flag error:
existing Server code and regression coverage intentionally retain
`remote_unavailable=true` with a positive historical settlement. Numbered
custody-plan02 corrects only that check; its meaningful RED and 23 passing host
checks preserve all exact durable identity, raw-record and reconciliation proof
requirements. This is not a production change or a final campaign pass.
Separate cleanup now passes with one explicit Recover, matching existing-handle
settlement and one new settled export; the four prior exports are copied
byte-identically. All 21 raw Robot operation rows and 374 preservation entries
remain unchanged, with Server 22/21, Robot 16/21 and zero debits. Original
OutcomeUnknown verdicts and the original finalization FAILED are preserved.
The accepted saved review is
`artifacts/robot-retained-debit-finalize-cleanup-actual-review01/review.json`.
Server cold-stop02 then passes once with all three services inactive/PID0,
full rows and peer/key/drop-in preserved, and unchanged Robot/carrier lifetimes:
`artifacts/server-diagnosis-cold02/result.json`.

D2 plan03 source staging passes, but preflight stops before baseline save,
compiler invocation, import or new attempt. Saved unattended-update evidence
identifies `libexpat1` `2.8.3-1~deb13u1`→`2.9.0-1~deb13u1` and `linux-libc-dev`
`6.12.111-1`→`6.12.113-1` as the two frozen-pin mismatches. Narrow controlled
APT restoration subsequently passes under separate owner05; no D2 PASS is claimed. Newer
image/meta 113 remain installed, while the running kernel is
`6.12.111+deb13-amd64`. This later package transaction does not explain the
earlier recorder cutoff or erase the observed cleanup/custody; those observations
are not complete proof of the original package cohort throughout the later
interval. Evidence: `artifacts/server-diagnosis-root-run03/{stage-sources,preflight}`
and `artifacts/server-diagnosis-package-drift-review02/review.json`.
Owner05 restores exactly Expat to `2.8.3-1~deb13u1` and `linux-libc-dev` to
`6.12.111-1`, with the same 364 package names and all 14 runtime/35 tool pins
matching. Image111 and image/meta113 are retained in the same running111 boot.
All three services stay cold; Server 22/21, Robot 16/21, zero debits, all 374
preservation entries and raw DB/sidecar bytes remain unchanged. No compile or
new agent runs. Mask03 and stop04 each succeeded once; owner05 read-only
quiescence adopts that known state, retaining four transient APT masks and the
failed/non-active timer diagnostic states, without repeat/reset. Earlier checker
failures stay FAILED; restoration05 remains PASS independently of the later D2
failure. Receipts:
`artifacts/server-qualification-package-restore-owner05/{actual-review.json,restore/result.json}`.

D2 run04 then passes preflight/build/import/start, but its one campaign fails
attempt `958787b26f3546d03c6ca58736042d2c`. Child8777's ordered kernel openat
results3,-2,3 show the unapproved existing `/dev/full` character1:7 opening
successfully. The parent exits naturally105 and both stores reap it, with no
Cancel. Retained observer sequence1..177 has zero loss. Initial/final OOM
counters remain0 and no `memory_begin` occurs: OOM is NOT_RUN. All old full
seven-table rows are unchanged; current Server23/22, zero debits, no new calls
or Robot rows. Requested source policy denies all then permits only1:3/5/8/9;
upstream runc1.1.15 appends virtual-device defaults, a strong source explanation,
but the exact compiled Debian BPF program827 was not dumped. This does not
establish generic sandbox escape, all policy disabled, physical risk or D2 PASS.
Normal04 finish/capture is NOT_RUN; the separate controlled stop now passes.
The selected fix adds a launcher-owned fixed device filter before Prepared and
verifies its identity before Start; a new qualification requires the corrected
cohort. No new attempt/replay occurs here. Saved capture and 26-check independent review:
`artifacts/server-diagnosis-failure-inspection01/capture-once.stdout` and
`artifacts/server-diagnosis-failure-review01/review.json`.
The post-failure stop preserves all 374 entries and full seven-table rows,
Server23/22, Robot16/21 and zero debits. Three Server services are cold, with no
tasks/shims/cgroups/broker directories, unchanged Robot raw/history and the same
carriers. Run04 remains FAILED and OOM NOT_RUN; there is no new attempt or retry.
Receipt: `artifacts/server-d2-failure-stop01/result.json`.

Robot's separate read-only inspection matches nine of ten runtime pins; Expat
2.9.0 remains UNRESTORED against pinned 2.8.3, with running kernel111, zero
package actions and zero RPCs. This limits exact installed-Robot package cohort
equality; it does not establish drift in the separate A16 disk. Receipt:
`artifacts/robot-qualification-package-inspection01/capture.json`.
Raw captures stay local and the pushed source is not their backup.

## Historical audit

Read-only audit on 2026-10-16, against the [approved A01–A16 matrix](../superpowers/plans/2026-10-16-actryn-v0.0.1.md#acceptance-matrix),
[progress ledger](progress.md), tracked harnesses and retained component results.
Source baseline: `ec3a1fe`. This inventory closes no acceptance row and changes no
contract, limit or release scope. A missing integrated campaign is distinguished
from an implementation defect and from existing component proof.

The scheduled source-omission, fresh-installation, live-model and A16 comparison
campaigns do not, by themselves, cover the following cases.

| Priority / rows | Remaining case and evidence boundary | Reuse |
|---|---|---|
| 1 — A02/A09 | Cancel the allocated key while the first proposal reply is withheld; separately close an allocated identity while the actual manager's SQLite writer cannot persist. Guest08 proves absent/pre-send cancellation, not these cases. Registry tests cover allocation/commit races and real SQLite contention with a mocked authority. | `apps/robotd/tests/guest.py`; `crates/robot-intent/src/tests.rs` tests `allocated_cancel_does_not_wait_for_blocked_storage_before_id_reply`, `cancel_between_durable_commit_and_final_check_prevents_dispatch`, `sqlite_exclusive_writer_lock_cannot_block_urgent_allocated_cancel`. A bounded relay and external SQLite lock can exercise the production interfaces without injection APIs. |
| 1 — A05/A08 | Approved-call pressure, prepared/retiring exhaustion while work remains active, and cancellation/restart with an actual unresolved downstream debit. The packaged-service campaign kills daemons after its offline broker call has settled; its unknown **attempt outcome** is not proof of an outstanding external reservation. Allocation/reclaim failure under active preparation also lacks an identified campaign. | `apps/server/tests/{guest_services.py,accounting.rs,robot_accounting.rs}`, `packaging/agent/guest_robot_acceptance.py`; existing finite-budget, terminal-durability and closure-worker tests provide expected behavior. |
| 1 — A04 | Abrupt server/Robot guest interruption with unfinished identities and accounting, followed by read-only inspection after boot without resend. Daemon SIGKILL and controller restart are separate lifetime cases. | Manager-crash phase in `apps/robotd/tests/guest.py`, server service-crash harness, and root-owned disposable VM control. Retain the original disk, handle and provenance. |
| 1 — A10 | Actual forged/replayed/flooded relay traffic, connection/observation saturation and retained relay descriptors across process replacement. Guest08 proves gateway death, offline local revoke and identity rotation; it does not exercise a malicious relay. | Existing manager/gateway fixed control and relay sockets, mTLS/canonical-frame tests, and guest lifecycle helper. No dedicated actual malicious-gateway harness was found. |
| 1 — A12 | Successful bootstrap/resume and installed-slot service startup, then an offline execution/export/restart. The fresh-install harness explicitly finishes inhibited and reports `services_started=false`, `module_loaded=false`, `successful_startup_tested=false`. Its update/rollback pass therefore does not establish installed runtime startup. | `packaging/release/tests/guest.py` and shipped `INSTALL.md`, followed by existing service/combined harness assertions adapted to the installed paths. Manual binary copies are not package-path proof. |
| 2 — D2/A16 | Server diagnostic overhead and loss under a stated workload; actual reader loss/readiness failure before start and while an attempt runs. The A16 authority-placement comparison includes optional UART tracing and explicitly excludes Robot/TLS/runtime costs. It does not measure server BPF overhead. Observer tests establish attribution/retention/loss; server readiness tests are component tests. | `tests/observer/guest.py`, `apps/server/tests/{observer.rs,guest_launcher.py,guest_services.py}`, retained delayed-retirement experiment. Preserve resource pressure, OS access failure and attributed broker denial as different facts. |

The next A02/A09 batch is deliberately narrower than the whole rows: one
end-to-end encrypted reply-loss case and one actual SQLite writer-contention
case. A SQLite lock is not an injected fsync stall or EIO. Uncertain replies,
independent clock/recorder faults, missing durable capture and failed cleanup
remain failures. The two-second recorder and ten-second clock limits stay fixed.

## Existing coverage and final-artifact reconciliation

| Rows | Existing evidence / remaining boundary |
|---|---|
| A01/A03 | Actual manager guest08 completes two natural operations under one grant; kernel selftests and adversarial delayed-handoff/late-receipt cases cover stale work and handoff. The combined offline run02 is one operation. Retain these distinct claims and map them to the selected final binaries; do not infer a combined two-operation test. |
| A06/A07/A15 | Snapshot15 has sixteen cases in each of plain, lockdep, KASAN and KCSAN, including actual production functions with injected serdev, every encoded partial-write offset, retained RX prefixes, queue/counter bounds, PM callbacks and concurrent closure. The full actual ARM twelve-case pass is snapshot13; snapshot14's wider campaign is incomplete; snapshot15's actual check covers selftest and Ready recovery. Reuse `kernel/tests/run_guest_campaign.py` for the final module's required transport/lifetime cases. No explicit multithread leader-exit/PID-reuse campaign was found. Platform suspend/resume is not established by callback tests; review this evidence boundary against the supported target before claiming coverage. This is not a request to repeat diagnostic builds merely because the ledger is incomplete. |
| A11 | Host tests retain typed source faults, distinguish external source identities from recorder ordinals, reserve fault metadata and reject replay without a complete input prefix. The scheduled one-event omission tests actual durable fault recording. It does not cover FIFO overflow or arbitrary-media power loss. The preview's metadata-only capture is intentionally execution-replay-ineligible. |
| A12 | Isolated installer tests cover multiple interruption boundaries; the real fresh-install fixture targets a durable pointer interruption and explicit recovery/rollback, using a disposable signing key. Neither establishes publication signing or startup. |
| A13/A14/A16 | Real hosted-model acceptance, independent human installation and the frozen competent-userspace comparison remain separately pending. Their scheduled execution cannot substitute for the failure cases above. |

Concrete retained results inspected include `artifacts/robotd-guest08.log`,
`artifacts/server-services-guest05.log`,
`artifacts/server-services-guest05-unknown.log`,
`artifacts/combined-offline-guest02/result.json`, and the hash-pinned campaign
records described in [kernel diagnostics](../../kernel/DIAGNOSTICS.md) and
[actual adversarial tests](../../kernel/tests/ADVERSARIAL.md). Earlier failures
remain retained. This audit ran no build, VM, hardware or acceptance command.

Final closure still needs an explicit A01–A16 evidence map against coherent
source/configuration/binary hashes, required external release inputs, and the
selected final-artifact checks. No software result qualifies physical actuation.
