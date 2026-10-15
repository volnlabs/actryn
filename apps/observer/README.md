# Fixed diagnostic observer

`actryn-observer` loads the installed `/usr/lib/actryn/observer.bpf.o` with
libbpf-rs, verifies the five-program set and attaches all required tracepoints
before it serves `/run/actryn/observer.sock`. Revision 1 requires the exact
Debian `6.12.111+deb13-amd64` kernel and x86-64 native syscall ABI. It is not
an enforcement program. The BPF feature manifest is `bpf/features.json`.

The restricted root launcher registers its generated attempt, boot ID and
cgroup inode/path before container task creation. The observer verifies the
canonical root-owned cgroup and assigns its own collector epoch. Only root can
use the mode-0600 Unix socket; requests are length-prefixed JSON (four-byte
big-endian size, at most 65,536 bytes, one request per connection). There are
eight command slots and eight live registrations. A timed-out command may
have completed: retry the same identity; never allocate a substitute attempt.
Health/readiness has no default-success path. Reader stalls, failed loading,
missing probes, epoch changes and evidence loss block a policy-dependent launch.
Installed cgroup, namespace and seccomp enforcement does not depend on this reader.

Only registered cgroups generate events. Fixed metadata contains process/thread
IDs, fork child/exec old PID, task comm, selected syscall number/result, monotonic
time and source sequence. No path, argv, file contents or network payload is
collected. Agent-controlled comm is serialized as data. An error return is
`access_failed`, never `policy_denied`. A successful syscall is an observation,
not proof that an entire tool operation succeeded.

The kernel ring is 1 MiB. Sequence allocation precedes ring reservation so loss
is visible; different CPUs may deliver records out of sequence. The per-attempt
metadata spool is capped at 16 MiB. Ring loss, a full spool or a failed write
latches incomplete evidence and makes readiness false. The spool is JSONL under
`/var/lib/actryn-observer/<epoch>/<attempt>.jsonl`; it feeds the evidence exporter,
and is not itself a complete MCAP episode. No live durability claim is made.
After a reaped, unpopulated cgroup is unregistered, the observer syncs its file
before a summary and directory sync. Interrupted files remain as raw evidence.
Storage may exceed the IPC deadline; retry unregister with the same identity.
Failed sync keeps the registration for explicit retry/recovery. Export/retention
management must preserve incomplete files and is part of release packaging.

Build the BPF object with `make -C bpf` and Rust with
`cargo build -p actryn-observer`. Install the binary, fixed object and
`packaging/systemd/actryn-observer.service` on the supported Debian server.
Tracefs must be mounted for attachment. The service uses only BPF/perf/resource
capabilities and cannot modify cgroups or load kernel modules.

Run `cargo test -p actryn-observer` for decode/registration checks.
`tests/observer/guest.py` runs actual attach/process/syscall/retention tests as
root in a disposable supported guest, with no existing observer service.
It checks successful and failed OS access, lifecycle events, rejected identity
changes and loss at the retention cap. These are software diagnostics, not
robot, physical or complete-isolation acceptance.

API sources: [libbpf lifecycle](https://docs.kernel.org/bpf/libbpf/libbpf_overview.html)
and [libbpf-rs 0.27.2](https://docs.rs/libbpf-rs/0.27.2/libbpf_rs/).
Original Rust userspace is Apache-2.0; the C BPF integration is GPL-2.0-only.
