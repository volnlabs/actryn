# Actryn software-fixture authority module

This GPL-2.0-only loadable module owns the second QEMU PL011 through serdev.
It accepts copied typed wheel commands through the [fixed UAPI](UAPI.md), never
raw bytes. Probe requires both `actryn,fixture-v2` and the QEMU
`linux,dummy-virt` machine. It is not a physical robot target.

Build with the exact installed kernel headers:

```sh
make -C kernel KDIR=/lib/modules/6.12.111+deb13-arm64/build
cc -std=c11 -Wall -Wextra -Werror kernel/tests/authority_selftest.c -o authority-selftest
```

The target package supplies a device-tree child under the second nonsecure
PL011 (`/pl011@9040000` in the pinned QEMU 11.1.1 machine):

```dts
authority {
    compatible = "actryn,fixture-v2";
};
```

Use the first PL011 for the console. Serdev enumeration suppresses the second
TTY cdev; installation must verify its absence. In the disposable ARM64 guest,
load `kernel/actryn_authority.ko` and run `./authority-selftest` as root against
a fresh inhibited external fixture. Never load this target module on the host.
The selftest leaves authority faulted/closed when its registered owner exits.
Subsequent runs require ordinary module unload/reload and fixture restart.

## Synchronization and lifetime

The authority mutex orders admission, lifecycle and each asynchronous prefix
write. Urgent closes first publish to one preallocated monotonic control slot,
then acquire the mutex directly. The first normal close reason wins; stronger
grant/fault/detach closure dominates; stale revision clearing cannot erase a
newer request. The write-wakeup callback may run inline under the UART lock and
only schedules work. RX uses bounded parsing and a separate fixed queue.

One immutable started frame and one replaceable unsent sample are retained.
Cancellation drops unsent work, finishes only the exact old suffix within the
original host/controller cutoff and recovery limit, then sends a new barrier.
Samples wait for actual applied receipts; operation occupancy survives local
close until the matching timely quiescence receipt. Expiry/fault never become
success when a late receipt arrives. Faulted transport does not claim delivery;
the independent fixture expiry is the remaining response.
One administrator recovery after a partial-frame fault waits for the immutable
old host cutoff, emits a delimiter to retire the abandoned COBS prefix, then
sends HELLO. This can never extend the old sample's horizon. Recovery stays
inhibited until an explicit rearm and new authorization.
During that fresh, authority-free handshake only, malformed incoming prefixes
are discarded through their delimiter within the unchanged absolute HELLO
timeout. A validated reply carrying the fresh nonce ends this synchronization
phase. RX capacity stays strict, and malformed traffic after mapping still
faults. This handles retained UART bytes when a new attachment starts inside
an old observation; the fixture also delimits its fresh HELLO reply.
An observed higher boot counter or higher session in the same boot from the
paired device closes current authority as a transport fault. Older epochs and
foreign nonces cannot refresh, acknowledge or reconcile current work.

The owner is the referenced original leader, credential object and exec ID.
Inherited/transferred descriptors do not gain authority. Binding and open-file
references retain endpoint state. Remove marks it detached, prevents new worker
scheduling, joins work, closes the UART and drops the binding reference; old
FDs remain queryable and cannot adopt a replacement device. Active suspend is
refused; resume faults and requires recovery/rearm. Module force-unload is not
supported.

The Linux 6.12 source path inspected for this design is
[serdev-ttyport](https://raw.githubusercontent.com/torvalds/linux/v6.12/drivers/tty/serdev/serdev-ttyport.c),
[serial_core](https://raw.githubusercontent.com/torvalds/linux/v6.12/drivers/tty/serial/serial_core.c),
[PL011](https://raw.githubusercontent.com/torvalds/linux/v6.12/drivers/tty/serial/amba-pl011.c)
and the TTY buffer consumer lock. Serdev open retains its runtime-PM reference;
PL011 close shuts down/free-joins IRQs and TTY flush joins the receive consumer.
This source review is not a sanitizer, race or latency qualification.

## Verification and remaining gates

`make -C kernel test` runs host ASan/UBSan assertions for ABI sizes, CRC/COBS,
truncation/corruption, expiry equality, bounded slew, and urgent-slot precedence.
An independent Python `struct`/`zlib` encoder checks the complete golden frame.
LeakSanitizer is disabled because this environment runs under ptrace; these
stack-only tests retain address/undefined-behavior sanitizers.

The guest selftest uses the actual ioctl/serdev/controller path for two normal
operations under one grant, allocation-before-start, allocated cancellation,
stale START rejection, immutable duplicates, forked-FD denial, actual exec
denial, malformed requests and expiry. It is software evidence only.
It also rejects reactivation after grant revocation and sample horizons that
would outlive recorder health or the observation's maximum age.

On a kernel built with `CONFIG_KUNIT=y`, build with
`CONFIG_ACTRYN_AUTHORITY_KUNIT_TEST=m`. Codec/control tests and the actual driver
transmit/close path then test every encoded byte offset with an injected serdev
writer. Snapshot 13 passed fourteen cases in each of four separate x86 diagnostic
kernels: plain KUnit, lockdep, KASAN and KCSAN. [Campaign evidence](DIAGNOSTICS.md)
records exact source identities and preserved earlier failures. Both suites are compiled into the
authority component only for that diagnostic build; the normal profile omits them.
The tests additionally cover every fault/recovery byte offset, including a
missing final delimiter, and reject applied/quiescence receipts past their
fresh deadlines. The recovery test supplies deterministic time snapshots to
the production transmit implementation; it makes no scheduling-bound claim.
The receive tests cover retained incomplete incoming frames, bounded fresh
handshake synchronization, strict post-mapping parsing and stale ACK rejection.
Older epochs cannot acknowledge current work. Newer controller epochs
close authority. RX-capacity/counter tests and direct PM callback tests exercise
bounded storage, nonwrapping accounting and inhibition.

The separate [actual ARM64 regressions](tests/ADVERSARIAL.md) exercise the
installed module through real ioctl/serdev/PL011 paths. Their software results
do not establish exhaustive concurrent lifecycle/teardown stress, actual
platform PM behavior, or a software latency bound. All physical limits and
physical qualification remain outside this target.
