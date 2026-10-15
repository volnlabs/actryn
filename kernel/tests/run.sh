#!/bin/sh
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT HUP INT TERM
cc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -g \
  "$here/wire_test.c" "$here/../actryn_wire.c" -o "$out/wire-test"
ASAN_OPTIONS=detect_leaks=0 "$out/wire-test"
ASAN_OPTIONS=detect_leaks=0 python3 "$here/wire_golden.py" "$out/wire-test"
