#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Reuse completed 07 build objects, preserving its evidence before any mutation.
set -euo pipefail
if [ "$#" -ne 3 ]; then
  echo "usage: $0 KERNEL_INPUT COMPLETED_07_DIRECTORY NEW_11_OUTPUT_DIRECTORY" >&2
  exit 2
fi
input=$(realpath "$1")
previous=$(realpath "$2")
output=$(realpath -m "$3")
test "$(id -u)" = 0
test "$(uname -m)" = x86_64
. /etc/os-release
test "$ID" = debian
test "$VERSION_ID" = 13
case "$(systemd-detect-virt --vm)" in qemu|kvm) ;; *) echo "Disposable QEMU guest required" >&2; exit 2;; esac
case "$output/" in "$previous/"*) echo "New output must be outside the previous campaign" >&2; exit 2;; esac
test ! -e "$output"
test -f "$input/actryn_driver.c"
python3 - "$input/actryn_driver_test.h" <<'PY'
import pathlib
import sys
assert 'KUNIT_CASE(inhibited_revoke)' in pathlib.Path(sys.argv[1]).read_text()
PY
source_tree="$previous/linux-source-6.12"
test -d "$source_tree/drivers/misc/actryn"
for campaign in plain lockdep kasan kcsan; do
  test "$(cat "$previous/$campaign.PASS")" = "PASS $campaign"
  test -f "$previous/build-$campaign/test.log"
  test -f "$previous/build-$campaign/vmlinux"
  test -f "$previous/build-$campaign/arch/x86/boot/bzImage"
done
mkdir -p "$output"
exec > >(tee "$output/campaign.log") 2>&1
trap 'rc=$?; if [ "$rc" -ne 0 ]; then echo "FAILED exit=$rc" > "$output/FAILED"; fi' EXIT
test "$(stat -c %d "$output")" = "$(stat -c %d "$source_tree/drivers/misc/actryn")"
# Reserve both the preserved 07 binaries and distinct 11 binaries, plus headroom.
binary_bytes=0
for campaign in plain lockdep kasan kcsan; do
  for file in vmlinux arch/x86/boot/bzImage; do
    size=$(stat -c %s "$previous/build-$campaign/$file")
    binary_bytes=$((binary_bytes+size))
  done
done
required=$((binary_bytes*2+536870912))
available=$(df --output=avail -B1 "$output" | tail -n 1)
echo "Disk preflight: available=$available required=$required binary_bytes=$binary_bytes"
if [ "$available" -lt "$required" ]; then
  echo "Insufficient space to preserve both campaigns; no previous inputs or builds changed"
  exit 1
fi
cd "$source_tree"
test "$(make -s kernelversion)" = 6.12.111
test "$(dpkg-deb -f "$previous/download/linux-source-6.12_6.12.111-1_all.deb" Version)" = 6.12.111-1
sha256sum -c "$previous/source-package.sha256"
sha256sum -c "$previous/source-tar.sha256"
sha256sum -c "$previous/authority-source.sha256"
gcc-14 --version > "$output/compiler.txt"
qemu-system-x86_64 --version > "$output/qemu.txt"
cmp "$previous/compiler.txt" "$output/compiler.txt"
cmp "$previous/qemu.txt" "$output/qemu.txt"
dpkg-query -W gcc-14 make flex bison libelf-dev libssl-dev python3 qemu-system-x86 > "$output/build-packages.txt"
cmp "$previous/build-packages.txt" "$output/build-packages.txt"
mkdir "$output/previous"
for file in campaign.log compiler.txt qemu.txt build-packages.txt authority-source.sha256 source-package.sha256 source-tar.sha256; do
  cp "$previous/$file" "$output/previous/$file"
