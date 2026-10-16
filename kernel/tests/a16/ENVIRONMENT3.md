# A16 environment amendment 3: compact raw DTB

Raw boot 01 failed before console output or SSH. It did not run the userspace
pilot or consume comparison trials. The original input, command, empty serial
log, QMP diagnostics and stopped-attempt record remain under `.cache/qemu/a16`.
The observed ARM64 register fragments match `setup_machine_fdt`'s invalid-DTB
message and its terminal loop. The expanded guest-memory FDT header was **not**
captured, so its size below is derived from source, not a memory measurement.

The exact tagged upstream paths establish a sufficient deterministic cause:

- [QEMU 11.1.1 `load_device_tree`](https://raw.githubusercontent.com/qemu/qemu/v11.1.1/system/device_tree.c)
  reads the file length, reserves `(length + 10000) * 2`, and calls
  `fdt_open_into` with that capacity (lines 73–115).
- [`fdt_open_into`](https://raw.githubusercontent.com/gregkh/linux/v6.12.111/scripts/dtc/libfdt/fdt_rw.c)
  sets the destination header's total size to the supplied capacity in both
  layout branches (lines 394–450).
- [QEMU ARM boot](https://raw.githubusercontent.com/qemu/qemu/v11.1.1/hw/arm/boot.c)
  installs the loaded blob without packing it (lines 443–456 and 583–589);
  [the virt machine](https://raw.githubusercontent.com/qemu/qemu/v11.1.1/hw/arm/virt.c)
  does not provide a `modify_dtb` packing callback.
- [Linux 6.12.111 `fixmap_remap_fdt`](https://raw.githubusercontent.com/gregkh/linux/v6.12.111/arch/arm64/mm/fixmap.c)
  rejects a header total size above `MAX_FDT_SIZE` (lines 151–153), which
  [ARM64 boot constants](https://raw.githubusercontent.com/gregkh/linux/v6.12.111/arch/arm64/include/asm/boot.h)
  define as 2 MiB. [`setup_machine_fdt`](https://raw.githubusercontent.com/gregkh/linux/v6.12.111/arch/arm64/kernel/setup.c)
  emits the observed text and loops after this failure (lines 162–186).

The retained raw blob is 1,048,576 bytes, giving a QEMU-loaded total of
2,117,152 bytes: 20,000 above Linux's 2,097,152-byte limit. The exact Debian
source patch delta has not been independently compared here; the tagged upstream
paths and observed panic are the evidence boundary. Boot 02 must test the
correction before the userspace pilot proceeds.

## Frozen correction and proof

`amendment3.toml` pins the original and compact blobs, failed-boot records,
commands and equality proof. DTC v1.8.1 produced the new file with these steps
(each output was created separately; no existing artifact was overwritten):

```text
dtc -I dtb -O dts -s boot/raw.dtb > environment-amendment3/raw.normalized.dts
dtc -I dts -O dtb environment-amendment3/raw.normalized.dts > boot/raw-compact-amendment3.dtb
dtc -I dtb -O dts -s boot/raw-compact-amendment3.dtb > environment-amendment3/compact.normalized.dts
```

Both normalized DTS files are byte-identical, SHA256
`0de56fd8d2557141e0adf8b8ae34fb8fbc53908b414b598f644f858abc31c463`.
The compact blob is 8,268 bytes, SHA256
`d168b0d8d40ad598f66d705351aaa65ce2c6fe55b4b47f829deac5c858fac6a5`.
Its header total size also equals 8,268, predicting 36,536 bytes after QEMU
expansion. `environment-amendment3/proof.json` retains full input/output headers,
tool version, exact absolute commands, equality/hash results and argument diff.
DTC stderr is retained beside it. Compaction changes representation and padding;
it does not alter the raw UART device-tree semantics.

The frozen `qemu-rawboot02.json` changes only argument 20 (the DTB path) and
argument 32 (a fresh `serial-rawboot02.log`) relative to `qemu-pilot01.json`.
Machine, CPU, memory, disk, seed, ports, fixture connection, kernel, initrd and
command line are identical. The protected-mode DTB, module, fixture, workload,
limits, original source archive and all amendment-2 pins remain unchanged.

## Separate diagnostic boot, then one pilot

The integration owner reviews the manifest and verifies it without guest access:

```sh
python3 kernel/tests/a16/environment3.py verify .cache/qemu/a16
```

Only after that review, launch the stopped dedicated VM using the exact JSON
argument vector in `qemu-rawboot02.json`, retaining the unit invocation and result
as a new boot-02 record. Capture the new boot ID, hostname, kernel, raw
`/dev/ttyAMA1` ownership and absence of `/dev/actryn-authority`, along with serial
and QMP evidence. Do not overwrite the failed boot or alter its status. Failure
of this diagnostic stops the pilot; another attempt requires a separately
identified explanation and amendment.

After successful diagnostic boot 02, the required userspace pilot entry is:

```sh
python3 kernel/tests/a16/environment3.py pilot .cache/qemu/a16
```

The wrapper verifies frozen files and unchanged amendment-2 source pins, and
requires every argument of the running `actryn-a16-robot.service` process to
match the amended command. It records process identity before and after invoking
the unchanged `pilot.py userspace`, rejects process replacement, and retains
environment evidence separately under `qualification/environment3-userspace01`
and inside `qualification/userspace01/environment-amendment3.json`. Both inner
pilot and environment-wrapper PASS are required. Failure consumes this labeled
pilot; the wrapper never retries it. Do not call the unwrapped userspace pilot.

This amendment authorizes no automatic comparison launch and establishes no
performance, physical actuation, superiority, equivalence or WCET result.
The frozen manifest's NOT_RUN fields describe its pre-execution state; later
outcomes belong in separately retained evidence, never by editing these pins.
