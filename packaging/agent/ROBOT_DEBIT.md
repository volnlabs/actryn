# Retained Robot debit: cancellation, server guest loss and capacity

**SOURCE PREPARED / actual campaign NOT_RUN.** This opt-in harness uses the
installed disposable server and non-actuating Robot. It neither installs software
nor enrolls identities, alters service limits, changes peer configuration, invokes
a provider, controls QEMU, or retries proposals. Parent review and separately
scheduled actual execution are required. No physical or complete replay claim is
made. This is a narrow A04/A05/A08 campaign, not closure of those entire gates.

The offline/model `calls` row settles **before** actual Robot dispatch in
`apps/server/src/service.rs`. The separate `robot_requests.outstanding` debit
remains charged until a valid, matching durable downstream settlement. The test
must retain both facts. A settled offline call or a reaped sandbox is not proof
that the Robot debit was released. `Store::mark_reaped` does not erase that debit.

## Prerequisites and fixed inputs

Use the preserved, explicitly selected installed server03 and a separately
scheduled Robot with the approved module (module16 selection remains external).
Supply each guest's distinct SSH key, a verified known_hosts file covering both
ports, actual machine IDs, server immutable manifest SHA256, actual manager ELF
SHA256 and loaded module-note SHA256. The script verifies these targets before
the inherited helper can create guest output or request Robot recovery. It
rejects existing tasks/unreaped attempts or outstanding Robot debits. Fresh
campaign output is mandatory; previous failures are never overwritten.

Use only the original credential-free OCI manifest
`sha256:c3013959f5cca4a2275fa5f26de6f030dcc011241dbbe5961993a406e2e53d45`.
Its agent sends `preview-1`, fixed +10/+10 ticks and1000ms, then remains alive for
60s after its output. No target, observation freshness, operation deadline,
recording or grant ceiling is increased. The broker's reviewed limits remain
Robot per-attempt1/global4/keys16, closure inventory16, sandbox active1/prepared1.
The harness checks the source declarations and exact selected service hashes.

The caller explicitly provisions the reviewed public Robot peer and systemd
workload credential beforehand, following the existing combined recipe. Keep
the separately retained original peer/drop-in/credential metadata for later
restoration. Never print or bundle private keys. Public peer `endpoint` must be
`10.0.2.2:GATE_PORT` for the selected QEMU user network, installed **before** bind.
The host gate listens only127.0.0.1:GATE_PORT and forwards to the explicit host
Robot TCP forward. DNS, CA, client certificate and exact Robot leaf pin are
unchanged; TLS terminates at robotd. The endpoint is part of the typed Rust
PeerConfig digest. Keep its exact public configuration unchanged through
cancellation, guest loss, restart and settlement. Switching back to a direct
endpoint early invalidates retained bindings. The script never changes it.

## Gate and actual operation

`debit_gate.py` uses at most8 active sockets,64 accepted connections,4KiB copy
chunks,256KiB per connection and8MiB observed bytes. Its whole lifetime is1200s;
pass-through connections have15s and blocked connections6s cutoffs. Gate errors
fail the campaign. No ciphertext is stored for replay, no TLS is decoded, and
no connection is automatically retried. The host loopback echo tests prove byte
transport decisions and caps, not a real TLS/Robot execution.

The server opens a fresh TLS connection for each Describe/Observe/Propose;
retained closure uses Describe followed by Cancel on another connection. Thus
the existing one-connection A02 ReplyGate cannot serve this campaign unchanged.
The new gate changes **future accepts only**. A preconnected direct authenticated
SDK watcher validates healthy admission before the one launch, then polls at
10ms for up to3s (one-second per-RPC deadline). On matching prepared attempt/
namespace and exact kernel/runtime RUNNING full operation identity, it arms the
gate immediately. Only the last16 diagnostic snapshots are retained. Existing
Propose traffic and its acknowledgement continue normally. No first-reply race
or inference about an opaque TLS method is needed.

The watched key/full identity must match the durable server handle and an
independent **direct Robot** Query. A missing one-second operation window is a
failed campaign, not permission to change the target or repeat launch. Do not use
`server robot-query` here: that can settle the very debit under test.

## Phases and parent-owned crash

The script reuses `guest_robot_acceptance.Campaign` SSH/protocol, credential,
lineage, export and local authority helpers. It uses separate predicates for
local reap and remote settlement instead of the happy-path cleanup helper.

1. **Cancel:** create one real delegated operation, observe its matching identity
   and retain outstanding1. Cancel the server attempt once through its reserved
   route. Require both stores reaped, cgroup absent, the offline call settled but
   publication closed/outputNULL, and the Robot debit still1. The unresolved
   export preserves its original binding/handle and debit. Original agent output
   was already published; this does not claim a delayed provider-reply test.
   Direct Robot reads wait for actual durable terminal reconciliation, followed
   by explicit local retire/recovery. They do not settle the server's debit.
2. **Crash handoff:** create a second actual operation/debit and leave its server
   attempt running. Retain an active partial export and immutable handoff with
   original boot, all handles, peer digest, source pin, catalog and gate report.
   The harness does not send another agent/model/Robot proposal. It waits for a
   bounded explicit stdin continuation while its stable gate remains alive.
3. **Parent crash/reboot:** the parent verifies the precise disposable QEMU unit,
   PID lifetime and disk before its separately authorized abrupt SIGKILL. It
   preserves actual signal/exit evidence and reboots that same disk, then
   explicitly starts the installed units. There is no VM control in this script.
   The signal must occur by the handoff's20s cutoff, comfortably before the
   original agent's60s keepalive can expire. Reboot/operator coordination may
   take up to the distinct300s continuation cutoff. A missed cutoff fails closed
   and retains uncertainty; no signal, reboot or mutation is retried.
