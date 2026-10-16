# Fixed standalone observer overhead and loss

**SOURCE PREPARED; actual measurement NOT_RUN.** This is a narrow descriptive
D2/A16 measurement, separate from the frozen Robot kernel-versus-userspace
comparison and from the installed-server readiness/death/loss acceptance campaign.
It measures neither full installed agent-workflow overhead nor physical behavior.
No guest, service, VM or build action was taken during source preparation.

## Fixed protocol

The planned order is exactly **OFF, ON, ON, OFF, ON, OFF, OFF, ON**, with four
adjacent OFF/ON pairs. There are no discarded warmups, reruns, timing-based
exclusions, workload escalations or post-hoc reordering. Every failed, started or
not-run trial stays in the eight-trial denominator. A failure aborts later
mutations; it does not trigger another trial. The script has one 360-second
experiment cutoff, with smaller command/RPC/helper bounds. A separate five-second
read-only terminal service snapshot may report unknown states after failure; it
never extends experiment eligibility.
READY/DONE frames and partial source/timing prefixes are retained even when a
later retirement or cleanup check fails. Such a prefix is not promoted into a
completed, comparable trial.

Run only during exclusive trusted local maintenance on the selected disposable
installed server. Initially all three services must be explicitly started and
healthy. The script pins exact Debian 13.7 amd64, kernel
`6.12.111+deb13-amd64`, caller-supplied machine/current-boot IDs, installed manifest,
loaded executable identities and fixed CLI/BPF assets before stopping anything.
Both stores must contain only reaped attempts, no open/unresolved ordinary calls,
and no outstanding Robot debits; containerd must have no tasks. A reaped sandbox
alone does not establish this quiescence. The server and launcher are then stopped
explicitly, with state readbacks retained. Neither is restarted by this campaign.

OFF stops only the installed observer. Before that stop, the script retains its
five actual program IDs from `/proc/PID/fdinfo`, bound to the verified process.
The read-only amd64 `BPF_PROG_GET_FD_BY_ID` lookup must return **ENOENT** for those
specific IDs. Permission failures or a surviving object cannot establish OFF.
Even a detached object held elsewhere conservatively blocks that control. The
script never detaches other programs, disables device/isolation BPF, writes policy
maps or interprets absence of a service as absence of its probes. Other host BPF
instrumentation is not claimed absent. ON uses the installed observer normally;
its actual PID-bound IPC listener, dropped loader capabilities and fresh healthy
registration must be verified. Adjacent ON trials can share a collector process,
but each has a fresh registered cgroup identity and retained trace.

Each trial creates a fresh, root-owned `/actryn/UUID` cgroup, applying/readback-
checking the same memory/swap/PID/CPU/I/O ceilings as the selected server profile:
256 MiB, no swap, 64 PIDs, `50000 100000`, and whole device `254:0` at 1 MiB/s and
128 operations/s. A trusted standalone Python helper is its sole process. This
is not an OCI agent and has no claimed namespace/seccomp/device isolation proof.
It performs exactly the reviewed `tests/observer/guest.py` workload: 30,000
`/dev/null` opens. The same child source and interpreter flags are used in both
arms; the exact child source/hash is retained. No provider, Robot, SDK or live
credential is involved.

The bounded READY/GO/DONE/ACK handshake verifies the child PID/start/cgroup before
the loop. Child startup/imports finish before READY. The helper measures loop
wall time with `monotonic_ns()` and its own user/system CPU deltas with `getrusage`.
It parks after DONE so ON source counters can bracket precisely the 60,000
selected open-entry/return events before process exit. It has a 15-second alarm;
parent reads use absolute deadlines and at most 2048 bytes per frame. Failed
helper cleanup has one kill and a two-second reap attempt, with no implicit
context-manager wait. Missing cleanup remains unknown.

## Recorded quantities and analysis