done
cp drivers/misc/Kconfig "$output/previous/drivers-misc.Kconfig"
cp drivers/misc/Makefile "$output/previous/drivers-misc.Makefile"
for campaign in plain lockdep kasan kcsan; do
  build="$previous/build-$campaign"
  for suffix in json log command PASS vmlinux.sha256 config; do
    cp "$previous/$campaign.$suffix" "$output/previous/$campaign.$suffix"
  done
  cp "$build/test.log" "$output/previous/$campaign.test.log"
  cp "$build/.config" "$output/previous/$campaign.build.config"
  cp "$build/vmlinux" "$output/previous/$campaign.vmlinux"
  cp "$build/arch/x86/boot/bzImage" "$output/previous/$campaign.bzImage"
  cp "$build/System.map" "$output/previous/$campaign.System.map"
  # Validate preserved bytes against the original source campaign's binary hash.
  expected=$(cut -d ' ' -f 1 "$previous/$campaign.vmlinux.sha256")
  actual=$(sha256sum "$output/previous/$campaign.vmlinux" | cut -d ' ' -f 1)
  test "$actual" = "$expected"
done
tar -czf "$output/previous-authority-source.tar.gz" drivers/misc/actryn
sha256sum "$output/previous-authority-source.tar.gz" > "$output/previous-authority-source.tar.gz.sha256"
find "$output/previous" -type f -print0 | sort -z | xargs -0 sha256sum > "$output/previous-evidence.sha256"
# Stage the new source first. Retain the complete old authority directory.
stage="$source_tree/drivers/misc/.actryn-replay-$$"
mkdir "$stage"
tar -C "$input" --exclude='*.o' --exclude='*.ko' --exclude='*.mod*' \
  --exclude='.*.cmd' --exclude=Module.symvers --exclude=modules.order \
  --exclude=__pycache__ --exclude='*.pyc' -cf - . | tar -C "$stage" -xf -
mkdir "$previous/.actryn-replay-started"
printf '%s\n' "$output" > "$previous/.actryn-replay-started/output"
mv drivers/misc/actryn "$output/previous-authority-source"
mv "$stage" drivers/misc/actryn
# Archives retain mtimes; an older source timestamp can otherwise hide changed
# bytes from an object compiled late in the previous four-campaign run.
find drivers/misc/actryn -type f -exec touch -- {} +
find drivers/misc/actryn -type f -print0 | sort -z | xargs -0 sha256sum > "$output/authority-source.sha256"
tar -czf "$output/authority-source.tar.gz" drivers/misc/actryn
echo "Previous build paths are now incremental workspaces; preserved 07 evidence is in $output/previous"
for campaign in plain lockdep kasan kcsan; do
  build="$previous/build-$campaign"
  fragments=(--kunitconfig=drivers/misc/actryn/config/kunit.config)
  if [ "$campaign" != plain ]; then
    fragments+=(--kunitconfig="drivers/misc/actryn/config/$campaign.config")
  fi
  command=(python3 tools/testing/kunit/kunit.py run --arch=x86_64 "${fragments[@]}"
    --build_dir="$build" --jobs=2 --timeout=60 --qemu_args='-smp 2'
    --make_options=CC=gcc-14 --make_options=HOSTCC=gcc-14
    --json="$output/$campaign.json" 'actryn*')
  printf '%q ' "${command[@]}" > "$output/$campaign.command"
  printf '\n' >> "$output/$campaign.command"
  echo "Starting 11 $campaign; maximum incremental build-and-run time 30 minutes"
  timeout --signal=TERM --kill-after=15s 1800s "${command[@]}" > "$output/$campaign.log" 2>&1
  cp "$build/.config" "$output/$campaign.config"
  cp "$build/test.log" "$output/$campaign.test.log"
  cp "$build/vmlinux" "$output/$campaign.vmlinux"
  cp "$build/arch/x86/boot/bzImage" "$output/$campaign.bzImage"
  cp "$build/System.map" "$output/$campaign.System.map"
  sha256sum "$output/$campaign.vmlinux" "$output/$campaign.bzImage" > "$output/$campaign.binary.sha256"
  python3 - "$output/$campaign.json" "$output/$campaign.test.log" <<'PY'
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
print('All eight 11 cases and both suites passed; no skip or kernel diagnostic pattern')
PY
  echo "PASS $campaign" | tee "$output/$campaign.PASS"
done
sha256sum -c "$output/previous-evidence.sha256"
echo "Four 11 campaigns passed; preserved 07 evidence hashes still match"
