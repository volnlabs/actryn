# A16 fixed software comparison (revision 1)

Qualification now requires the [premeasurement revision-2 amendment](amendment2.toml)
below. Original revision-1 inputs and builds remain immutable.

Status: host engine, socket-lifetime, analyzer and profile checks PASS;
target qualification NOT_RUN. No comparison has run. This is a
test-only userspace baseline, never a production Robot backend or installer.

## Frozen configuration and workload

Use Debian 13, Linux `6.12.111+deb13-arm64`, QEMU 11.1.1 `virt`, Cortex-A72,
two vCPUs and 2048 MiB, with the same disk, fixture executable and immutable
`qemu-arm64-fixture/1` software limits. The kernel arm uses the production
exclusive serdev DT. A separately identified test-only DT exposes the second
PL011 as `/dev/ttyAMA1` only for the userspace arm. Root owns those VM manifests.
Both arms refuse hardware, a different kernel, or simultaneous raw-TTY and
authority-device access. No physical limits are inferred.

The baseline has one fixed endpoint, owner and grant, four role connections,
32 RX frames, 256 event records, one immutable started frame and one unsent
sample. It uses copied UAPI requests, the existing C wire codec/control ordering,
typed limits, absolute deadlines, observation and recording health, receipts,
quiescence, immutable partial recovery and an independent controller expiry.
The gateway owns the UART through private permissions and `TIOCEXCL`; its
nonblocking event loop watches the registered owner through a pidfd and checks
per-message credentials. The trusted workload denies exec before registration.
Owner loss invalidates authority even while another process retains a socket.
The gateway rechecks pidfd readiness immediately before its transmit tick.
Eight socket connections, one pending reply per connection and requested 4096
byte send/receive socket buffers bound IPC storage (Linux may double/min-clamp
the requested buffer sizes). The gateway performs no persistence on its event
loop; both arms use the same workload's durable operation intent and JSON log.

Run four boot blocks in order **kernel, userspace, userspace, kernel**. In each
block run mandatory evidence alone, then the same evidence plus optional UART
diagnostic tracing. There are exactly ten trials per mode, with fixed order:
normal, cancel, delayed-applied, owner-exit, normal, cancel, delayed-applied,
owner-exit, normal, normal. Each ordinary trial requests ten zero-duty samples
at 100 ms intervals, with 400 ms sample deadlines, a 5 s operation, 15 s grant,
900 ms observation validity and 1500 ms health. Cancellation follows sample
five. Delayed-applied injects a 600 ms fixture response delay for a sample with
a 150 ms deadline. Owner-exit follows sample five. Every trial starts a fresh
handshake/rearm/grant, after acknowledged `delay 0` and fixture `restart`;
operation identity is durably recorded before START. The controller's durable
boot counter advances for each trial, and the module/gateway stays installed
through the ten trials of one mode. The explicit restart is excluded from the
recovery interval but included in whole-run CPU accounting.
The ordinary scenario timeout is 10 s. Fixed bounds are test budgets, never
observed or guaranteed latency limits. Setup failures consume their trial;
never replace a failed attempt with an unreported retry.

The executable accepts only arm (`kernel` or `userspace`) and a new evidence
directory. Fixture delay is coordinated with the existing bounded bridge.
No generated skills, model calls, TLS gateway or generic Robot runtime are
included. Those costs are not attributed to authority placement.

## Qualification before comparison

Independent assertions must establish: canonical request rejection; allocation
without dispatch; fresh observations and health; typed/slew limits; original
sample expiry; immutable and changed duplicates; cancel before START; no next
operation before matching timely quiescence; all partial-write offsets and
zero/error writes; stale epochs/ACKs; owner/FD transfer; grant non-resurrection;
bounded RX/event capacity; late receipts and absolute handshake timeout.
Tests use expected states/bytes defined independently of the baseline's
implementation, including the existing golden codec vector. A shared codec or
reducer executed twice is not an independent correctness oracle. Any missing
protection remains an explicit qualification failure and blocks measurement.

Run host qualification with `sh kernel/tests/a16/run.sh`. This compiles both
executables with strict warnings, runs the pure engine and actual Unix
credential/pidfd tests under ASan/UBSan, tests analysis denominators and checks
the exact profile constants. LeakSanitizer is disabled for this ptraced host;
address and undefined-behavior checks remain enabled. The host protocol test
does not run the complete gateway loop or qualify actual TTY ownership.

Before comparative execution, a separately retained **qualification pilot** on
the raw-TTY guest must pass the ten fixed trials, prove that the production
authority node is absent and another unprivileged process cannot open that
UART, and exercise inherited/transferred client denial against the live
gateway. Pilot output is correctness evidence only and must not enter the
frozen comparison. A target pilot failure blocks the matrix; no automatic
retries or alternate limits are provided here. Root owns that VM and its
independent qualification harness; the baseline remains unqualified until
those actual results and source review are recorded.

Build inside the exact ARM guest (never run this test backend on hardware):

