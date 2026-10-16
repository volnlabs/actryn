# Diagnostic 8: one cold, admin-only HELLO

This is source preparation, not an A16 benchmark amendment or a successful
handshake claim. Excluded pilot07 remains FAILED: one of ten trials aborted on
PROTOCOL before grant/START/SAMPLE. Its first UART write took 9.915006 ms;
the recorded fault followed 13.436765 ms after entry. Those observations are
consistent with the unchanged 10 ms HELLO guard, but do not identify its failed
predicate or the cause of the long first write.

The new diagnostic derives a distinct test-only module from the exact module16
driver SHA256 `0b63292e70ed1874cfd6cd178bea4178fca33e82970cc20550cf72e535550e28`.
It never overwrites module16, its evidence, any amendment7 input or a campaign
manifest. Its module description identifies diagnostic8. The module name and
serdev compatible remain unchanged, so production and diagnostic variants must
never be loaded together. Neither native compilation nor target execution has
run during this source preparation.

## Fixed observation and authority boundary

Only ADMIN and EVENTS bind requests and exactly one RECOVER are allowed. The
additional request whitelist runs before the urgent closure path. Other ioctls
retain their existing rules, including STATUS; event reads and internal closure,
shutdown and removal still work. No runtime owner can be bound and no grant,
rearm, allocation, START, SAMPLE or repeated RECOVER can be issued. A repeated
eligible RECOVER increments the diagnostic attempt counter, making the record unusable.
The client never tests that rejection by sending a second request.

`hello8.py derive ABSENT_DIRECTORY` checks all five original source hashes before
creating output, emits the new driver/helper/minimal Makefile and exact client
and decoder bytes, and writes `DIFF8.patch` plus `DERIVATION8.json`. The original
HELLO validation expression and `receive_frame` time sample remain verbatim.
Recording runs after the original branch resolves; it recomputes all failed
predicate bits from the same protected frame, `hello_sent` and sampled `now`.
The diagnostic mask never controls acceptance or rejection.

