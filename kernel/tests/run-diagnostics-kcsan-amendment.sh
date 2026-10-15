#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Separate amendment after the eight-case validator exposed a stale KCSAN object.
set -euo pipefail
if [ "$#" -ne 3 ]; then
  echo "usage: $0 PREVIOUS_07_WORKSPACE FAILED_11_OUTPUT NEW_11B_OUTPUT" >&2
  exit 2
fi
previous=$(realpath "$1")
failed=$(realpath "$2")
output=$(realpath -m "$3")
test "$(id -u)" = 0
test "$(uname -m)" = x86_64
. /etc/os-release
test "$ID" = debian
test "$VERSION_ID" = 13
case "$(systemd-detect-virt --vm)" in qemu|kvm) ;; *) exit 2;; esac
case "$output/" in "$previous/"*|"$failed/"*) echo "Separate output required" >&2; exit 2;; esac
test ! -e "$output"
test -f "$failed/FAILED"
test ! -f "$failed/kcsan.PASS"
test "$(cat "$previous/.actryn-replay-started/output")" = "$failed"
source_tree="$previous/linux-source-6.12"
build="$previous/build-kcsan"
test -f "$build/drivers/misc/actryn/actryn_driver.o"
mkdir "$output"
exec > >(tee "$output/campaign.log") 2>&1
trap 'rc=$?; if [ "$rc" -ne 0 ]; then echo "FAILED exit=$rc" > "$output/FAILED"; fi' EXIT
bytes=$(stat -c %s "$build/vmlinux")
required=$((bytes*2+536870912))
available=$(df --output=avail -B1 "$output" | tail -n 1)
echo "Disk preflight: available=$available required=$required"
test "$available" -ge "$required"
cd "$source_tree"
test "$(make -s kernelversion)" = 6.12.111
test "$(dpkg-deb -f "$previous/download/linux-source-6.12_6.12.111-1_all.deb" Version)" = 6.12.111-1
sha256sum -c "$failed/authority-source.sha256"
sha256sum -c "$previous/source-package.sha256"
sha256sum -c "$previous/source-tar.sha256"
sha256sum -c "$failed/previous-evidence.sha256"
gcc-14 --version > "$output/compiler.txt"
qemu-system-x86_64 --version > "$output/qemu.txt"
dpkg-query -W gcc-14 make flex bison libelf-dev libssl-dev python3 qemu-system-x86 > "$output/build-packages.txt"
for file in compiler.txt qemu.txt build-packages.txt; do cmp "$failed/$file" "$output/$file"; done
mkdir "$output/prior-failure"
for suffix in json log command config test.log binary.sha256; do
  cp "$failed/kcsan.$suffix" "$output/prior-failure/kcsan.$suffix"
done
cp "$failed/FAILED" "$output/prior-failure/FAILED"
cp "$failed/campaign.log" "$output/prior-failure/campaign.log"
cp "$failed/authority-source.sha256" "$output/authority-source.sha256"
stat --printf='%n size=%s mtime=%y\n' drivers/misc/actryn/actryn_driver.c \
  drivers/misc/actryn/actryn_driver_test.h "$build/drivers/misc/actryn/actryn_driver.o" \
  "$build/vmlinux" > "$output/prior-failure/timestamps.txt"
sha256sum "$build/drivers/misc/actryn/actryn_driver.o" "$build/vmlinux" \
  > "$output/prior-failure/build.sha256"
find "$output/prior-failure" -type f -print0 | sort -z | xargs -0 sha256sum > "$output/prior-failure.sha256"
cat "$output/prior-failure/timestamps.txt"
# Change only source mtimes, retaining exactly the reviewed snapshot 11 bytes.
find drivers/misc/actryn -type f -exec touch -- {} +
sha256sum -c "$output/authority-source.sha256"
command=(python3 tools/testing/kunit/kunit.py run --arch=x86_64
  --kunitconfig=drivers/misc/actryn/config/kunit.config
  --kunitconfig=drivers/misc/actryn/config/kcsan.config
  --build_dir="$build" --jobs=2 --timeout=60 --qemu_args='-smp 2'
  --make_options=CC=gcc-14 --make_options=HOSTCC=gcc-14
  --json="$output/kcsan.json" 'actryn*')
printf '%q ' "${command[@]}" > "$output/kcsan.command"
printf '\n' >> "$output/kcsan.command"
timeout --signal=TERM --kill-after=15s 1800s "${command[@]}" > "$output/kcsan.log" 2>&1
cp "$build/.config" "$output/kcsan.config"
cp "$build/test.log" "$output/kcsan.test.log"
cp "$build/vmlinux" "$output/kcsan.vmlinux"
cp "$build/arch/x86/boot/bzImage" "$output/kcsan.bzImage"
cp "$build/System.map" "$output/kcsan.System.map"
sha256sum "$output/kcsan.vmlinux" "$output/kcsan.bzImage" > "$output/kcsan.binary.sha256"
python3 - "$output/kcsan.json" "$output/kcsan.test.log" <<'PY'
import json
import pathlib
import re
import sys
data = json.loads(pathlib.Path(sys.argv[1]).read_text())
text = pathlib.Path(sys.argv[2]).read_text()
expected = {'wire_roundtrip', 'urgent_monotonic', 'every_cancel_offset',
            'concurrent_closure', 'late_receipts', 'every_fault_recovery_offset',
            'stalled_parser_timeout', 'inhibited_revoke'}
suites = {'actryn-authority', 'actryn-serdev-recovery'}
found, found_suites = set(), set()
def visit(node):
    if isinstance(node, dict):
        name = node.get('name', '')
        if name in expected:
            assert node.get('status') == 'PASS', node
            found.add(name)
        if name in suites:
            found_suites.add(name)
        for value in node.values():
            visit(value)
    elif isinstance(node, list):
        for value in node:
            visit(value)
visit(data)
assert found == expected, (found, expected)
assert found_suites == suites, (found_suites, suites)
assert not re.search(r'BUG:|WARNING:|KASAN:|KCSAN:|possible circular locking|Kernel panic|not ok|# SKIP', text), text
print('All eight 11b cases and both suites passed; no skip or kernel diagnostic pattern')
PY
sha256sum -c "$output/prior-failure.sha256"
sha256sum -c "$failed/previous-evidence.sha256"
echo "PASS kcsan" | tee "$output/kcsan.PASS"