4. **After boot:** require the new supplied boot ID and original machine/manifest/
   service/module/peer pins. Read-only inspections must show the second attempt
   unknown/reaped, first still cancelled/reaped, both debits1, all publications
   closed/outputNULL, no extra attempt IDs or container tasks. Recovery may send
   closure only; blocked future connections prevent a matching remote response.
   The old Robot operations/keys remain the comparison identities.

The parent retains an independently observed crash record of at most64KiB:

```json
{
  "action": "SIGKILL_QEMU",
  "unit": "actryn-install-server03.service",
  "pid": 12345,
  "old_server_boot_id": "ORIGINAL_OBSERVED_UUID",
  "at_monotonic_ns": 123456789000,
  "verified_signal_exit": true
}
```

Set `verified_signal_exit` only after actual host unit/process readback confirms
the intended QEMU died by that signal, not merely because a command returned0.
The parent owns the unit/PID lifetime evidence; the harness validates the record's
identity/timing and retains its hash. A changed boot ID alone is insufficient
evidence of abrupt termination. The explicit stdin line is:

```json
{"continue":"AFTER_REVIEWED_SERVER_REBOOT","new_server_boot_id":"NEW_OBSERVED_UUID","crash_record":"/PROTECTED/PARENT/crash.json"}
```

There is no shell interpretation of this line or VM-command field. Each ordinary
phase has180s, final settlement300s, plus the independent overall gate cutoff.
Continuation bytes are read incrementally under the original absolute phase/gate
deadline: at most1024 bytes including exactly one terminating newline. Partial
input does not extend that deadline; premature EOF, extra buffered lines and
oversize frames fail. Every SSH/command wait is bounded by its phase cutoff. On failure the script
retains FAILED, attempts, handles and gate state, then attempts one distinct
reserved local revoke only if the original Robot machine was verified. Failed
closure remains explicitly unknown; no automatic retire/recovery erases it.

## Optional global Robot pressure and final settlement

With `--pressure`, two more sequential actual operations and cancellations retain
exactly four Robot rows with outstanding1. Local sandbox slots can be free after
reap while these rows remain charged. The gate admits each new planned binding
only after the preceding blocked connections have drained. Reaped attempts do
not automatically retry closure; the previous failed response leaves their debit.

A fifth bound attempt may be prepared, locally granted/activated, launched, and
admitted to an ordinary broker reservation. These are real admitted side effects.
It must then fail with the exact Robot-global-capacity diagnostic before creating
a Robot reservation, obtaining an observation or sending a Robot proposal. Check
all four exact rows unchanged, no fifth Robot row, a cancelled ordinary call, no
stdout, and no new kernel/runtime operation or output. Cancel/reap that sandbox
and retire/recover its unused Robot preparation. This does not claim exhaustion
of the16 closure entries, per-attempt second-call capacity, or provider budgets.

Opening the gate never releases old bytes. Bounded `server robot-query` calls now
inspect the **original** handles. Only matching durable terminal reconciled Robot
snapshots may clear each debit. Record before/after exports. The crashed attempt
keeps unknown local attempt outcome and incomplete logs even when its separate
remote operation becomes known. Optional pressure then performs one new actual
operation to prove released Robot capacity is reusable; it too is explicitly
cancelled/reaped, retired and settled. Final stores/tasks/debits must be clear.

Happy-path `omissions=[]` is inappropriate for the crashed attempt: old log
writers can lose a tail, `log_incomplete` must remain, final resource facts may be
missing, and old observer coverage is a retained prefix. Partial validation checks
exact core identities, canonical hashes, independent raw logs/absence and declared
omissions. It must never invent a complete episode, clean tail or new source epoch.

After success, the gate closes; peer configuration intentionally remains
unchanged. PASS is written only after gate workers have joined and final error,
counter and lifetime checks pass. Gate shutdown failures are retained as FAILED.
Parent explicitly stops server units and restores the separately
retained original peer/credential configuration only after all debits are0.
Restoration is not silently claimed tested by this harness. On failure retain the
stable endpoint, keys, disk and records for deliberate closure/reconciliation.

## Host verification and actual invocation

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s packaging/agent -p test_robot_debit.py -v
python3 packaging/agent/guest_robot_debit.py --help
```

Supply every endpoint and pin explicitly; there are no SSH/Robot port defaults:

```sh
python3 packaging/agent/guest_robot_debit.py --allow-disposable-guests \
  --server-ssh-key SERVER_KEY --robot-ssh-key ROBOT_KEY --known-hosts BOTH_HOSTS \
  --server-port SERVER_SSH --robot-port ROBOT_SSH --tcp-port ROBOT_TLS_FORWARD \
  --gate-port REVIEWED_GATE_PORT --server-qemu-unit actryn-install-server03.service \
  --server-machine-id SERVER_MACHINE --robot-machine-id ROBOT_MACHINE \
  --server-manifest SERVER_MANIFEST_SHA256 --robot-manager-sha256 MANAGER_SHA256 \
  --robot-module-note-sha256 MODULE_NOTE_SHA256 --cli SELECTED_HOST_CLI \
  --guest-cli /usr/bin/actryn --peer-config GATED_PUBLIC_PEER_JSON \
  --ca TEST_CA --certificate CLIENT_CERT --client-key PRIVATE_CLIENT_KEY \
  --artifact sha256:c3013959f5cca4a2275fa5f26de6f030dcc011241dbbe5961993a406e2e53d45 \
  --output NEW_PRIVATE_OUTPUT --pressure
```

Actual execution is separately scheduled after the module decision. No guest was
launched, altered, killed or restarted while preparing these source files.