Each raw trial retains loop wall/user/system CPU, the exact child identity,
cgroup CPU/memory counters before/after, guest CPU/steal and CPU-pressure readback
brackets, source health before/after, and final original-epoch summary. ON also
reports observer process CPU ticks across loop-through-retirement, its clock-tick
resolution, post-loop health RPC time and retirement RPC time. Those RPC intervals
exclude the harness's own intent/reply fsync, but include connection/protocol and
collector work; retirement's known reply includes the actual JSONL/summary sync.
They are not isolated storage-latency measurements. Loop timing excludes service
startup, registration, observer retirement, Python startup and orchestration.
Collector CPU is reported separately rather than silently treating asynchronous
recording as free.

ON loss may be positive under this fixed workload. It is retained, not used to
discard a slow trial or to authorize a modified workload. Final raw records must
match the original boot/attempt/cgroup/collector and unique source sequences;
missing-record count must equal the final source loss count. The actual synced
summary and raw-file byte count/hash are checked. Pre/post loop frontiers are
retained separately from whole-helper lifetime totals, which also include startup
and exit. OFF has no observer: loss is **unavailable**, never an invented zero.
Source-order delivery across CPUs is not required to be sorted.

The pure `analyze()` function retains all eight raw outcomes, per-arm sample
counts/minimum/median/maximum wall time, four signed paired wall/CPU deltas and
relative wall deltas against the corresponding OFF sample. Missing pairs have
null deltas. Negative deltas remain negative. There is no significance test,
superiority inference, hard-deadline/WCET claim or automatic release qualification.

Unresolved biases are explicit: Python interpreter cost dilutes syscall-specific
effects; QEMU/KVM scheduling, steal and shared-host noise remain; CPU-quota phase
and startup budget consumption can affect loop wall time; four balanced pairs do
not eliminate cache/order effects. The 1 MiB ring and 16 MiB retained-log ceiling
can cause loss, changing ON processing cost after saturation. Thus the result
describes this exact bounded diagnostic stack and workload, not unlimited,
loss-free BPF or full sandboxed-agent performance. Parent scheduling must keep
other timing campaigns, builds and heavy storage activity separate.

## Invocation and retained state

Stage a protected source subset preserving repository-relative paths:
`tests/observer/overhead.py`, `apps/server/tests/guest_observer_gap.py` and
`apps/server/tests/guest_capacity.py`. Their hashes are retained. No dependency
download, compiler, bpftool installation or production file replacement is needed.
The direct BPF lookup uses the fixed Debian amd64 syscall ABI; unsupported access
fails closed. Use a fresh private `/var/tmp/actryn-observer-overhead-*` output.

Historical server03 preparation pins are machine
`14fea5c769be49d59a0f79d2049d16f4` and manifest
`0f2ea983181abfbcca5a3edffe9d34ebd34f7b129039d8c1f55b95eae278f4bc`.
They must be checked against the selected guest; its current boot UUID is a fresh
caller input. These are not newly observed measurement results.

```sh
/usr/bin/python3 -B -E -s /PROTECTED/SOURCE/tests/observer/overhead.py --allow-disposable-guest \
  --machine-id VERIFIED_MACHINE_ID --boot-id VERIFIED_CURRENT_BOOT_UUID \
  --manifest VERIFIED_INSTALLED_MANIFEST_SHA256 \
  --output /var/tmp/actryn-observer-overhead-01
```

Successful completion explicitly stops the observer too: all three services are
left stopped, retained attempt states and unresolved-work counts are unchanged,
and trial cgroups have retired.
Initial/final full service states are retained. The operator reviews measurements
before separately restarting any service. Failure performs no hidden restoration,
repeated service operation, registration or workload. Preserve the exact output,
disk and old-epoch observer prefixes; inspect recorded cgroup identities and any
unconfirmed helper/registration before explicit recovery. Synchronous storage can
still stall on a broken filesystem; the parent owns an external campaign watchdog.

Host checks run without guest/service actions:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s tests/observer -p test_overhead.py -v
python3 -B tests/observer/overhead.py --help
```

The actual invocation has not been executed during source preparation.
