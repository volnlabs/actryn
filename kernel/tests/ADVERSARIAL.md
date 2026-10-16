# Actual guest regressions

Snapshot 15's single labeled ARM64 verification ran `selftest` and
`ready-recovery`; both passed without a retry. The latter retained controller
boot 77 and advanced session 1 to 2. Its exact module SHA-256 is
`2405de617a09b4b3beec5eaec8f83ff6ee6c0cc0a1968d091b0c5634fcff8e1e`.
The evidence archive SHA-256 is
`78f651edfac6b1bb8c64853542ddd315644cae7ce32dee5a2d665d7fd0ec7741`.
It includes the build log, per-case output and kernel logs, fixture state,
guest boot identity and a clean handoff (no diagnostic probes, local trace
clock, daemon services stopped, no second raw TTY). This bounded verification
does not turn the incomplete snapshot 14 wider campaign into a pass.

Before this fix, a separate module-14 admin-only exchange was instrumented:
the valid HELLO_ACK reached decoding about 3.47 ms after HELLO send, the worker
receipt snapshot was 3.591615 ms after send, and mapping succeeded. That trace
is retained in the same archive and is explicitly a **non-reproduction** of
the earlier manager handshake failure. The deterministic worker-wakeup RED/GREEN
test described in [diagnostics](../DIAGNOSTICS.md) proves a source race; the
unchanged ten-ms clock-exchange guard still applies. No measured timing bound
or universal explanation for handshake failures follows from these tests.

These tests require the exact Debian `6.12.111+deb13-arm64` QEMU guest and
external non-actuating fixture. The harness checks kernel, architecture, root
and device-tree machine identity before opening authority. It never loads a
module. Compile in the guest:

```sh
cc -std=c11 -Wall -Wextra -Werror kernel/tests/authority_adversarial.c -o authority-adversarial
```

Start each scenario with a fresh inhibited fixture and ordinarily unloaded/
reloaded module. Do not force unload. Each binary invocation has a 20-second
alarm and emits a PASS line only after its assertions complete:

```sh
./authority-adversarial dup
./authority-adversarial inhibited-revoke
./authority-adversarial rights
./authority-adversarial ready-recovery
./authority-adversarial owner-exit
./authority-adversarial unbind-rebind serial0-0
./authority-adversarial event-capacity
```

`dup` keeps the owner alive while one duplicate closes, then tests final runtime
file-description release. `inhibited-revoke` verifies that revoking absent grant
authority cannot bypass inhibited baseline reconciliation. `rights` transfers the file through a Unix socket to
a different process and checks command denial. `owner-exit` keeps that same
file description open in the parent after its registered owner exits, requiring
UNKNOWN plus owner-loss closure. `unbind-rebind` detaches an active endpoint
while its descriptors remain open, checks they stay detached after a replacement
probe, and verifies that replacement begins inhibited. `event-capacity` stops
consuming evidence, fills the bounded queue and requires evidence-loss closure
with uncertain operation state. It does not simulate RX-queue or physical FIFO
exhaustion.

`ready-recovery` runs two manager lifetimes without resetting the fixture or
unloading the module between them. The second handshake must retain the
controller boot identity, advance its session and use a fresh runtime nonce.
Both lifetimes explicitly rearm and authorize before activation.

Six additional scenarios synchronize with the fixture's existing private
admin socket. Run the bridge on the host that owns that socket, passing the
actual SSH invocation and guest command after `--`. For example:

```sh
python3 kernel/tests/fixture_bridge.py --admin /absolute/path/fixture.admin -- \
  ssh -i /absolute/path/guest-key -p 26221 root@127.0.0.1 \
  /root/authority-adversarial late-sample
```

Repeat with a fresh fixture/module for `late-barrier`, `delayed-handoff` and
`controller-restart`, `repeated-revoke` and `cancel-revoke`. The bridge accepts only the five fixed delay/replay/restart instructions emitted by
these tests and acknowledges each fixture command before the guest proceeds.
`late-sample` delays the applied receipt beyond the sample cutoff. `late-barrier`
delays quiescence beyond operation expiry. Both require UNKNOWN to survive the
late receipt and a replay. `delayed-handoff` rejects the next allocation while
the first completion barrier is delayed, then admits it after reconciliation.
`controller-restart` advances the fixture's durable boot identity during an
operation, sends a zero-duty sample under the old epoch, and requires a
transport fault with UNKNOWN before the generic missing-receipt timeout. It
checks that the old operation identity remains preserved and replay cannot
revive it. Its 500 ms observation window is a test timeout, not a latency bound.
`repeated-revoke` delays a closure receipt by 250 ms, revokes repeatedly while
that receipt is pending, and requires one unchanged QUIESCE transaction to
reconcile. `cancel-revoke` adds escalation from operation cancellation to grant
revocation. Both require revoked authority to stay revoked after receipt replay.

Retain each scenario's stdout/stderr, exit status, exact source/module hashes,
fixture identity and kernel log. Compilation is not a runtime pass. These
scenarios do not establish physical qualification, a timing bound, suspend/
resume behavior, forced unload safety, or immunity to all lifetime races.

The host-side `run_guest_campaign.py` automates a labeled campaign against the
disposable guest, refuses active daemon services, ordinarily unloads/reloads
the chosen guest module and resets the non-actuating fixture between cases.
It preserves each case's output, fixture identity, kernel log and exit status,
stops at failure, and never overwrites an earlier output directory. For example:

