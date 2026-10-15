# Separate diagnostic kernel campaigns

These are proposed reproducible commands, not completed campaign results. The
stock Debian ARM64 module selftest is separate evidence. Retain its exact
package/configuration and binary hashes alongside each diagnostic result.

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
and stops subsequent campaigns. The script has been syntax-checked; running
it and retaining successful campaign outputs remains necessary evidence.

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
the actual production transmit and close functions. Tests cover each encoded
byte offset and two concurrent close/fault publishers with mutex-side closure.
This is different evidence from the ARM64 PL011 end-to-end path.

Run four **separate** builds from the source root, retaining each generated
`.config`, compiler log, test log, test JSON, vmlinux hash and command line:

```sh
python3 tools/testing/kunit/kunit.py run --arch=x86_64 \
  --kunitconfig=drivers/misc/actryn/config/kunit.config \
  --build_dir=.kunit-actryn --jobs=8 --timeout=60 \
  --qemu_args='-smp 2' --json=.kunit-actryn/results.json 'actryn*'

python3 tools/testing/kunit/kunit.py run --arch=x86_64 \
  --kunitconfig=drivers/misc/actryn/config/kunit.config \
  --kunitconfig=drivers/misc/actryn/config/lockdep.config \
  --build_dir=.kunit-actryn-lockdep --jobs=8 --timeout=60 \
  --qemu_args='-smp 2' --json=.kunit-actryn-lockdep/results.json 'actryn*'

python3 tools/testing/kunit/kunit.py run --arch=x86_64 \
  --kunitconfig=drivers/misc/actryn/config/kunit.config \
  --kunitconfig=drivers/misc/actryn/config/kasan.config \
  --build_dir=.kunit-actryn-kasan --jobs=8 --timeout=60 \
  --qemu_args='-smp 2' --json=.kunit-actryn-kasan/results.json 'actryn*'

python3 tools/testing/kunit/kunit.py run --arch=x86_64 \
  --kunitconfig=drivers/misc/actryn/config/kunit.config \
  --kunitconfig=drivers/misc/actryn/config/kcsan.config \
  --build_dir=.kunit-actryn-kcsan --jobs=8 --timeout=60 \
  --qemu_args='-smp 2' --json=.kunit-actryn-kcsan/results.json 'actryn*'
```

Require both expected suites (`actryn-authority`, `actryn-serdev-recovery`), all
expected cases and zero skips. Inspect the full kernel output, not only the
KUnit summary, for lockdep, sanitizer, warning and panic reports. An unavailable
configuration or build failure stays a failed/not-run campaign; never reuse a
different build's result. A timeout is not a timing bound. These small campaigns
do not replace the still-required FD-lifetime, unbind/rebind, PM, retained-UART,
capacity and long-stall integration scenarios.
