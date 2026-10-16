#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Run only after extracting source.tar.gz to /opt/actryn-a16/src in the NEW VM.
set -eu
test "$(id -u)" = 0
test "$(uname -m)" = aarch64
test "$(uname -r)" = 6.12.111+deb13-arm64
test "$(cat /etc/hostname)" = actryn-a16
tr '\0' '\n' < /proc/device-tree/compatible | grep -qx linux,dummy-virt
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
source_root=$(CDPATH= cd -- "$here/../../.." && pwd)
test "$source_root" = /opt/actryn-a16/src
mkdir /opt/actryn-a16/build  # Refuse to overwrite an earlier provision attempt.
build=/opt/actryn-a16/build
exec > "$build/provision.log" 2>&1
trap 'echo FAILED > "$build/FAILED"' EXIT HUP INT TERM
export DEBIAN_FRONTEND=noninteractive
timeout 120 apt-get -o Acquire::Retries=0 -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20 update
python3 - "$here/manifest.toml" > "$build/packages.requested" <<'PY'
import pathlib,sys,tomllib
m=tomllib.loads(pathlib.Path(sys.argv[1]).read_text())
for name,version in m['packages'].items(): print(name+'='+version)
PY
# Version tokens are fixed in the reviewed TOML, with no shell metacharacters.
timeout 600 xargs -r apt-get -y --no-install-recommends -o Acquire::Retries=0 \
  -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20 install < "$build/packages.requested"
python3 - "$here/manifest.toml" <<'PY'
import pathlib,subprocess,sys,tomllib,hashlib
m=tomllib.loads(pathlib.Path(sys.argv[1]).read_text())
for name,version in m['packages'].items():
 actual=subprocess.check_output(['dpkg-query','-W','-f=${Version}',name],text=True)
 assert actual==version,(name,actual,version)
p=pathlib.Path('/opt/actryn-a16/src/kernel/actryn_driver.c')
assert hashlib.sha256(p.read_bytes()).hexdigest()==m['authority_source_sha256']
for name,expected in m['baseline'].items():
 assert hashlib.sha256((pathlib.Path('/opt/actryn-a16/src')/name).read_bytes()).hexdigest()==expected,name
for path,expected in [('/boot/config-6.12.111+deb13-arm64',m['kernel_config_sha256']),
 ('/boot/vmlinuz-6.12.111+deb13-arm64',m['assets']['kernel']['sha256']),
 ('/opt/actryn-a16/src/targets/qemu-arm64-fixture/1/profile.toml',m['profile_sha256'])]:
 assert hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()==expected,path
PY
dpkg-query -W > "$build/packages.installed"
cp -a /var/lib/apt/lists "$build/apt-lists"
cp /boot/config-6.12.111+deb13-arm64 "$build/kernel.config"
sha256sum /boot/vmlinuz-6.12.111+deb13-arm64 "$build/kernel.config" > "$build/kernel-inputs.sha256"
gcc-14 --version > "$build/compiler.txt"
cp -a "$source_root/kernel" "$build/kernel"
timeout 300 make -C "$build/kernel" KDIR=/lib/modules/6.12.111+deb13-arm64/build CC=gcc-14 -j1
for name in selftest adversarial; do
 gcc-14 -std=c11 -O2 -Wall -Wextra -Werror "$build/kernel/tests/authority_$name.c" -o "$build/authority-$name"
done
gcc-14 -std=c11 -O2 -Wall -Wextra -Werror "$here/gateway.c" "$here/engine.c" \
 "$source_root/kernel/actryn_wire.c" -o "$build/a16-gateway"
gcc-14 -std=c11 -O2 -Wall -Wextra -Werror "$here/workload.c" -o "$build/a16-workload"
sha256sum "$build/kernel/actryn_authority.ko" "$build/a16-gateway" "$build/a16-workload" \
 "$build/authority-selftest" "$build/authority-adversarial" > "$build/binaries.sha256"
readelf -n "$build/kernel/actryn_authority.ko" "$build/a16-gateway" "$build/a16-workload" > "$build/build-ids.txt"
echo 'PASS provisioning/build only; target qualification NOT_RUN' > "$build/BUILD_PASS"
trap - EXIT HUP INT TERM