```sh
python3 kernel/tests/run_guest_campaign.py \
  --identity /absolute/path/guest-key --known-hosts /absolute/path/known_hosts \
  --admin /absolute/path/fixture.admin --build /root/actryn-kernel-build12 \
  --output /absolute/path/new-campaign selftest dup rights owner-exit \
  unbind-rebind event-capacity late-sample late-barrier delayed-handoff controller-restart
```

Coordinate a quiet host build window before running handshake-sensitive tests.
Any interruption stays labeled as such; completed functional checks do not
turn an interrupted campaign into an overall pass.

Optional `--trace` enables guest-only kprobes in the actual receive/decode
path. The helper records bounded frame prefixes, lengths and transport/protocol-fault
stack traces, then removes its probes and triggers. These instrumented runs
are diagnosis, never latency measurements. Trace setup requires an idle `nop`
tracer with no existing kprobes; preserve tracing failures separately from
driver failures.

## Recorded snapshot 13 results

The clean ARM64 build and all twelve scenarios above passed on
`6.12.111+deb13-arm64`, guest boot
`5a7d94ab-b572-4a54-90f7-388669c10b2b`. The module SHA-256 was
`649929882cb7bf5b00ec6b952f2df55822c4c425efb1bed74c89de5ab06fe921`;
the external fixture executable SHA-256 was
`3684e5f2a5b848ac779336fb4dc1c087413c92d5fb11e63f39e1c72c7007e398`.
The fixture includes the known-disabled READY handshake and explicit reply
delimiter fixes. Actual READY recovery retained boot 53 while advancing its
session from 1 to 2, without resetting the fixture or reloading the module
between the two lifetimes.

A separate, bounded six-reload diagnostic also passed all six cases. Its third
case captured a 156-byte truncated old observation and decoder rejection,
followed by a valid fresh ACK and successful scenario completion. Earlier
snapshot 12 diagnostic 07 captured the same malformed frame causing immediate
protocol closure before the valid ACK. These are actual PL011 RED/GREEN traces;
the KUnit tests separately verify strict malformed-frame faults after mapping.
No warning, panic or sanitizer diagnostic pattern appeared in these actual
guest kernel logs. The stock guest does not enable the separate diagnostic
sanitizer configurations.

The evidence archive `actryn-kernel13-arm-evidence.tar.gz` has SHA-256
`852d32977aee2b2736cab3343cd5fb02fe8ffc2148a7b275b63889690f9557f9`.
It retains exact build/source hashes, guest boot records, fixture identities,
outputs, exit statuses, traces and kernel logs. It also preserves snapshot 12's
interrupted campaign 02, failed campaign 03, trace-cleanup failure 04,
successful diagnostic 05 and failed diagnostic 06/07 attempts. The cleanup
failure was in the tracing harness: attached stacktrace triggers had to be
removed before deleting kprobe events. None of these earlier attempts is
relabeled as passing by the snapshot 13 results.

## Recorded snapshot 14 results

Snapshot 14 fixes a separately observed duplicate-revocation failure. Manager
guest06 recorded closure at transaction 18, another closure at 19, then a
transport fault at 20 only 7.333330 ms after the first closure. Source inspection
showed that the urgent publication and mutex side of one REVOKE ioctl could
both apply grant closure, discard an awaited QUIESCE receipt and allocate a new
barrier transaction. A separate actual ARM RED run with the unchanged snapshot
13 module reproduced the failure. Its trace captured QUIESCED followed by
AW_FAULT with Stale status and transport closure, distinguishing that path from
a missing-receipt timeout. The fixture's exact-duplicate rule remains unchanged.

The clean snapshot 14 ARM64 build has module SHA-256
`9bb5a8150172f5750eda6e07b56c44ff569bcaeb78f9c736e114b12ae5ce44cf`.
Both new cases passed, retaining QUIESCE transaction 4 through repeated revoke
and cancellation-to-revocation escalation. The full selftest and inhibited-revoke
case also passed. Campaign 01 then stopped at a `dup` handshake setup failure:
PROTOCOL, no established controller epoch, request-to-closure interval
11.11 ms. That interval is consistent with the unchanged 10 ms HELLO exchange
guard, but the untraced attempt does not establish its precise cause. The actual
duplicate-FD assertions were not reached in that attempt.

Separately labeled diagnostic continuation 02 passed eight cases: dup, rights,
owner-exit, unbind-rebind, event-capacity, late-sample, late-barrier and
delayed-handoff. It then stopped when controller-restart's SAMPLE ioctl returned
EINVAL after the fixture restart acknowledgment. That test did not reach its
reset-closure assertion; the original harness lacked a request-time status
snapshot, so the failing admission predicate is unresolved. Ready-recovery did
not run in snapshot 14. No more continuation or deadline widening was used.
The narrow closure fix has actual RED/GREEN evidence; the wider snapshot 14
campaign is incomplete and is not an overall acceptance pass.

Guest boot remained `5a7d94ab-b572-4a54-90f7-388669c10b2b`; the same fixture
executable used for snapshot 13 remained installed. Services stayed stopped and
manager persistence was untouched. No kernel warning/panic diagnostic pattern
appeared in the recorded stock ARM logs. The evidence archive
`actryn-kernel14-arm-evidence.tar.gz` has SHA-256
`cc257b9feced57a11eeeacac130ff2499b553fa069b38bfaa250f530b5da40e4`.
It preserves the RED trace, both subsequent campaign failures and successes,
exact source/build identities and a separately labeled post-campaign host
resource snapshot; that late snapshot does not establish conditions at failure.
