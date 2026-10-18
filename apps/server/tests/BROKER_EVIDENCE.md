# Fixed sandbox/broker evidence — preparation only

`broker_agent.c` is test-only. Compile it statically; **never execute it on the
host**. All original negative probes, five broker calls, cancellation-before-call,
fork/sleep behavior and `BROKER_ACCEPTANCE_PASS child=...` remain. Each syscall
result/errno and nested broker JSON reply is flushed before its old assertion.
Names and format strings are fixed. Malformed/multiline/duplicate-key broker
JSON fails the host parser; an old marker alone is insufficient.

Before making any broker socket, one bounded `/proc/self/fd` enumeration checks
at most4096 directory entries, excludes only its own enumeration FD, and rejects
every other FD>2. `fstat` requires present stdio FDs to be non-sockets; only stdin
may be absent, with EBADF. No descriptor content is read. Counts/errors and the
single directory-close result are emitted before assertions. This source-bound
check addresses inherited sockets, separately from network topology. A new
`setns(-1,0)` check requires EPERM: even a wrong filter can only yield EBADF for
this invalid descriptor; it cannot enter a namespace.

`broker_evidence.validate(...)` is inert: no process, guest, SQLite, image import,
service or Robot action. It consumes retained public bytes:

- `expected`: Root-selected `{attempt, artifact, agent_sha256}` fixed before the
  attempt; `artifact` is the OCI manifest digest, not the layer or tar-file hash.
- `manifest_raw`, `config_raw`, `layer_raw`: exact selected OCI blobs from
  `packaging/agent/build_oci.py`. Check every descriptor/digest, offline profile,
  entrypoint/UID and exactly three regular fixed members, including agent hash.
  The tar is read in memory, never extracted. This does not create a compiler
  receipt or independently establish source-to-binary equivalence.
- `prepared`: the actual prepared inspection's `attempt` object, including
  `outcome="pending"` and complete JSON `binding`, retained before Start.
- `stdout`, `stderr`, six-artifact `bundle`, final reaped `inspection`, observer
  `summary` and raw JSONL `trace_raw` from the same attempt.

Fetch the final Broker inspection with `server status` after known `server
cancel`, even when Cancel already reports `reaped`. Cancel returns the Launcher
inspection, whose calls and denials are empty. The stores set Start deadlines
independently, so their `deadline_ms` values can differ. Retain both replies and
their deadlines unchanged; compare the Broker inspection's accounting with the
export while binding their shared attempt, artifact and runtime identities.

The existing `guest_capacity.validate_export` still rejects any denial by
default. Its explicit `expected_denials` option compares exact broker-export
and inspection records/counts. This validator selects only
`denied-1/admin.grant/method_not_allowed`, keeps allowed `offline-1` and result
control bound to the actual attempt, and verifies durable `cancel-first` plus
closed late-call rejection. It does not normalize away real evidence.

The owner must separately establish the installed package/config/provider tuple,
fresh VM/process lifetime, approved agent build/source hash, import approval,
old history/raw custody, finite stage bounds, zero Robot bindings, and one known
Start/Stop with no retry. The agent's PID/TID1 is its private namespace PID;
host PID/start/cgroup come from the prepared binding and kernel exec/fork trace.
Never run the old `guest_broker.py` main on the retained installed guest: it
rewrites configuration, uses UID991 and starts manual services. No new target
executor or execution authorization is provided here.

## What the observer can establish

The selected x86-64 `bpf/observer.bpf.c` records openat257/connect42, selected
privileged calls, and lifecycle, **not socket41**. Validate complete source
sequences, loss0, exact attempt/boot/cgroup/epoch, leader exec, one fork and both
leader/child exits. All integer event fields reject JSON booleans. The fresh
FD-enumeration openat must first succeed, matching its reported FD (including0
when stdin was absent). Four subsequent direct openat probes require matching
entry/exit results: three ENOENTs and EROFS/EACCES. These are namespace/read-only-path
observations, not device-policy-origin events. Five AF_UNIX broker connects
must succeed and have matching entry/exit records.

Official upstream stable v6.12.111 `kernel/entry/common.c:53–64` calls
`__secure_computing` and can return before `trace_sys_enter`;
`arch/x86/entry/common.c:74–84` then skips the syscall body for nr=-1 and returns
through the exit path. Therefore bpf/perf/unshare/setns/mount EPERM records are
source-attributed probe output, separately bound to the selected agent and
prepared seccomp2/caps0 profile. Their missing entry records are **not** evidence
of observer loss, policy origin or a paired syscall. Exit-only or absent selected
records are supported. Never require impossible enter pairs or treat absence
as proof of enforcement.

Primary upstream sources (not an audited Debian patchset):

- <https://raw.githubusercontent.com/gregkh/linux/v6.12.111/kernel/entry/common.c>
  SHA256 `ecf9a1bdd58e02ba5c710d383e77a7000b39e3de6b75237c5d677514b10ead6d`.
- <https://raw.githubusercontent.com/gregkh/linux/v6.12.111/arch/x86/entry/common.c>
  SHA256 `a5e6b39f2832923a384ef61c220b2df064f24c418ffa363d37e12e1a0eeda767`.

AF_INET socket denial is distinct from a failed external connect: this workload
has no such connect path, and the fixed profile has zero external routes. Do
not relax socket/network privileges just to produce an observed connect denial.
The exported admin.grant denial is broker-origin policy evidence; the remaining
agent JSON remains classified as untrusted output. No physical, hostile-root,
whole-D2 or release qualification claim follows from these host checks.
