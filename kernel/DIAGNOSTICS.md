# Separate diagnostic kernel campaigns

The separate x86 campaigns below have run against authenticated Debian source
`6.12.111-1` with GCC 14. The stock Debian ARM64 module selftest is separate
evidence; diagnostic KUnit does not exercise the physical PL011 lifetime path.

| Snapshot | Campaign result |
| --- | --- |
| 07 | Plain, lockdep, KASAN and KCSAN passed seven cases each. |
| 11 | Plain, lockdep and KASAN passed eight cases. KCSAN produced only seven; the eight-case validator rejected its reused object. This failed attempt is retained. |
| 11b | Separate KCSAN amendment passed eight cases after changing source timestamps, with source bytes verified unchanged. |
| 12-red | Thirteen cases ran; only `new_controller_epoch` failed, preserving the missing reset-closure regression. |
| 12 | Plain, lockdep, KASAN and KCSAN passed thirteen cases each after the narrow controller-epoch fix. |
| 13-red | Fourteen cases ran; only `handshake_rx_sync` failed on the captured truncated-observation sequence. |
| 13 | Plain, lockdep, KASAN and KCSAN passed fourteen cases each with bounded handshake synchronization. |
| 14-red | Fifteen cases ran; only `grant_closure_idempotence` failed, with replaced barrier bytes/transaction and lost receipt wait. |
| 14 | Plain, lockdep, KASAN and KCSAN passed fifteen cases each, retaining the original barrier across grant closure. |

Snapshot 12 records are retained in the disposable server guest under
`/var/tmp/actryn-diag-12`; its RED evidence is under `actryn-diag-12-red`.
The exported evidence archive SHA-256 is
`250e0b0a063a96d543348be04518cf3c7e7e14dea5f668f7f7298e15908ed7be`.
The production `actryn_driver.c` SHA-256 is
`ea754c85df4177db9fa1ed1eaae89006bf7c2738232919f14b0a5610d5ae846f`;
the diagnostic driver-test header SHA-256 is
`2f356076c9054452e3e39dafab19e8d594fc635f7d228bb0bdd7840f7174798d`.
Logs, JSON, generated configurations, commands, source hashes and binary hashes
are retained; the guest also retains the binaries. The plain build emits six
objtool unreachable-instruction warnings, also present in snapshots 07 and 11.
The successful runs contain no tested kernel warning, panic, sanitizer or
locking-diagnostic pattern. These results do not erase earlier failed attempts.

Snapshot 13 records remain under `/var/tmp/actryn-diag-13`, with its RED run in
`actryn-diag-13-red`. Exported evidence archive SHA-256:
`9f8a37fa0200deb839d60c04a78ab9e8c442c857ae0970d5e79be3d3ba6f815c`.
Its production driver SHA-256 is
`70322c539c6b80617fd754f94bcdc7c0f3123217d0c10ddeb3b1c4a54d5ae168`;
its driver-test header SHA-256 is
`cac2f9f452fb70c4a0cfe6fd65ba62c7c95e69f063d2626571a3e2f0744e61cb`.
The new test preserves inhibition across a truncated old observation followed
by a valid fresh ACK, requires malformed traffic after mapping to fault, and
checks that noise cannot extend the absolute timeout or bypass RX capacity.

Snapshot 14 records remain under `/var/tmp/actryn-diag-14`, with the original
driver's RED run in `actryn-diag-14-red`. The exported evidence archive SHA-256
is `80a432cf5c1ed8a00a01300d4aee0e2f4362b3c01fa3ad5ca704deaf78bdb129`.
Its production driver SHA-256 is
`820d6e5003eec10ec7b7343c21b6554090772320753ee226962dc4c0f5ac0f12`;
its driver-test header SHA-256 is
`d41115d7c601e9726d2860a32ea9d1bcd2ebe7e3cee441664dcdb11da4e6b0ef`.
The fifteen-case validator rejected the RED failure and checked both suites,
zero skips and absence of kernel diagnostic patterns separately for each GREEN
configuration. Source and binary artifacts from earlier campaigns remain intact.

Use the authenticated Debian `linux-source-6.12=6.12.111-1` package, whose
source tarball includes the Debian patches, not a mutable checkout or the host
7.2 headers. Record package and source-tar hashes. Use Debian GCC 14
builder with make, flex, bison, libelf/libssl development packages, Python 3,
bc and QEMU x86-64. No host module loading is needed.

