#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT HUP INT TERM
cc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -fno-omit-frame-pointer \
  "$here/engine_test.c" "$here/engine.c" "$here/../../actryn_wire.c" -o "$out/engine-test"
ASAN_OPTIONS=detect_leaks=0 "$out/engine-test"
cc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -fno-omit-frame-pointer \
  "$here/gateway_test.c" "$here/engine.c" "$here/../../actryn_wire.c" -o "$out/gateway-test"
ASAN_OPTIONS=detect_leaks=0 "$out/gateway-test"
cc -std=c11 -Wall -Wextra -Werror "$here/gateway.c" "$here/engine.c" \
  "$here/../../actryn_wire.c" -o "$out/a16-gateway"
cc -std=c11 -Wall -Wextra -Werror "$here/workload.c" -o "$out/a16-workload"
cc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -fno-omit-frame-pointer \
  "$here/workload_test.c" -o "$out/workload-test"
ASAN_OPTIONS=detect_leaks=0 "$out/workload-test"
python3 -m unittest discover -s "$here" -p '*_test.py'
python3 - "$here/../../.." <<'PY'
import pathlib
import sys
import tomllib
root = pathlib.Path(sys.argv[1]).resolve()
profile = tomllib.loads((root / 'targets/qemu-arm64-fixture/1/profile.toml').read_text())
assert profile['kernel_series'] == '6.12' and profile['wire_version'] == 2
assert not profile['physical_acceptance'] and not profile['live_actuation']
expected = {'max_duty_permille': 200, 'max_slew_permille_per_second': 1000,
            'max_slew_credit_ms': 100, 'max_grant_ms': 60000, 'max_operation_ms': 10000,
            'max_sample_ms': 500, 'max_observation_age_ms': 1000, 'max_clock_uncertainty_ms': 10,
            'clock_drift_ppm': 100, 'max_clock_mapping_age_ms': 60000, 'partial_recovery_ms': 500,
            'reconciliation_ms': 1000, 'owner_poll_ms': 100, 'rx_frames': 32, 'event_records': 256,
            'max_started_frames': 1, 'max_unsent_samples': 1}
assert profile['authority'] == expected
print('PASS fixed A16 software profile identity')
PY
