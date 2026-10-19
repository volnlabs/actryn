# Remaining software acceptance inventory

## Current disposition

The tracked [incomplete qualification packet](final-qualification.json) now
binds the selected candidates and case references. It lists remaining
source/cohort associations, A16 failure and external inputs without closing rows.

Follow-up audit through Server/Robot source `8d6e71d`, launcher correction `2e93ccd`
(build source `14afd962`) and diagnostic fix `42537e2` supersedes the historical
NOT_RUN entries below where actual evidence now exists. It closes no whole
release row; the final source/configuration/binary cohort still needs an explicit
evidence map. See [progress](progress.md) for the individual results and failures.
The additive [release cohort map](release-cohort.md) binds selected mixed-origin
artifacts to case evidence and identifies source-impact and CLI coverage boundaries.
Unsigned Robot candidate `da6b6862…cc5a9` is selected after actual host assembly
and independent 17-entry review; installed d77 and qualification are unchanged.
The map closes no acceptance row.
Push26 records preceding integration checkpoint `117cc93`,
with zero CI runs; it supplies no CI pass or backup of ignored raw evidence.
The existing device/OOM composite passes the existing-device-denial and cgroup-OOM cases
only; whole D2 remains open for final cohort reconciliation.
Post-run05 shutdown now preserves all histories/accounting and leaves both VMs
and the fixture off, with stopped public-byte custody recorded in
`artifacts/reconciliation-post-run05-stopped-custody01/closed.json`. The fixture's
safe Faulted transport-loss state is retained; its rejected first stop precheck
sent no Stop. This cleanup closes no additional acceptance row.

A16's frozen comparison is complete and FAILED: all 80 trials began and ended,
79 pass and B3 evidence trial 6 fails during BIND before RECOVER/eligibility.
Exact role/errno and underlying cause remain unobserved. B1/B2/B4 pass 20/20;
B3 evidence 9/10 and trace 10/10 remain separate. The exact 19-receipt plan02
known-cleanup exception admits only block4 and does not rerun or relabel B3.
Both passing pilots retain their separately excluded 20-trial denominator.
All six original-K11 catalog/provider/artifact pairs and four 78/78 diagnostic
trace correlations pass with zero recorded loss; those facts do not qualify
the failed workload. The [actual comparison report](a16-comparison.md) contains
the eight rows, metric/dispatch CSVs, known cleanup and exact receipts, including
independent final audit `4257e045…ef0865`. No pooling, significance, superiority,
equal-work inference from B3's failed run, physical measurement or WCET claim follows.
Historical pilot07 and boot09/10 failures stay unchanged.