The tracked bootstrap executes this recipe in a disposable Debian 13 x86-64
QEMU guest, with authenticated apt retrieval, exact package/kernel version
checks, an 8 GiB free-space preflight and separate campaign artifacts:

```sh
bash kernel/tests/run-diagnostics-guest.sh /absolute/path/to/kernel /var/tmp/actryn-diagnostics-new
```

The output directory must be new. Each build/run is bounded to 30 minutes;
each emulated kernel run is bounded to 60 seconds. A failure preserves logs
and stops subsequent campaigns. For an existing completed build workspace,
[incremental update](tests/run-diagnostics-update.sh) preserves current sources
and build artifacts, verifies the prior source manifest, touches new source
timestamps and writes separately labeled results. It uses one compiler job.
The [replay notes](tests/DIAGNOSTIC_REPLAY.md) describe the preserved 11 failure
and the bounded 11b amendment.

In a disposable copy of that source, copy this committed `kernel/` directory to
`drivers/misc/actryn/`, excluding build outputs. Add these two integration lines:

```make
# drivers/misc/Makefile
obj-$(CONFIG_ACTRYN_AUTHORITY) += actryn/
```

```text
# drivers/misc/Kconfig
source "drivers/misc/actryn/Kconfig"
```

The x86 diagnostic device never probes; KUnit injects a serdev controller into
the actual production transmit, receive, close and PM functions. Tests cover
each encoded TX recovery offset, each retained RX prefix, explicit recovery,
late receipts, old/new epochs, RX capacity, nonwrapping counters, PM callbacks
and two concurrent close/fault publishers with mutex-side closure.
The grant-closure regression repeats revocation and operation-to-grant
escalation at every QUIESCE write offset, including no accepted bytes and a
fully sent frame awaiting its receipt. It requires the original bytes,
transaction and absolute close deadline to survive, then accepts that original
matching receipt. Stronger faults still dominate subsequent revocation.
This is different evidence from the ARM64 PL011 end-to-end path.

Run four **separate** builds from the source root, retaining each generated
`.config`, compiler log, test log, test JSON, vmlinux hash and command line:

```sh
python3 tools/testing/kunit/kunit.py run --arch=x86_64 \
  --kunitconfig=drivers/misc/actryn/config/kunit.config \
  --build_dir=.kunit-actryn --jobs=1 --timeout=60 \
  --qemu_args='-smp 2' --json=.kunit-actryn/results.json 'actryn*'

python3 tools/testing/kunit/kunit.py run --arch=x86_64 \
  --kunitconfig=drivers/misc/actryn/config/kunit.config \
  --kunitconfig=drivers/misc/actryn/config/lockdep.config \
  --build_dir=.kunit-actryn-lockdep --jobs=1 --timeout=60 \
  --qemu_args='-smp 2' --json=.kunit-actryn-lockdep/results.json 'actryn*'

python3 tools/testing/kunit/kunit.py run --arch=x86_64 \
  --kunitconfig=drivers/misc/actryn/config/kunit.config \
  --kunitconfig=drivers/misc/actryn/config/kasan.config \
  --build_dir=.kunit-actryn-kasan --jobs=1 --timeout=60 \
  --qemu_args='-smp 2' --json=.kunit-actryn-kasan/results.json 'actryn*'

python3 tools/testing/kunit/kunit.py run --arch=x86_64 \
  --kunitconfig=drivers/misc/actryn/config/kunit.config \
  --kunitconfig=drivers/misc/actryn/config/kcsan.config \
  --build_dir=.kunit-actryn-kcsan --jobs=1 --timeout=60 \
  --qemu_args='-smp 2' --json=.kunit-actryn-kcsan/results.json 'actryn*'
```

Require both expected suites (`actryn-authority`, `actryn-serdev-recovery`), all
expected cases and zero skips. Inspect the full kernel output, not only the
KUnit summary, for lockdep, sanitizer, warning and panic reports. An unavailable
configuration or build failure stays a failed/not-run campaign; never reuse a
different build's result. A timeout is not a timing bound. These small campaigns
do not replace actual FD-lifetime/unbind stress, platform PM, retained PL011
bytes, recorder/submission pressure or long-stall integration scenarios. The
retained-prefix test alone is not live-cause evidence. Separate ARM diagnostic
07 captured a truncated 156-byte encoded observation (expected 157 bytes), its
decoder failure and protocol closure, then a valid 157-byte HELLO_ACK. That
trace establishes the initial-handshake failure path addressed by snapshot 13.
The failed live attempt is retained separately from the subsequent tests.