```sh
cc -std=c11 -O2 -Wall -Wextra -Werror kernel/tests/a16/gateway.c \
  kernel/tests/a16/engine.c kernel/actryn_wire.c -o a16-gateway
cc -std=c11 -O2 -Wall -Wextra -Werror kernel/tests/a16/workload.c -o a16-workload
```

Run `a16-gateway` only on the isolated raw-TTY guest. Run `a16-workload kernel
NEW_OUTPUT` or `a16-workload userspace NEW_OUTPUT` through the existing fixture
bridge, which acknowledges the fixed controller instructions. A pre-existing
gateway socket is an error; confirm its process is stopped before operator
cleanup. Retain the binary/source hashes, DT, command line, guest/kernel/fixture
identities, stdout/stderr, exit status and the entire new output directory.
`analyze.py` accepts exactly eight `events.jsonl` paths in the frozen order.

## Measurements and limits

Retain raw requests, returns, events, fixture interventions, deadlines, boot and
session IDs, tool/source hashes, failures and all attempted-trial denominators.
Use guest CLOCK_BOOTTIME for admission call duration, submit-to-captured-applied
receipt, cancel-to-admission-closure and cancel-to-quiesced receipt, acquisition
age, recovery time and deadline misses. Event gaps and `events_lost` are loss
metrics. Record evidence bytes and guest-wide CPU deltas; baseline process CPU
is a separate diagnostic and cannot stand in for total kernel-arm CPU.

Optional common `uart_write` entry/return tracing may measure Linux buffer
acceptance after matching complete immutable frame bytes. It is not UART drain
or controller application. If reliable correlation is unavailable, dispatch
latency is NOT_RUN, never replaced with ioctl return time. Mandatory evidence
remains enabled in every arm. Trace overhead is compared on/off within each arm.

Report raw counts, median, p95 and observed maximum with sample counts, plus
failures/unknowns, without superiority or WCET claims. QEMU scheduling and host
contention are part of this software configuration. Userspace ownership relies
on Linux device permissions, exclusive open and the gateway process; the kernel
arm additionally retains transport ownership/lifecycle in the kernel. Neither
protects against hostile root/Linux, and neither proves physical response.
The kernel tracks the retained owner credential object and exec ID; the
baseline checks message PID/UID/GID and relies on the trusted workload's exec
filter and unchanged credentials. These mechanisms are not equivalent against
credential mutation or a malicious manager. The kernel workqueue polls health
at up to its configured worker interval (normally 10 ms here); the baseline
uses a 10 ms timer plus event-driven wakeups/pidfd readiness. Scheduler and IPC
cost differences are part of these two implementations, not isolated costs of
moving one identical instruction sequence across the syscall boundary.

Source owner: kernel lane (`kernel/tests/a16/**`). Root owns test-only DT/VM
configuration, quiet-window scheduling and the integrated acceptance report.

## Dedicated pilot preparation (not yet executed)

The [frozen manifest](manifest.toml) selects the separate `actryn-a16` guest,
ports 26224/27446, one 16 GiB disk, a new key and the pinned cloud image, boot
assets and fixture binary. Existing manager/server disks and fixture state are
never inputs. `prepare.py ROOT_REPO_WITH_PINNED_CACHE` requires a clean committed
kernel source tree, verifies hashes, and refuses an existing `.cache/qemu/a16`.
When explicitly executed, it creates a fresh disk, seed, private key, frozen
fixture copy, source archive and command JSON files. **It never starts a VM,
fixture or systemd unit.** A failed preparation remains recorded and cannot be
silently rerun over its directory. Command JSON uses a distinct serial log for
each provision/pilot/ABBA boot, with the same disk and hardware configuration.
Run preparation from the integrated source checkout: its frozen profile hash is
`6b9f174af8b018e0cf95bfd282ed52b5385d364ebe7e372d54ce6a91d1d99be8`.
An older development worktree profile fails preflight even when its authority
constants agree. Baseline source and driver hashes are checked independently.

Root starts only `actryn-a16-fixture` and `actryn-a16-robot` after checking ports
and memory headroom. The initial protected boot uses `qemu-provision01.json`;
the raw pilot uses `qemu-pilot01.json`. The fixture command uses only this new
directory's socket/admin/state files. Preserve its state across boot blocks.
Establish and retain this local guest's SSH host fingerprint in its own
`known_hosts`; use only its new `id_ed25519` and port 26224 thereafter.

