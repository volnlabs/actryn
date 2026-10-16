#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail
if [ "$#" -ne 2 ]; then
  echo "usage: $0 KERNEL_SOURCE_DIRECTORY NEW_OUTPUT_DIRECTORY" >&2
  exit 2
fi
input=$(realpath "$1")
output=$(realpath -m "$2")
test -f "$input/actryn_driver.c"
test "$(id -u)" = 0
test "$(uname -m)" = x86_64
. /etc/os-release
test "$ID" = debian
test "$VERSION_ID" = 13
case "$(systemd-detect-virt --vm)" in qemu|kvm) ;; *) echo "Disposable QEMU guest required" >&2; exit 2;; esac
if [ -e "$output" ]; then
  echo "Refusing to overwrite an existing diagnostic campaign: $output" >&2
  exit 2
fi
mkdir -p "$output"
exec > >(tee "$output/campaign.log") 2>&1
trap 'rc=$?; if [ "$rc" -ne 0 ]; then echo "FAILED exit=$rc" > "$output/FAILED"; fi' EXIT
available=$(df --output=avail -B1 "$output" | tail -n 1)
if [ "$available" -lt 8589934592 ]; then
  echo "At least 8 GiB free guest disk is required for source and four retained builds"
  exit 1
fi
timeout --kill-after=15s 180s apt-get update
DEBIAN_FRONTEND=noninteractive timeout --kill-after=15s 600s apt-get install -y --no-install-recommends \
  gcc-14 g++-14 make flex bison libelf-dev libssl-dev bc python3 \
  qemu-system-x86 xz-utils ca-certificates
mkdir "$output/download"
cd "$output/download"
# apt verifies repository signatures and the package digest from authenticated metadata.
timeout --kill-after=15s 300s apt-get download linux-source-6.12=6.12.111-1
package="$output/download/linux-source-6.12_6.12.111-1_all.deb"
test "$(dpkg-deb -f "$package" Version)" = 6.12.111-1
sha256sum "$package" > "$output/source-package.sha256"
dpkg-deb -x "$package" "$output/source-package"
source_tar="$output/source-package/usr/src/linux-source-6.12.tar.xz"
sha256sum "$source_tar" > "$output/source-tar.sha256"
tar -xf "$source_tar" -C "$output"
cd "$output/linux-source-6.12"
test "$(make -s kernelversion)" = 6.12.111
mkdir drivers/misc/actryn
tar -C "$input" --exclude='*.o' --exclude='*.ko' --exclude='*.mod*' \
  --exclude='.*.cmd' --exclude=Module.symvers --exclude=modules.order -cf - . |
  tar -C drivers/misc/actryn -xf -
printf '\nobj-$(CONFIG_ACTRYN_AUTHORITY) += actryn/\n' >> drivers/misc/Makefile
printf '\nsource "drivers/misc/actryn/Kconfig"\n' >> drivers/misc/Kconfig
find drivers/misc/actryn -type f -print0 | sort -z | xargs -0 sha256sum > "$output/authority-source.sha256"
gcc-14 --version > "$output/compiler.txt"
qemu-system-x86_64 --version > "$output/qemu.txt"
dpkg-query -W gcc-14 make flex bison libelf-dev libssl-dev python3 qemu-system-x86 > "$output/build-packages.txt"
for campaign in plain lockdep kasan kcsan; do
  build="$output/build-$campaign"
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
  echo "Starting $campaign; maximum build-and-run time 30 minutes"
  timeout --signal=TERM --kill-after=15s 1800s "${command[@]}" > "$output/$campaign.log" 2>&1
  test -f "$build/test.log"
  cp "$build/.config" "$output/$campaign.config"
  sha256sum "$build/vmlinux" > "$output/$campaign.vmlinux.sha256"
  python3 - "$output/$campaign.json" "$build/test.log" <<'PY'
import json
import pathlib
import re
import sys
data = json.loads(pathlib.Path(sys.argv[1]).read_text())
text = pathlib.Path(sys.argv[2]).read_text()
expected = {"wire_roundtrip", "urgent_monotonic", "every_cancel_offset", "concurrent_closure", "late_receipts", "every_fault_recovery_offset", "stalled_parser_timeout", "inhibited_revoke", "retained_rx_recovery", "stale_epoch_receipts", "new_controller_epoch", "bounded_queues_counters", "pm_inhibition", "handshake_rx_sync", "grant_closure_idempotence", "receive_wakeup_preserved"}
suites = {"actryn-authority", "actryn-serdev-recovery"}
found, found_suites = set(), set()
def visit(node):
    if isinstance(node, dict):
        name = node.get("name", "")
        if name in expected:
            assert node.get("status") == "PASS", node
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
assert not re.search(r"BUG:|WARNING:|KASAN:|KCSAN:|possible circular locking|Kernel panic|not ok|# SKIP", text), text
print("Expected cases passed; no skip or kernel diagnostic pattern found")
PY
  echo "PASS $campaign" | tee "$output/$campaign.PASS"
done
echo "Four diagnostic campaigns passed; retain all output with the tested source revision"
