#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Preserve the current authority sources/build artifacts before incremental tests.
set -euo pipefail
if [ "$#" -lt 5 ]; then
  echo "usage: $0 INPUT_KERNEL WORKSPACE CURRENT_SOURCE_MANIFEST NEW_OUTPUT plain|lockdep|kasan|kcsan [...]" >&2
  exit 2
fi
input=$(realpath "$1")
workspace=$(realpath "$2")
manifest=$(realpath "$3")
output=$(realpath -m "$4")
shift 4
test "$(id -u)" = 0
test "$(uname -m)" = x86_64
. /etc/os-release
test "$ID" = debian
test "$VERSION_ID" = 13
case "$(systemd-detect-virt --vm)" in qemu|kvm) ;; *) exit 2;; esac
case "$output/" in "$workspace/"*) echo "Separate output required" >&2; exit 2;; esac
test ! -e "$output"
test -f "$input/actryn_driver_test.h"
for campaign in "$@"; do
  case "$campaign" in plain|lockdep|kasan|kcsan) ;; *) exit 2;; esac
done
mkdir "$output"
exec > >(tee "$output/campaign.log") 2>&1
trap 'rc=$?; if [ "$rc" -ne 0 ]; then echo "FAILED exit=$rc" > "$output/FAILED"; fi' EXIT
source_tree="$workspace/linux-source-6.12"
cd "$source_tree"
test "$(make -s kernelversion)" = 6.12.111
test "$(dpkg-deb -f "$workspace/download/linux-source-6.12_6.12.111-1_all.deb" Version)" = 6.12.111-1
sha256sum -c "$workspace/source-package.sha256"
sha256sum -c "$workspace/source-tar.sha256"
sha256sum -c "$manifest"
gcc-14 --version > "$output/compiler.txt"
qemu-system-x86_64 --version > "$output/qemu.txt"
dpkg-query -W gcc-14 make flex bison libelf-dev libssl-dev python3 qemu-system-x86 > "$output/build-packages.txt"
for file in compiler.txt qemu.txt build-packages.txt; do cmp "$workspace/$file" "$output/$file"; done
required=536870912
for campaign in "$@"; do
  for file in vmlinux arch/x86/boot/bzImage; do
    bytes=$(stat -c %s "$workspace/build-$campaign/$file")
    required=$((required+bytes*2))
  done
done
available=$(df --output=avail -B1 "$output" | tail -n 1)
echo "Disk preflight: available=$available required=$required"
test "$available" -ge "$required"
mkdir "$output/before"
cp "$manifest" "$output/before/authority-source.sha256"
for campaign in "$@"; do
  build="$workspace/build-$campaign"
  cp "$build/vmlinux" "$output/before/$campaign.vmlinux"
  cp "$build/arch/x86/boot/bzImage" "$output/before/$campaign.bzImage"
  cp "$build/.config" "$output/before/$campaign.config"
  cp "$build/test.log" "$output/before/$campaign.test.log"
done
find "$output/before" -type f -print0 | sort -z | xargs -0 sha256sum > "$output/before.sha256"
stage="$source_tree/drivers/misc/.actryn-update-$$"
mkdir "$stage"
tar -C "$input" --exclude='*.o' --exclude='*.ko' --exclude='*.mod*' \
  --exclude='.*.cmd' --exclude=Module.symvers --exclude=modules.order \
  --exclude=__pycache__ --exclude='*.pyc' -cf - . | tar -C "$stage" -xf -
test "$(stat -c %d "$output")" = "$(stat -c %d "$stage")"
mv drivers/misc/actryn "$output/previous-authority-source"
mv "$stage" drivers/misc/actryn
find drivers/misc/actryn -type f -exec touch -- {} +
find drivers/misc/actryn -type f -print0 | sort -z | xargs -0 sha256sum > "$output/authority-source.sha256"
tar -czf "$output/authority-source.tar.gz" drivers/misc/actryn
for campaign in "$@"; do
  build="$workspace/build-$campaign"
  fragments=(--kunitconfig=drivers/misc/actryn/config/kunit.config)
  if [ "$campaign" != plain ]; then
    fragments+=(--kunitconfig="drivers/misc/actryn/config/$campaign.config")
  fi
  command=(python3 tools/testing/kunit/kunit.py run --arch=x86_64 "${fragments[@]}"
    --build_dir="$build" --jobs=1 --timeout=60 --qemu_args='-smp 2'
    --make_options=CC=gcc-14 --make_options=HOSTCC=gcc-14
    --json="$output/$campaign.json" 'actryn*')
  printf '%q ' "${command[@]}" > "$output/$campaign.command"
  printf '\n' >> "$output/$campaign.command"
  echo "Starting $campaign; maximum build-and-run time 30 minutes; one compiler job"
  run_status=0
  timeout --signal=TERM --kill-after=15s 1800s nice -n 10 "${command[@]}" > "$output/$campaign.log" 2>&1 || run_status=$?
  printf '%s\n' "$run_status" > "$output/$campaign.exit"
  for file in .config test.log vmlinux System.map; do
    if [ -f "$build/$file" ]; then cp "$build/$file" "$output/$campaign.$file"; fi
  done
  if [ -f "$build/arch/x86/boot/bzImage" ]; then cp "$build/arch/x86/boot/bzImage" "$output/$campaign.bzImage"; fi
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
            'stalled_parser_timeout', 'inhibited_revoke', 'retained_rx_recovery',
            'stale_epoch_receipts', 'new_controller_epoch', 'bounded_queues_counters',
            'pm_inhibition', 'handshake_rx_sync', 'grant_closure_idempotence',
            'receive_wakeup_preserved'}
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
print('All sixteen cases and both suites passed; no skip or kernel diagnostic pattern')
PY
  test "$run_status" = 0
  sha256sum -c "$output/before.sha256"
  echo "PASS $campaign" | tee "$output/$campaign.PASS"
done
