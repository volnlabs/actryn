# Instrumentation amendment 4: complete-frame software dispatch

This is a test-only capture module and independent decoder for the frozen A16
software comparison. It changes no authority driver, baseline, workload, limit
or controller behavior. The four ABBA boots and eight ordered runs remain fixed:
kernel untraced/traced, userspace untraced/traced, userspace untraced/traced,
kernel untraced/traced. The traced modes use this module alone. Do not also
enable `uart_trace.py`'s pointer/count probes; that would change their overhead.
Those earlier probes remain an optional separately labeled diagnostic.

The normative architecture asks for admission/dispatch latency separately.
Here admission-call duration remains the existing before/after request interval.
The added estimand is **external request-call entry to the return boundary where
Linux has accepted the complete immutable frame**, matched by full identity.
`uart_write` copies bytes into the serial transmit FIFO before returning, so the
return timestamp is an observed upper boundary on that acceptance. It does not
measure the exact internal authorization instant, FIFO drain, UART delivery,
controller receipt or physical response. Dispatch can precede the request call's
return; that is recorded explicitly rather than creating a negative latency.

## Common source point and lifetime

[Linux v6.12.111 `uart_write`](https://raw.githubusercontent.com/gregkh/linux/v6.12.111/drivers/tty/serial/serial_core.c)
has signature `ssize_t (struct tty_struct *, const u8 *, size_t)` and copies from
its input synchronously into `state->port.xmit_fifo` before returning the accepted
byte count (lines 577–601). Both the protected serdev callback and baseline's
raw TTY write reach this same function; see [the common path review](UART_TRACE.md).
The authority driver advances/replaces its immutable transmit buffer only after
`serdev_device_write_buf` returns. The raw TTY path retains its kernel write
buffer through the synchronous callback. The kretprobe runs before either caller
resumes, so copying the accepted prefix there precedes caller reuse. This depends
on the reviewed trusted writers; it is not a hostile-kernel lifetime guarantee.

The filter uses the exact compiled `tty_struct` fields: index 1, name `ttyAMA1`,
and driver name `ttyAMA`. [The PL011 driver](https://raw.githubusercontent.com/gregkh/linux/v6.12.111/drivers/tty/serial/amba-pl011.c)
defines both driver/device names as `ttyAMA` (lines 2476–2483). Entry arguments
come from ARM64's [documented kernel register helpers](https://raw.githubusercontent.com/gregkh/linux/v6.12.111/arch/arm64/include/asm/ptrace.h)
using zero-based argument numbers, not guessed offsets or assembly registers.
Only positive accepted bytes are read with
[`copy_from_kernel_nofault`](https://raw.githubusercontent.com/gregkh/linux/v6.12.111/mm/maccess.c).
No negative/zero return, over-cap request, invalid return larger than the request,
or failed read supplies an accepted fragment. No memory past the original count
is copied. UART functions with other names/indices are excluded before copying.

Registration/unregistration and no-fault copy are GPL exports in both the exact
source and the **actual Debian ARM header `Module.symvers`** retained by build04.
[Unregistration](https://raw.githubusercontent.com/gregkh/linux/v6.12.111/kernel/kprobes.c)
removes callbacks and synchronizes RCU before export. A function still in flight
can lose its return callback during unregistration; its nonzero `inflight` count
therefore invalidates completeness rather than being silently subtracted.

## Bounded mechanism and file format

The module has no parameters, hot-path allocation, storage I/O, controller write,
request modification or output authority. A preallocated array holds exactly
4,096 records of 256 bytes (1 MiB). MAXACTIVE is 64. Entry retains original
pointer/count/TTY and CLOCK_BOOTTIME time; return captures its own time and up to
158 accepted bytes. Overlapping selected calls increment a concurrency counter;
they invalidate reconstruction because return order need not be FIFO order.
All `kretprobe.nmissed` events, including possible other-UART calls before the
filter, conservatively invalidate complete evidence.

Only the named A16 ARM guest, exact kernel and QEMU virt can initialize it. The
root-only `/dev/actryn-a16-capture` exposes one operation: ioctl `0x5541` freezes
capture by unregistering the probe. Reads before freeze return EBUSY. Afterward
the immutable header and records can be read; reset/rearm is unavailable. Open
file references pin the module. Each traced run loads a fresh module and exports
then unloads it; there is no forced unload.

All fields are little-endian; reserved bytes must remain zero:

| Structure | Fields in order |
|---|---|
| 128-byte header | 8-byte `A16UART4`; u32 version=4, record size=256, capacity=4096, retained count; u64 started/stopped boottime; u64 selected entries, returns, dropped records, over-cap calls, failed reads, invalid returns, concurrent entries, global missed returns, in-flight calls; 16 reserved bytes |
| 256-byte record | u64 sequence, entry time, return time, TTY pointer, original buffer pointer, original count; s64 return; u32 TID, CPU, flags, copied count; 158 data bytes; 26 reserved bytes |

Flags are over-cap=1, invalid return=2, negative write result=4, failed copy=8.
Zero/error writes remain records with zero copied bytes. Pointer values are
diagnostic evidence, not actor identity. The global counters and every sequence,
timestamp, TTY, count, padding and byte boundary are checked by `dispatch.py`.
Any loss, unknown read, capacity violation, missed/in-flight return, concurrent
writer, malformed/unfinished frame, changed duplicate or reversed time rejects
capture completeness. Exact duplicate frames and repeated request identities
remain ambiguous, never selected by earliest/fastest timestamp.

The independent Python decoder reconstructs only positive accepted fragments,
handles delimiter-only resynchronization, validates fixed 156-byte COBS/CRC32
commands and complete epoch/operation/sample identity, and matches the original
192-byte request plus handshake epoch from raw 216-byte events. Absolute sample
or START deadline equality censors the candidate. Every issued request remains
in the cohort counts; failed dispatch calls and non-dispatch calls are reported
separately from successful eligible and matched calls. All raw frames and all
ambiguous/unmatched requests remain visible. An automatic owner-loss QUIESCE may
have no user request; it is retained without inventing a request-entry time.

## Build04 provenance and pilot gate

Exact compile-only evidence lives at
`.cache/qemu/a16/instrumentation4-build04/`. Source archive SHA256 is
`9033207e98b5d6c7facceea5ec3a2b570d21b00a6f540de9f23f1e5998d473ca`;
evidence archive SHA256 is
`6a56ae4481b162c89333f8e3785012fee011eac4ccece9342c8670c590d7e15d`.
It records Debian kernel/header/common packages `6.12.111-1`, GCC `14.2.0-19`,
make `4.4.1-2`, exact config, source/module hashes, symbol exports, modinfo and
GNU build ID. Module SHA256 is
`535b1e5c653993a7a1ba716da9d569501875198a668ac94747bf119c95805bc8`.
Only compilation ran in the original ARM preview guest: no module load, service
or runtime mutation. The host 7.2.5 compile is explicitly NONRELEASE evidence.

The integration owner copies the frozen amendment's source files (preserving
their relative paths), `instrumentation4.toml`, and that exact ARM `.ko` into
new `/opt/actryn-a16/instrumentation4/` on the dedicated A16 guest. Do not overwrite
the original or amendment-2 builds. `capture_guest.py` checks source/module hashes,
the pinned kernel/config/hostname/CPUs and idle tracefs before loading. A caller
must serialize/fence start and cleanup commands so a delayed remote start cannot
outlive retirement. Stop exports bounded raw data and unloads even if export
fails; a failed start remains failed after cleanup.

Before any frozen comparison run, retain separately numbered **kernel and
userspace instrumentation pilots** using the unchanged ten-trial workload. Each
must pass workload correctness, actual probe/filter installation, complete raw
capture with zero loss/concurrency/missed/in-flight counts, all successful
eligible request correlations, and unload/cleanup. Verify decoder/golden-vector
and every-fragment split tests before these target pilots. Failures block the
matrix; do not retry, alter limits, filter failed trials or rewrite the pins.

At source freeze these target pilots and all eight comparison runs are NOT_RUN.
Even after they pass, measurements remain descriptive software results under
QEMU scheduling. They establish no physical response, WCET, superiority or
equivalence of the two authority mechanisms.
