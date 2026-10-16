# A16 fixed software comparison (revision 1)

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
