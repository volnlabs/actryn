# Common UART diagnostic for the fixed A16 matrix

`uart_trace.py` replaces the driver-only `arm_trace.sh` for A16 diagnostic
visibility. The same two probes, fetch arguments, clock, buffers and metadata
apply to both protected and userspace arms. Target execution is NOT_RUN when this
source is committed. Host fake-tracefs tests establish guard/cleanup behavior;
they do not qualify target probe installation or event completeness.

## Verified source boundary

The exact upstream Linux v6.12.111 sources show one shared function:

```c
static ssize_t uart_write(struct tty_struct *tty, const u8 *buf, size_t count)
```

[`serial_core.c`](https://raw.githubusercontent.com/gregkh/linux/v6.12.111/drivers/tty/serial/serial_core.c)
defines it at line 577 and assigns it to `uart_ops.write` at line 2585.
The protected path calls `serdev_device_write_buf`, whose controller callback
reaches [`serdev-ttyport.c`'s `ttyport_write_buf`](https://raw.githubusercontent.com/gregkh/linux/v6.12.111/drivers/tty/serdev/serdev-ttyport.c)
and invokes `tty->ops->write` (line 70). The raw baseline's configured raw-mode
TTY goes through [`N_TTY` write](https://raw.githubusercontent.com/gregkh/linux/v6.12.111/drivers/tty/n_tty.c)
to that same callback (line 2274). This is a serial-core software enqueue path,
not a physical UART delivery or controller acceptance boundary. The exact Debian
patch delta has not been independently re-extracted for this trace source check.

The [same kernel's kprobe event documentation](https://raw.githubusercontent.com/gregkh/linux/v6.12.111/Documentation/trace/kprobetrace.rst)
defines `$argN` entry fetches, `$retval` return fetches, explicit return-probe
`MAXACTIVE`, and hit/miss counters in `kprobe_profile`. The scalar pointer,
`size_t` and `ssize_t` signature on this AArch64 target supports the following
generic fetch syntax without guessed register numbers or struct offsets:

```text
p:actryn_a16_uart/enter uart_write tty=$arg1:x64 buffer=$arg2:x64 count=$arg3:u64
r64:actryn_a16_uart/leave uart_write result=$retval:s64
```

The helper captures pointer values and counts only. It does not dereference the
buffer, associate return events with complete immutable commands, identify a
controller receipt, or select only ttyAMA1. Other UART traffic can appear. Each
state/result explicitly records `dispatch: NOT_RUN`, `frame_correlation: false`
and no timing claim. Do not substitute these call intervals, ioctl latency,
aggregated enqueue bytes, or apparent trace maxima for complete-frame dispatch,
authority latency, physical qualification or WCET.

## Fixed controls and execution

Only root on hostname `actryn-a16`, AArch64 QEMU virt, exact kernel
`6.12.111+deb13-arm64`, pinned kernel config and CPUs 0–1 is accepted. Tracefs must
already be mounted, with `nop`, all events disabled, no dynamic probes, empty
event PID filters, both CPUs included, and no pre-existing trace records. The
helper never installs packages, mounts tracefs or removes foreign probes.

Each diagnostic block uses a fresh alphanumeric label and an already reviewed
bounded workload. The integration runner must call stop in its cleanup path
even if the workload fails:

```sh
python3 uart_trace.py start /var/tmp/actryn-a16-trace-block01
# Run exactly the separately frozen bounded diagnostic workload once.
python3 uart_trace.py stop /var/tmp/actryn-a16-trace-block01
```

Start durably saves boot ID, original clock/buffer/tracing controls, options,
probe definitions and this script's SHA256 before changing tracefs. It selects
`boot` clock, 256 KiB per CPU (512 KiB total), two probes, and return MAXACTIVE 64.
No trace consumer drains the buffer during the block. Export is a bounded 16 MiB
text read, not an unbounded `trace_pipe` stream. Buffer overwrite or kretprobe
misses are possible and must remain in the denominator.

Stop disables tracing, retains `trace.txt`, both per-CPU statistics and raw
`kprobe-profile.txt`, then removes its own probes and restores the original
clock, uniform buffer size and tracing state. Failed raw export still attempts
both stats exports and restoration. Exceptions and restoration failures produce
`failure.json`; normal completion produces `result.json`. Wrong-boot or foreign
probe detection rejects control changes. The helper does not retry or overwrite
an ended attempt. SIGKILL/power loss cannot guarantee cleanup; preserved
`state.json` is recovery evidence, and an interrupted trace is not a valid block.

Successful stop means capture/restoration completed, not loss-free evidence.
The review must inspect every CPU's overrun/commit-overrun/dropped count and each
probe's hit/miss count. Missing counters, no expected probe hits, positive loss,
unexpected events, failed restoration, or a changed script/config block any
lossless diagnostic claim. Preserve the entire directory and script hash with
the arm/block evidence. Diagnostic overhead is unmatched to an untraced run and
must be reported separately from the mandatory-evidence matrix. A comparison
still cannot report dispatch measurements until an independently qualified
complete-frame correlation mechanism exists.
