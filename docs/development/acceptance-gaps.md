# Remaining software acceptance inventory

## Current disposition

Follow-up audit through integration source `1a2e9c5` supersedes the historical
NOT_RUN entries below where actual evidence now exists. It closes no whole
release row; the final source/configuration/binary cohort still needs an explicit
evidence map. See [progress](progress.md) for the individual results and failures.

| Rows | Actual evidence now available | Remaining boundary |
|---|---|---|
| A01/A03 | Manager guest08 lifecycle; installed Robot run01 also retains two reconciled natural completions under one grant. Module16 covers stale/duplicate/replayed transport. Manager11's exact target recovery regression passes once. | Installed run01 as a whole remains failed. The full installed lifecycle with manager11 remains pending. |
| A02/A09 | `robot-a02-replyloss-02` withholds the initial reply while durable cancellation/reconciliation succeeds. `robot-a09-contention-04` closes the allocation during a measured 611 ms SQLite exclusive lock, with zero STARTs. Both select manager10/module16. | Preserve separate evidence for absent/pre-send cancellation and commit races. SQLite contention is not fsync stall, EIO or media-power-loss proof. |
| A04/A05/A08 | Existing daemon-death/accounting tests and one settled combined Robot debit; installed Server capacity01 preserves active work during exhaustion. | Actual outstanding-debit cancellation, Server guest crash/restart and debit pressure remain pending. A Robot guest crash with a durable unfinished operation is also missing: retained traffic02 had already completed, and lifetime02 had no operation record. |
| A06/A07/A15 | Module16 aggregate binds 16 actual ARM cases and 17 cases each in plain, lockdep, KASAN and KCSAN, including owner/leader exit and PID reuse. Current driver/header hashes match the aggregate. | Keep mocked-serdev byte-offset and PM/shutdown callback proof distinct from actual UART and platform suspend/poweroff behavior. Reconcile final artifacts without a blanket diagnostic rerun. |
| A10 | Traffic03 unchanged-capture reanalysis passes its corrected validator; prior lifecycle verifies gateway death, rotation and offline recovery. | Original traffic03 campaign remains failed with separate reanalysis. Lifetime05 fails with PendingAge before any gateway signal; replacement while old descriptors remain held is still incomplete. |
| A11 | Actual source omission records the 80→82 gap and durable fault. Hot-journal recovery retains only committed records plus the raw remnant and unknown tail. | Recorder overflow/media-loss boundaries remain explicit; metadata-only execution-replay ineligibility is intentional. |
| A12 | Fresh Server and Robot installer transitions/bootstrap pass. Server03 also passes installed execution/export/restart and BPF loading. Robot candidate04 update/resume/startup preserves all three slots and prior history. | Corrected Robot lifecycle and final coherent artifact binding remain; disposable test signing is not release signing. |
| A13/A14 | Pinned live-policy/missing-credential checks and operator-executed installation recipes. | Authorized live-provider credentials and an independent developer are still external inputs. |
| A16 | `observer-installed-01` passes three readiness/death/loss cases and eight descriptive OFF/ON trials, preserving positive loss. Amendment7 source checks and independent review pass. | Kernel/userspace comparison remains incomplete after the failed instrumentation pilot; amendment7 target build/freeze and both new pilots remain pending. Standalone diagnostic timing is not whole-agent overhead or WCET. |

The current target queue is the corrected Robot update/lifecycle, full retained-FD
gateway case, outstanding-debit/crash/pressure case, unfinished Robot guest crash,
and amended authority comparison. Release signing, live credentials and independent
installation remain separate external gates. No software result qualifies motion.

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
