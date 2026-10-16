# A04 frozen QEMU, crash and retained history

**Actual campaign01 passes on installed manager11/module16.** Its freeze, retained
disk reboot and inspection evidence is recorded in the
[progress ledger](../../../docs/development/progress.md#installed-manager11-and-numbered-follow-up-campaigns).
The raw tail remains unknown; this does not close the whole A04 release row.
This opt-in test has two separate
invocations. It uses the existing installed Robot, software fixture, SDK proposal,
canonical local RPC, SSH master, CLI pairing/export and production evidence reader.
It launches no VM, installs nothing and creates no enrollment or replacement
identity. The parent owns exclusive guest scheduling and the same-disk restart.
No physical actuator or provider credential is involved.

The sequence is explicitly **SIGSTOP, external fixture closure observation,
SIGKILL, new boot, retained-history inspection**. It is not an instantaneous
powercut. The native fixture stays alive outside the paused guest. A direct QEMU
kill would close the Unix connection and exercise `transport_lost`; keeping the
stopped process and its socket descriptors alive permits independent clock polling.

## Reviewed inputs and preflight

Use a new protected local plan JSON. Root supplies the actual current pins after
the candidate04/update/recovery campaign, before any lifecycle identity rotation.
Historical manager10 or stale boot inputs are never substituted automatically.
The JSON is at most 128 KiB and contains:

- `allow_disposable_guest: true`, exact `machine_id`, original actual `boot_id`,
  installed `manifest_sha256`, retained `identity_generation`, and full host
  `cli_sha256` / `reader_sha256`.
- `rpc`: exactly the existing fields `ssh_port`, `tcp_port`, `cli`, `reader`,
  `ssh_key`, `known_hosts`, `ca`, `cert`, `key`, `principal`, `dns`, `pin`,
  `manager_sha256`, `gateway_sha256`, `module_note_sha256`. Paths are absolute;
  existing private keys are used through their normal authentication route and
  are never copied into diagnostics. Pins are full lowercase SHA256 values.
- `qemu`: exact `unit`, `pid`, `/proc/PID/stat` `start_ticks`, `invocation_id`,
  `exe_sha256` and complete process `argv`. Only an owned
  `actryn-install-robot-vmN.service` or
  `actryn-install-robot-manager11-vmN.service`, QEMU name `actryn-install-robot`,
  TasksMax256/MemoryMax3GiB/Restart=no are accepted. The guest remains 2GiB with
  its original kernel, DT, disk, UART and production profile.
- `fixture`: native process `pid`, `start_ticks`, `exe_sha256`, absolute
  `admin_path` and `controller_path`. The actual QEMU chardev argument must name
  this socket. Only the existing read-only `status` datagram command is sent.

All target facts are rechecked: machine, actual boot, Debian-selected ARM kernel,
non-actuating DT compatible, immutable slot digest, loaded module note and loaded
manager/gateway executable paths/hashes. Only public identity generation, CA/
certificate hashes and policy hash are retained; device private keys are not read.
Plan/CLI/reader mismatches fail before any grant. A pidfd is opened for the exact
host QEMU and checked against PID/start/argv/InvocationID **before setup can grant**.
Changed identity never causes a search for another process.

## Freeze/crash phase

```sh
python3 -B apps/robotd/tests/guest_freeze_crash.py freeze \
  --plan /PROTECTED/current-a04-plan.json --output /NEW/a04-freeze01
```

Existing setup performs one explicit Recover/Rearm/Prepare/30-second Grant/
Activate. A production CLI handle is saved before the sole SDK proposal, whose
fixed target is `[100, -100]` and duration is `10000` ms. The campaign requires
acknowledged full RUNNING identity, healthy sources, a durable nonterminal snapshot
and matching original SQLite intent/operation bytes. Missing/terminal evidence
fails; the target, deadline or process is never changed to obtain a running case.
The complete original history and operation are retained in `before-freeze.json`.

The one pidfd SIGSTOP freezes all QEMU threads. Actual socket inode inventory is
retained and rechecked while frozen. Status replies require kernel-supplied sender
credentials matching the same native fixture process. The same controller boot/
session must change from enabled nonzero Active to disabled-zero Faulted while
fixture time advances at least the unchanged 500 ms sample ceiling, within the
two-second observation ceiling. Queue saturation does not establish this predicate.

**Cause boundary:** existing status exposes no fault reason or last applied
absolute expiry. The report retains the last observed controller receipt timestamp
and explicitly marks absolute expiry unavailable. Faulted/zero plus retained
socket/process and timing is a **source/timing inference**, never a directly
observed expiry reason, exact stopping latency or physical disable proof.

Only after this observation does the same guarded pidfd receive one SIGKILL.
Process death and inactive/failed unit with MainPID0 must be confirmed. The phase
has a 90-second cutoff. `FROZEN_CRASH_COMPLETE` permits only the later inspected
restart; it is not the A04 PASS result. Native fixture, original disk, prior
serial, handles, checkpoints and journals must be retained.

## Parent-controlled restart and inspect phase

Root reviews the freeze result, preserves old serial bytes and restarts the **same
disk**, using the reviewed original QEMU tuple and host ceilings. Only new serial
and QMP diagnostic paths may differ. No clean-disk replacement, snapshot rollback,
state deletion or fixture reset is permitted. The installed Robot daemons must
remain inactive; their disabled installation units do not become auto-started.
Root explicitly loads only the installed signed-slot module using the existing
bootstrap instructions, and records its note pin; this does not open the registry.

Before the destructive phase the harness also requires both installed units to
have `UnitFileState=disabled`. On the new boot, inactivity alone is insufficient:
both units must report `ActiveState=inactive`, `MainPID=0`,
`UnitFileState=disabled`, and `ExecMainStartTimestampMonotonic=0`. Retain these
exact fields in the parent's reboot handoff; do not stop a previously started
service or clear its state to manufacture this predicate.

Create a separate protected restart JSON containing the freshly observed `boot_id`
and `qemu` identity object with the same fields as above. Both PID and InvocationID
must be new; machine, manifest, identity and retained disk must match.

```sh
python3 -B apps/robotd/tests/guest_freeze_crash.py inspect \
  --plan /PROTECTED/current-a04-plan.json --before /NEW/a04-freeze01 \
  --restart /PROTECTED/a04-new-boot.json --output /NEW/a04-inspect01
```

Before normal service open, `cold-runtime.tar.gz` preserves the entire runtime
intent DB, any journal, immutable bindings and complete/partial capture files.
It excludes the identity/key directory. Inventory is bounded to 2048 regular files,
32 MiB per file and 256 MiB total, with a 1 MiB inventory cap. All bytes/hashes are
verified locally. A separate `mode=ro` SQLite query checks the exact unfinished
operation and all original rows. A hot-journal read failure is recorded as a failure;
the harness does **not** repair the source, delete its journal or silently retry.

Three additional read-only records, `cold-services-before-archive.json`,
`cold-services-after-archive.json`, and `cold-services-before-start.json`, repeat
the service fields and current-boot journal checks. Each retains the actual boot
before/after, exact argv, status, stdout/stderr and timeout/overflow flags for four
queries. Each command has a two-second timeout; retained stdout/stderr are capped
at 64 KiB/8 KiB, with overflow rejected. The journal commands use `--lines=1`,
restricted JSON fields, `--no-pager`, and the exact boot UUID as a 32-digit ID:

```sh
journalctl --no-pager --quiet --boot=BOOT_ID_HEX --lines=1 --output=json \
  --output-fields=_BOOT_ID,__MONOTONIC_TIMESTAMP
journalctl --no-pager --quiet --boot=BOOT_ID_HEX --lines=1 --output=json \
  --output-fields=_BOOT_ID,__MONOTONIC_TIMESTAMP \
  --unit=actryn-robotd.service --unit=actryn-gatewayd.service
```

The first must return one valid current-boot anchor with its cursor and monotonic
timestamp. The second must return no entry: even a prior unit start/stop record
rejects inspection. Missing journals, warnings, nonzero exits, malformed anchors,
timeouts and overflow remain uncertainty and fail closed. Plan02's parent handoff
must collect the same successful anchor and empty unit query before inspection;
the harness independently repeats them. No journal sync, vacuum, rotation, repair
or service-state mutation is performed. This uses the trusted host/journal
assumption; it does not establish absence after deliberate journal erasure.

The selected properties and filtering behavior are documented in the primary
[systemd v257 D-Bus interface](https://github.com/systemd/systemd/blob/v257/man/org.freedesktop.systemd1.xml)
and [journalctl documentation](https://github.com/systemd/systemd/blob/v257/man/journalctl.xml).
`--unit` includes both service messages and manager messages about that unit;
`--boot` selects `_BOOT_ID`. Restricted JSON retains the cursor and timestamps.

Only after preservation/inspection does one explicit service start occur. The
loaded installed executables are reverified. Without Recover/Rearm/Prepare/Grant
or Propose on this boot, three fresh authenticated connections query the original
saved handle. They must return the identical full operation as terminal
`OutcomeUnknown`, with no live authority, reconciliation or cancellation claim.
Kernel operation/grant/stream stay zero and there is no prepared instance. All raw
historical rows remain unchanged, with no new allocation/submit record.

`Engine::inspect` deliberately projects an unfinished physical DB row to UNKNOWN
read-only. The test does not invent a persisted phase8/retired bit or prepare new
work just to force a database transition. Legitimate future maintenance remains
separate. The old capture is exported with the pinned CLI and decoded by the pinned
production reader. One original allocation/START/proposal must remain visible;
completed/cancelled/reconciled work cannot establish an interrupted operation.
Crash remnants and supported private-copy checkpoint recovery remain explicit;
metadata-only evidence stays execution-replay-ineligible.

## Failure and verification

The inspect phase has a 240-second cutoff and bounded command/read/helper waits.
The parent retains an external watchdog; uninterruptible storage is not given a
hard fsync guarantee. All mutations and host signals are one-shot. Before an
attempted freeze, a failure can issue one reserved local revoke. After a freeze
attempt there is no automatic SIGCONT, repeated kill, VM boot, service restoration,
recovery or proposal resend. A stopped or uncertain VM is handed back for review.
An inspect failure likewise preserves raw state and reports its original error.

PASS is written only after SSH cleanup, actual history/export checks and hash
collection. `phase-result.json` binds the artifact inventory hash and is its final
sentinel; the inventory excludes itself and that sentinel. A `failure.json` always
invalidates success. Earlier failures/unknown acknowledgements are never relabeled.
Before opening SSH or creating inspection output, inspect verifies that sentinel's
inventory digest and bounded regular-file hashes for the original plan, source
pins, handle, before-freeze handoff, crash record and fixture closure. The retained
plan/source must match the selected current inputs; embedded handoffs and closure
proofs must agree. Missing, substituted or mixed phase records reject inspection.
The existing source-pin map includes all sibling test Python files and the three
executed SDK files `sdk/python/actryn/__init__.py`, `client.py`, and
`robot_v1_pb2.py`. Plan02 must pin those same files. An SDK change or missing file
between freeze and inspect rejects before inspection output or SSH is opened.

Host-only checks exercise signal order/no retry, a real owned temporary child with
pidfd SIGSTOP/SIGKILL, real read-only SQLite bytes, immutable history, UNKNOWN
identity, malformed archive bounds, late-read rejection, final hash failure and
tampered handoff rejection before any SSH/output opening:

```sh
python3 -B -m unittest discover -s apps/robotd/tests -p test_guest_freeze_crash.py -v
python3 -B apps/robotd/tests/guest_freeze_crash.py --help
```

These checks launch no VM and do not establish the target A04 result. Actual
execution requires the parent's separately recorded current-guest handoff.
