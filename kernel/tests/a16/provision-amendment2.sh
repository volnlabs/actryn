#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Premeasurement amendment: retain original source/build; no apt, module or service actions.
set -eu
test "$(id -u)" = 0
test "$(uname -m)" = aarch64
test "$(uname -r)" = 6.12.111+deb13-arm64
test "$(cat /etc/hostname)" = actryn-a16
tr '\0' '\n' < /proc/device-tree/compatible | grep -qx linux,dummy-virt
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
source_root=$(CDPATH= cd -- "$here/../../.." && pwd)
test "$source_root" = /opt/actryn-a16/src-amendment2
original=/opt/actryn-a16/build
build=/opt/actryn-a16/build-amendment2
test -f "$original/BUILD_PASS"
mkdir "$build" # Never overwrite an original or failed amendment build.
exec > "$build/provision.log" 2>&1
trap 'echo FAILED > "$build/FAILED"' EXIT HUP INT TERM
python3 - "$source_root" <<'PY'
import hashlib,pathlib,subprocess,sys,tomllib
root=pathlib.Path(sys.argv[1]); here=root/'kernel/tests/a16'
amendment=tomllib.loads((here/'amendment2.toml').read_text())
original=pathlib.Path('/opt/actryn-a16/src')
digest=lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
assert amendment['revision']==2
assert digest(original/'kernel/tests/a16/manifest.toml')==amendment['base_manifest_sha256']
base=tomllib.loads((original/'kernel/tests/a16/manifest.toml').read_text())
assert digest(root/'kernel/tests/a16/manifest.toml')==amendment['base_manifest_sha256']
assert digest(root/'kernel/actryn_driver.c')==base['authority_source_sha256']
for path,expected in base['baseline'].items():
 assert digest(original/path)==expected,path
 if path!='kernel/tests/a16/workload.c': assert digest(root/path)==expected,path
for path,expected in amendment['sources'].items(): assert digest(root/path)==expected,path
assert subprocess.check_output(['dpkg-query','-W','-f=${Version}','gcc-14'],text=True)=='14.2.0-19'
PY
sha256sum -c "$original/binaries.sha256"
cp "$original/binaries.sha256" "$build/original-binaries.sha256"
cp "$original/compiler.txt" "$original/packages.installed" "$build/"
cp "$here/amendment2.toml" "$build/amendment2.toml"
mkdir "$build/kernel" "$build/kernel/tests"
cp "$original/kernel/actryn_authority.ko" "$build/kernel/actryn_authority.ko"
cp "$original/kernel/tests/arm_trace.sh" "$build/kernel/tests/arm_trace.sh"
cp "$original/a16-gateway" "$original/authority-selftest" "$original/authority-adversarial" "$build/"
timeout 60 gcc-14 -std=c11 -O2 -Wall -Wextra -Werror "$here/workload.c" -o "$build/a16-workload"
timeout 60 gcc-14 -std=c11 -O2 -Wall -Wextra -Werror "$here/workload_test.c" -o "$build/workload-test"
timeout 10 "$build/workload-test" > "$build/workload-test.log"
sha256sum "$build/kernel/actryn_authority.ko" "$build/a16-gateway" "$build/a16-workload" \
 "$build/authority-selftest" "$build/authority-adversarial" > "$build/binaries.sha256"
readelf -n "$build/kernel/actryn_authority.ko" "$build/a16-gateway" "$build/a16-workload" > "$build/build-ids.txt"
echo 'revision 2; original source/build retained; no target pilot executed' > "$build/AMENDMENT2"
echo 'PASS amendment build/predicate test only; target qualification NOT_RUN' > "$build/BUILD_PASS"
trap - EXIT HUP INT TERM
