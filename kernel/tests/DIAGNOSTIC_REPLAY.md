# Incremental diagnostic replay

Run inside the same disposable Debian 13 x86 QEMU guest that completed all
four snapshot 07 campaigns. Use an extracted, reviewed snapshot 11 source
directory and a new output directory:

```sh
bash kernel/tests/run-diagnostics-replay.sh \
  /root/snapshot11/kernel /var/tmp/actryn-diag-07 /var/tmp/actryn-diag-11
```

The script first checks free disk space, the exact Linux 6.12.111 source
package and source hashes, compiler/QEMU versions, and installed build-package
versions. Before replacing source or reusing build objects, it copies each
07 log, configuration, JSON result, command, hash, `vmlinux`, `bzImage`, and
`System.map` into the new campaign's `previous/` directory. It verifies the
copied `vmlinux` bytes against the original recorded hashes and retains the
old authority source directory and a source archive.

The original 07 build directories then become incremental workspaces. Their
build outputs and source path change; the copied, hashed evidence is the
preserved 07 record. Each 11 campaign gets separate logs, JSON, configuration,
binary copies and hashes. Plain KUnit, lockdep, KASAN and KCSAN each require
both suites and all eight expected cases to pass without skips or kernel
diagnostic patterns. The script verifies the copied 07 evidence hashes again
afterward.

Each build/run has a 30-minute timeout and each QEMU test execution a
60-second timeout. A failure is retained as `FAILED`; an existing output
directory or replay marker prevents silent reuse. A replay failure requires
inspection before another separately labeled attempt. Successful snapshot 07
results do not establish that snapshot 11 passed.

The first incremental 11 attempt produced seven KCSAN cases, failing the
eight-case validator. A copied source timestamp older than an object built late
in campaign 07 can hide changed bytes from Kbuild; retain timestamps to verify
that diagnosis. Replay now touches staged
authority files before compilation, changing no source bytes. Preserve that
failed attempt and run the narrowly scoped KCSAN amendment separately:

```sh
bash kernel/tests/run-diagnostics-kcsan-amendment.sh \
  /var/tmp/actryn-diag-07 /var/tmp/actryn-diag-11 /var/tmp/actryn-diag-11b
```

This records the previous source/object timestamps, verifies the reviewed 11
source hashes before and after touching source files, and writes a distinct
KCSAN result. The original 11 failure and preserved 07 evidence remain intact.