A separately numbered diagnostic9 now has an actual native guest GCC14.2.0
build (ELF045d9bcd…a612, 74704 bytes) and known normal shutdown/46-unit stopped
custody. The null controller backend starts no fixture, gateway, module or
workload; both fixture journals and the other eight public records are unchanged.
At that build checkpoint, diagnostic execution was NOT_RUN; A16 remains FAILED79/80.
The later [boot01 mode-guard failure and cleanup](release-cohort.md#diagnostic9-boot01-mode-guard-and-cleanup)
preserve that boundary: actual ELF bytes match, but mode0700 differs from the
guard's assumed0755. No workload was dispatched. Normal cleanup and that checkpoint's
69-unit stopped custody pass, with fixture boot145 and zero diagnostic appends.
Separately numbered [observation02](release-cohort.md#diagnostic9-observation02-ten-trials)
now passes all ten diagnostic trials with no BIND failure. It preserves the
original limits and cohort, then completes normal cleanup and74-unit stopped
custody. No historical role/errno/cause is recovered; original FAILED79/80
acceptance remains unresolved, and these ten trials are not pooled with it.
Under the original baseline, D2-01/02 source association exposes literal
pre-Create ordering and pre-Start cleanup gaps: runtime Create gates application
entry, but broker socket/live filter binding is later, and old observer/socket
failures leave prepared resources charged until expiry. The user now approves the ordering
clarification, integrated exactly as `025e36e`; the original snapshot remains.
The private-clone missing-broker regression has actual old-binary RED/known cleanup
and normal shutdown, with 51-unit stopped custody and unchanged original records.
The isolated cleanup fix passes 66 Server package tests and one host build/static
check (ELF3ead4e49…afe30). Separately numbered GREEN04 now passes missing-broker
cleanup, observer-unreachable retirement/recovery, healthy/duplicate Start and
capacity preservation. Its cold33/24 stores preserve every old row/log and have
zero Robot debit. Normal poweroff and that checkpoint's 59-unit stopped custody preserve
all original public records, key metadata, fixtures and original26/24Server,
16/21Robot/all374. Earlier setup/fixture/read-only failures stay failed; exact
reconciliation and two consumed same-inode stale-socket unlinks precede the new
execution, without database/ownership/retained-artifact/capacity changes.
The fix and test corrections are integrated as `e6120d3`/`71696f2`/`ecc5a8b`.
The later namespace verifier raises the maintained Server Python suite to 96 passing
checks. Final unsigned Server9f749ca3 is assembled and independently byte-reviewed;
whole-cohort qualification remains open and installed f32 is unchanged.
[Current approval and regression receipts](release-cohort.md#approved-ordering-and-actual-pre-start-regression)
close no whole acceptance row.
[Exact build and source evidence](release-cohort.md#diagnostic9-build-only-and-current-source-gaps)
closes neither whole D2 nor the failed comparison.

D2 now also has one source-bound native attempt on exact kernel111/TEST f32.
Unchanged validators independently accept ten syscall denials, five Broker cases
and 196 trace records with zero loss. The original runner remains FAILED because
it substitutes Launcher Cancel's empty delegated accounting for Broker Status.
A separate status read supplies the actual Broker inspection; both raw replies
and independent deadlines remain unchanged. No operation is retried. Cleanup,
exact three-file Restart restoration, normal poweroff and final custody02 pass:
26/24 Server, 16/21 Robot, zero debits/all 374 preserved, all 42 host units cold.
One additive import leaves six charged trees/five approvals at capacity eight;
current Server configuration hash is cd9a365f…93d03. The maintained regression
passes 83 host tests; the separately numbered harness amendment has six passing
host checks and no target execution. [Native evidence and limits](release-cohort.md#server111-native-sandbox-and-broker-evidence)
replace the earlier missing per-case native records only; they do not close whole
D2 or transfer unsupported network, physical or policy-origin claims. The additive
[17-predicate association](../../artifacts/server-final-d2-predicate-map03/association.json)
and separate composition decision accept preview case coverage while retaining
the historical literal D2-05 gap in frozen map03. The new
[namespace association](release-cohort.md#created-task-network-namespace-proof)
supplies scoped preview network coverage through a separate trusted ENETUNREACH
probe, composed with agent socket-denial/no-inherited-socket evidence. The agent
itself does not issue an external connect. Final-cohort review remains open; the
exact single multimodal-batch story is NOT_RUN.

The preceding D2 capability-denial window binds boot `62353823-df1e-4515-a744-3d767565835e`,
kernel `6.12.111+deb13-amd64` and unchanged TEST f32. The wrong pre-Stop raw
baseline leaves cold prerequisite01 FAILED; saved amendment `44fc914b…05f9`
proves exact prior cold/poweroff bytes without a collection retry. First cold
integrity checks all 27 payload files, five registry trees and four providers.
One Prepare (`aa4055e973266e3b6fda034d3597b2ea`) reports fixed-policy load EPERM,
but the original owner stays FAILED because its two-key predicate rejects the
actual six-field `server_error` reply; `outcome_unknown=true` stays intact.
Durable readback and 157 contiguous trace records with no loss, exec or output
resolve only the current cleanup state. Separate cleanup stops the original
three services once, restores four policy files exactly, and preserves old
rows/logs/Broker plus all 374 entries at 25/23 Server, 16/21 Robot and zero debits.
Normal poweroff and final stopped custody then pass: all 35 host units inactive
with empty cgroups and NRestarts0, no repository actors, QSD/FUSE mounts, image
holders or selected listeners; other eight public records and three
metadata-only keys unchanged. [Exact receipts](release-cohort.md#server111-capability-denial-cleanup-evidence)
preserve the original failures and unknown reply; no Prepare/operation is replayed.
Prior extraction failures remain preserved. Whole D2/final-cohort mapping stay open.
No independent installer or release signing identity is confirmed. The hosted-model
credential was provisioned only through the documented Server `LoadCredential`
route in a disposable overlay. The frozen two-call A13 campaign has now been
consumed: standalone passed, while the combined call settled 33 tokens and then
failed closed because its original one-second observation expired during
inference. No operation was allocated; later Robot clock warnings are separate
post-failure facts, and local recovery preserved the uncertain debit. Raw evidence
is local, ignored material rather than a Git backup.

| Rows | Actual evidence now available | Remaining boundary |
|---|---|---|
| A01/A03 | Manager guest08 lifecycle; installed manager11 lifecycle03 passes, including two reconciled natural completions under one grant and later durable terminal rows. Module16 covers stale/duplicate/replayed transport. Manager11's exact target recovery regression passes once. | Earlier installed run01 remains failed. Final source/artifact reconciliation remains. |
| A02/A09 | `robot-a02-replyloss-02` withholds the initial reply while durable cancellation/reconciliation succeeds. `robot-a09-contention-04` closes the allocation during a measured 611 ms SQLite exclusive lock, with zero STARTs. Both select manager10/module16. | Preserve separate evidence for absent/pre-send cancellation and commit races. SQLite contention is not fsync stall, EIO or media-power-loss proof. |
| A04/A05/A08 | Existing daemon-death/accounting, installed capacity, freeze/crash and pressure evidence remains separate. Diagnostic fix `42537e2` passes 5 Rust/28 Python checks and its corrected OCI reports the exact retained-capacity error. Closed-gate startup drains four retained streams with zero forwarded bytes. Four matched historical queries settle all four old debits while preserving OutcomeUnknown. After the new operation's cancellation, separate existing-handle cleanup passes one Recover and matching historical settlement. Final custody verifies 22 launcher/21 broker rows, 16 namespaces/21 Robot records, zero debits, 374 preserved entries, no tasks and inhibited disabled-zero output. Server cold-stop02 then passes with all three services inactive and full rows unchanged. | Finalize-run01 remains FAILED: identity checks passed in 29 ms, then recorder-inclusive guard exceeded 1.5 s at 3.736 s before the next result request. Its consumed abort remains unknown; never resend or replay an operation. Separate cleanup does not relabel that failure or manufacture task success. Recorder fsync versus scheduling cause is unresolved; uncommitted tails remain unknown. Final artifact reconciliation remains. |
| D2 isolation | Run04's 1:7 success and absent OOM remain FAILED. Corrected TEST cohort f32/launcher17a0 installs after fresh four-provider checks; startup02 passes. Run05 staging/preflight pass; independent 32-check saved review verifies open results 3,-2,-1, 177 complete records/loss0, max18/oom1/oom_kill1 and natural137. Its checker overcounts five pre-exec TGID thread exits despite actual leader exit177. Fix `66f559b` passes 12 diagnosis/72 Server Python tests and corrected maintained offline export/trace/device/OOM/full-old-row checks. Separate custody identifies one reaped attempt1f5cfda02c51a3b354e46d27e75924e6; known stop passes, Server24/23, Robot16/21, zero debits, all374/old rows retained and three Server services cold. | Run05 campaign remains FAILED and its owner's null attempt count is preserved. Normal capture05 NOT_RUN; no whole D2 PASS. Path attribution combines the fixed probe/node/control with trace results; it is not an explicit policy-origin event. Disposable TEST signing is not release qualification. No physical or generic sandbox claim follows. |
| A06/A07/A15 | Module16 aggregate binds 16 actual ARM cases and 17 cases each in plain, lockdep, KASAN and KCSAN, including owner/leader exit and PID reuse. Current driver/header hashes match the aggregate. | Keep mocked-serdev byte-offset and PM/shutdown callback proof distinct from actual UART and platform suspend/poweroff behavior. Reconcile final artifacts without a blanket diagnostic rerun. |
| A10 | Traffic03 unchanged-capture reanalysis passes its corrected validator; prior lifecycle verifies gateway death, rotation and offline recovery. Lifetime09 passes retained-FD replacement, observed stale-binding no-effect checks, gateway-offline local recovery and export on installed manager11/module16. | Earlier failed campaigns remain failed. Lifetime09 preserves the uncertain negative reply; its old capture prefix does not cover that later request. Its zero SAMPLE records do not establish applied motion. Final cohort reconciliation remains. |
| A11 | Actual source omission records the 80→82 gap and durable fault. Hot-journal recovery retains only committed records plus the raw remnant and unknown tail. | Recorder overflow/media-loss boundaries remain explicit; metadata-only execution-replay ineligibility is intentional. |
| A12 | Fresh Server and Robot installer transitions/bootstrap pass. Server03 also passes installed execution/export/restart and BPF loading. Robot candidate04 update/resume/startup preserves all three slots and prior history; manager11 lifecycle03 passes with SDK/CLI export and retained crash history. | Final coherent artifact binding remains; disposable test signing is not release signing. |
| A13/A14 | Pinned live-policy/missing-credential checks, one standalone live PASS, and one combined live FAIL with 33 settled tokens, an expired original observation and zero allocated operation, plus explicit recovery and stopped custody. | A13 needs qualification of the reviewed execution-observation revalidation and a renewed call budget; the failed call must not be replayed. An independent developer remains unavailable and A14 stays deferred. |
| A16 | [Completed frozen comparison](a16-comparison.md): 80 begun/ended, 79 PASS/1 FAILED; B1/B2/B4 each 20/20, B3 evidence 9/10 and trace 10/10. Six original-K11 cohort pairs, four 78/78 trace correlations, independent final audit and known stopped custody pass. Both pilots remain excluded. | Comparison acceptance stays FAILED on B3 trial 6 BIND abort; role/errno/cause unobserved. No retry or failure exclusion. Historical pilot07/boot09/10 failures and diagnostic8 boundaries remain. No equal-work, superiority, physical or WCET inference. |

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
Source correction `2e93ccd` (immutable build source `14afd962…2dca9`) completes
the independently authored Apache-2.0 four-device filter, owned ID/direct/effective
MULTI proof checks and launcher `CAP_BPF`. Host results are 66 Rust, 69 Server
Python, 25 release Python and 13 agent self-tests, Clippy/format PASS, connected
review without material findings. These are not corrected kernel/guest evidence.
Launcher-only build/static checks now pass: binary `17a0d392…96b24`, all 31
allocated sections preserved and 154 historical target imports matched. Fresh
target-provider verification remains required before preserved cold TEST installation,
then a new numbered D2 attempt reusing approved OCI `55967ce1…10d00`/agent `2ac58…`
and the original1:7 probe; no repeated agent compile/import. Receipts:
`artifacts/server-device-policy-root-tests01/verification.json`,
`artifacts/server-device-policy-helper-tests01/receipt.json` and
`artifacts/server-device-policy-validator-tests01/verification.json`.
Build receipt: `artifacts/server-device-policy-build01/provenance.json`.

Latest follow-up: fresh four-provider verification and a same-filesystem
no-replace archive of `0f2ea983…f4bc` precede cold installation of TEST manifest
`f32f1c85ff58095034d7b82f80e59454fac826b83760f7013a585a27025c54ad`, launcher
`17a0d392…96b24`. Four historical slots are retained, five total/three managed;
current f32 supersedes historical b119. Actual qualification remains false despite
disposable test signing. Startup01 fails before Start on `Restart=on-failure`,
preserving raw history; three runtime-only `Restart=no` drop-ins and startup02
then pass. Run05's campaign is still FAILED on its TGID thread-exit overcount,
although independent 32-check review verifies the actual leader exit 177 and
positive device/OOM observations. Validator fix `66f559b` (source `5dea0f4`) passes
12 diagnosis/72 Server Python tests and corrected maintained offline
export/trace/device/OOM/full-old-row reanalysis. Normal capture05 is NOT_RUN;
this does not close the whole D2 gate. Separate custody and known-stop receipts
prove counts 24/23/16/21/0, full old rows/logs/374 entries, unchanged credentials
metadata/Robot raw/history, cold Server services and empty owned scopes. No
automatic retry, new export or whole-gate PASS follows. Evidence:
`artifacts/server-device-policy-{cold-inspection01,archive-owner01,install-owner01}/result.json`,
`artifacts/server-device-policy-testvariant01/result.json`,
`artifacts/server-device-policy-startup-{inspection01,owner02}/result.json`,
`artifacts/server-diagnosis-failure-review02/review.json`,
`artifacts/server-diagnosis-thread-exits-regression01/{review.json,offline.stdout}`,
`artifacts/server-device-policy-d2-owner02/campaign/result.json`,
`artifacts/server-device-policy-d2-failure-custody01/result.json` and
`artifacts/server-device-policy-failure-stop-owner01/result.json`.

Actual cold-integrity01 then passes all 27 payload files, public configuration/
policy, typed DeviceAllow, unit text, persistent-library/no-interposition checks
and all five registry trees. Full 24/23 rows, Robot/374 custody and cold raw
bookends remain equal; both owner scopes are empty. The hash-bound composite
certificate passes **two concrete cases only**: existing char1:7 denial with
allowed/absent controls, and fresh 256MiB cgroup OOM with natural SIGKILL
retirement. Run05 remains FAILED and normal capture05 NOT_RUN. The whole D2 gate
is `OPEN_FINAL_COHORT_RECONCILIATION_REQUIRED`; release/physical qualification is
not established. Receipts:
`artifacts/server-device-policy-cold-integrity-owner01/result.json` and
`artifacts/server-device-policy-composite-cases01/result.json`.

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