Extract the prepared `source.tar.gz` into `/opt/actryn-a16/src` in the new
guest, then run `sh /opt/actryn-a16/src/kernel/tests/a16/provision-guest.sh`.
It checks the exact hostname, architecture, kernel and virtual-machine identity,
uses authenticated apt with bounded network/command timeouts and exact direct
package pins, records the full installed dependency inventory and apt lists,
then builds the module and test executables once. A new build directory is
required. It installs no module or daemon and makes no target-test claim.
The pins were checked against the Debian ARM64 pages for
[build-essential](https://packages.debian.org/trixie/arm64/build-essential),
[GCC 14](https://packages.debian.org/trixie/gcc-14),
[make](https://packages.debian.org/trixie/arm64/make),
[Python 3](https://packages.debian.org/trixie/arm64/python3) and the
[exact kernel headers](https://packages.debian.org/trixie/arm64/linux-headers-6.12.111%2Bdeb13-arm64/download).
Transitive package versions are recorded rather than falsely claimed to be
individually pinned; both comparison arms use that same provisioned disk.

With the appropriate dedicated mode already booted, run on the host:

```sh
python3 kernel/tests/a16/pilot.py protected /absolute/root/.cache/qemu/a16
# Root then stops only the dedicated VM and boots its same disk with raw DT.
python3 kernel/tests/a16/pilot.py userspace /absolute/root/.cache/qemu/a16
```

The protected pilot runs one module selftest and the diagnostic controller-reset
case. The userspace pilot starts only the new guest's test gateway, runs the
independent [live client](live_qualify.py), then the ten fixed workload trials.
The client defines its own binary UAPI layout and uses real Unix descriptors;
it does not import the baseline engine. It requires raw-UART access denial for
an unrelated unprivileged process, inherited/SCM_RIGHTS runtime-role denial,
continued admission of the original owner, and owner-death closure while another
process retains its runtime connection. It issues no grant or rearm. The ten
operation trials separately test the active path. Host tests of this client
check binary offsets, actual seqpacket framing and malformed replies, **not**
the live gateway or UART.

`pilot.py` has a fixed port and hostname guard, new immutable result directories,
bounded SSH/fixture/workload waits and no retry loop. A missing/failed trial,
wrong scenario order, lost events or incomplete capture blocks qualification.
It preserves failed output and partial captures and stops its test gateway;
it never starts/stops a VM or contacts the existing guests. The 60-second bridge
budget is a campaign timeout, not a latency bound. Target preparation, boot,
provisioning and these live pilot commands remain **NOT_RUN** until their actual
records exist. A passing pilot permits the already-authorized frozen ABBA
experiment; pilot rows never enter its measurement denominator.

## Premeasurement amendment 2

Read-only review found two qualification gaps before any pilot or comparison ran:
an unknown gateway-start reply skipped cleanup, and normal/cancel trials did not
check the specific closure reason or retained grant. Amendment 2 changes those
checks and the corresponding evidence only. Scenario order, request rate, sample
and health deadlines, duties, guest resources, authority driver, baseline engine,
gateway executable and controller remain the revision-1 configuration.

The original preparation is commit `cee3a2db674559355dcd6fc89918f72274839f4b`,
source archive SHA-256 `34b37b2b399b3af1917e8f62762364c92ed9c8aaf0532d8ab5f81d5503355d6d`.
Keep `.cache/qemu/a16/{prepared.json,manifest.toml,source.tar.gz}`, the original
guest `/opt/actryn-a16/src` and `/opt/actryn-a16/build`, and all provision logs.
`prepare.py` intentionally still validates revision-1 source; do not rerun it over
the prepared guest or rewrite its old workload pin to conceal this amendment.

Before either pilot, the integration owner archives the signed amendment commit's
`kernel/` and target profile into a **new** `source-amendment2.tar.gz`, retains its
commit/hash alongside the original preparation, and extracts it into the new
guest directory `/opt/actryn-a16/src-amendment2`. Then run only:

```sh
sh /opt/actryn-a16/src-amendment2/kernel/tests/a16/provision-amendment2.sh
```

The script requires the successful original build, checks original and amended
source pins and the exact compiler package, then creates a separate
`/opt/actryn-a16/build-amendment2`. It copies the hash-verified original module,
gateway and authority selftests, builds the corrected workload and its predicate
test, and records separate binary hashes/build IDs and an amendment marker. It
does not install packages, load a module, change a service or execute a pilot.
A failed amendment build is retained and cannot be overwritten. The corrected
host `pilot.py` requires this new build and matching amendment manifest before
using its executables; both original boot modes and pilot result names remain
unchanged because no pilot was executed under revision 1.

Normal/cancel completion now requires Active/Reconciled, SkillFinished/Cancelled
respectively, zero duties, the original grant/operation/stream and runtime nonce,
and both handshaken and grant-authorized flags. A retained terminal-status row
lets the host independently check the state, reason, duties and retained
grant/operation/stream instead of relying on child exit status. The event
format remains revision 1 and its manifest explicitly records `amendment: 2`.

Gateway start and cleanup share a bounded guest `flock`. Cleanup records a closed
fence before stopping/readback, including when the first start reply was lost;
a delayed original SSH command cannot launch after that fence. A prior unit or
closed fence rejects startup. Start is never retried, and a missing cleanup reply
retains failure/uncertainty. Host RED/GREEN tests cover both lost replies and a
delayed start overtaken by cleanup using real subprocesses/locks with temporary
service-command fixtures. These tests and the C terminal-predicate tests qualify
the harness checks only; actual target pilot and comparison remain **NOT_RUN**.