Eight preallocated 208-byte records plus a 64-byte header form one 1,728-byte
snapshot. Overflow saturates an explicit counter and disqualifies completeness.
Recording freezes after the first decision or internal closure, with no reset.
The root-readable, read-only `hello8_snapshot` module parameter exports exactly
3,456 hex characters and one newline (3,457 bytes total). No additional device, debugfs file, allocator,
printk, probe or UART write is added by observation. The original kernel 6.12
[parameter callback contract](https://raw.githubusercontent.com/torvalds/linux/v6.12/include/linux/moduleparam.h)
provides a 4 KiB getter buffer and permits a missing setter. `bin2hex` is declared
in [the matching header](https://raw.githubusercontent.com/torvalds/linux/v6.12/include/linux/hex.h);
its export was verified in retained exact Debian Module.symvers, CRC `0xd45cc6ca`.

| Record | Original timestamps and retained data |
| --- | --- |
| BEGIN | Original `do_request` sample for the one permitted RECOVER attempt. |
| TX | Original `transmit_at` sample and `hello_sent`, requested immutable bytes, offset and return count. A separately labeled new post-write timestamp is observational only. |
| RX | Existing `parser_started` and existing delimiter-age sample, raw bounded COBS bytes, decode result and capacity/age flags. The existing sample is assigned to a local without replacing its value or changing short-circuit evaluation. |
| PROCESS | Original `receive_frame` sample, original `hello_sent`, exact decoded frame, RX queue record ID and outer HELLO matching-predicate mismatch bits. |
| DECISION | Same processing sample and frame, original send timestamp, accepted/rejected branch and all failed validation bits. |
| CLOSE | Original closure rank/reason and a new observational capture timestamp; no claim that this is the original decision timestamp. |

Decision bits 0–12 are status != 1, zero boot, zero session, zero device,
nonzero grant, operation, stream, sequence, expiry, left, right, context,
and unsigned `now - hello_sent > 10 ms`. PROCESS mismatch bits 0–4 are
non-HELLO_ACK, not awaiting, awaited kind not HELLO, transaction mismatch and
nonce mismatch. Raw parser bytes remain separate from re-packed decoded fields.
Host decoding verifies CRC/COBS, exact RX/processing/decision correspondence,
HELLO identity, the mask and the original unsigned clock arithmetic.

## Native compile and freeze proposal — not executed

1. Root reviews the generated source diff and host test evidence. Create a new
   source archive and input manifest containing the derived tree, this plan and
   exact commands. Existing build directories and archives remain untouched.
2. In a separately authorized dedicated A16 build boot, require hostname
   `actryn-a16`, ARM64, kernel `6.12.111+deb13-arm64`, the exact installed Debian
   GCC `14.2.0-19`, make `4.4.1-2`, and headers/common `6.12.111-1`. No installs.
   Recheck config SHA256
   `0f442d89365ea22dc5169463634ee62903925200844558479666cbe3eeb7e555`
   and Module.symvers SHA256
   `42fe7f2b8e33b9f95bf259092f437bf2a5927e231c07ea6e90869a7d2ac0b35d`.
3. Extract only after absent-directory and archive-member guards, into new
   `/root/actryn-hello8-build01/source`. Execute once, with one compiler job:
   `make -C /lib/modules/6.12.111+deb13-arm64/build M=/root/actryn-hello8-build01/source -j1 modules`.
   Bound the build at 120 seconds; retain stdout, stderr, exit, source hashes,
   packages/compiler, config, symvers, module SHA256, GNU note bytes and build ID.
   Any failure consumes build01; fixes need a separately recorded build attempt.
4. Retrieve and independently verify the evidence. Freeze the actual diagnostic
   module and client/decoder hashes before any deployment. There is no pending
   placeholder that a launcher may silently fill. This document authorizes no
   target execution by itself.

## One target case and cleanup proposal — not executed

Use a fresh, separately numbered protected A16 boot on the preserved dedicated
disk, with the same pinned kernel/initrd/DT, fixture binary and retained state, two CPUs and software
limits. Root records the actual new PID, start ticks, invocation and boot UUID;
no future identity is assumed. Require at least 4 GiB MemAvailable, the same
TasksMax 256 / MemoryMax 3 GiB host launcher, absent new output paths, no other
timed campaign, authority client, loaded authority/capture module, enabled probes
or raw ttyAMA1. Preserve all prior failed boot/pilot records. Do not reset the
fixture or warm up the HELLO path. Record its current identity/disabled queue
state; an incompatible state is a setup failure, not permission to mutate it.

At resumption, root reported a new host boot and absent Actryn fixture/VM units.
Previous process IDs and invocations are historical. Before any target case,
root must separately record restoration of the dedicated fixture from retained
state, its executable/state hashes and new lifetime identities. That prerequisite
is not a silent reset or authority to reuse an earlier launch record.

Stage frozen bytes to new `/opt/actryn-a16/hello8`, then one `insmod` of its
`actryn_authority.ko`. Check the loaded GNU note against the frozen binary and
require the unconsumed diagnostic header. Issue exactly one client command:

```text
timeout --signal=TERM --kill-after=2s 10s python3 -B /opt/actryn-a16/hello8/hello8_client.py /var/tmp/actryn-hello8-case01 ACTUAL_BOOT_ID FROZEN_MODULE_SHA256 FROZEN_LOADED_NOTE_SHA256
```

These three literals must come from retained observation/freeze evidence, never
guesses. The client checks identity and module hashes, exclusively creates its
output, binds ADMIN/EVENTS and saves the intent before one RECOVER. It reads at
most 128 events for two seconds, with an eight-second process alarm and no
snapshot/status formatting loop during HELLO. It exports raw events, statuses,
snapshot and assessment before closing both FDs. Exit zero means a complete
diagnostic observation, which can explicitly be REJECTED_ACK or OTHER_CLOSURE;
it is not handshake success. Success also requires a known zero RECOVER result,
complete before/after and event statuses with version 1 and zero reserved fields,
zero cumulative `events_lost` throughout, and contiguous event sequences starting
at 1. A terminal snapshot cannot hide `RETURNED_ERROR`, `OUTCOME_UNKNOWN` or
`NOT_ISSUED`; those outcomes and errno/exception remain explicit and cause nonzero
exit even when the diagnostic snapshot is otherwise complete.
An existing output path, unknown ioctl outcome, loss, timeout or error consumes
the case. There is no automatic retry.

Retrieve and hash all raw output before teardown. Read back no outstanding
authority/operation/TX/await, disabled fixture output and empty queue; preserve
nonce/controller/status identity, including any fault. Verify no client or open
authority FDs remain and retain final kernel log/module identity. Then one normal
`rmmod actryn_authority` may remove only the exact diagnostic binary, followed by
module/device absence checks and disabled-fixture readback. Never force unload,
rebind, reset, RECOVER again or substitute module16 during cleanup. If unload or
closure is uncertain, retain the guest and report it. Otherwise a separately
guarded graceful poweroff preserves the disk and releases the window.

The added recording changes code layout, execution cost and synchronization.
The admin-only client also differs from pilot07. A reproduced mask identifies
this diagnostic case's predicate only; a passing case is a non-reproduction.
Neither proves why uninstrumented pilot07 failed, measures its instrumentation
overhead, permits a silent warm-up, widens a deadline, nor qualifies comparison
or physical behavior. Any further source or experiment change needs a new
numbered decision after this one retained case.
