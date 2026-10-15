#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Diagnostic-only kprobes; error-triggered stack traces, no driver mutation.
set -eu
test "$(id -u)" = 0
test "$(uname -m)" = aarch64
test "$(uname -r)" = 6.12.111+deb13-arm64
tr '\0' '\n' < /proc/device-tree/compatible | grep -qx linux,dummy-virt
cd /sys/kernel/tracing
case "${1:-}" in
start)
 test "$(cat current_tracer)" = nop
 test -z "$(cat kprobe_events)"
 echo 0 > tracing_on
 echo > trace
 printf '%s\n' 'p:actryn_close actryn_authority:request_close rank=$arg2:u32 reason=$arg3:u32' >> kprobe_events
 printf '%s\n' 'r:actryn_decode actryn_authority:actryn_decode result=$retval:s32' >> kprobe_events
 printf '%s\n' 'p:actryn_decode_input actryn_authority:actryn_decode length=$arg2:u64 head=+0($arg1):x8[16] tail=+142($arg1):x8[16]' >> kprobe_events
 echo 'reason == 6 || reason == 7' > events/kprobes/actryn_close/filter
 echo 'result < 0' > events/kprobes/actryn_decode/filter
 echo 'stacktrace if reason == 6 || reason == 7' > events/kprobes/actryn_close/trigger
 echo 'stacktrace if result < 0' > events/kprobes/actryn_decode/trigger
 echo 1 > events/kprobes/actryn_close/enable
 echo 1 > events/kprobes/actryn_decode/enable
 echo 1 > events/kprobes/actryn_decode_input/enable
 echo 1 > tracing_on
 ;;
stop)
 echo 0 > tracing_on
 cat trace
 echo 0 > events/kprobes/actryn_close/enable
 echo 0 > events/kprobes/actryn_decode/enable
 echo 0 > events/kprobes/actryn_decode_input/enable
 echo '!stacktrace' > events/kprobes/actryn_close/trigger
 echo '!stacktrace' > events/kprobes/actryn_decode/trigger
 echo '-:actryn_close' >> kprobe_events
 echo '-:actryn_decode' >> kprobe_events
 echo '-:actryn_decode_input' >> kprobe_events
 ;;
*) echo "usage: $0 start|stop" >&2; exit 2;;
esac
