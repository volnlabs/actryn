# Diagnostic9 BIND reply retention — source preparation only

`bind9.render(source)` accepts C text only when its SHA-256 is
`c94c29729272ef19ed94d7777ea0fd3ddea5b162b44344eefa1e53c550ef6b32`,
the identical frozen amendment7/C03 workload. It returns new C text and performs
no file, build, process, socket, device or campaign action. No CLI is needed.
The original workload, campaign, manifests, binaries and frozen pins stay intact.

The derivative captures the existing userspace BIND reply once. On a nonzero
`reply.error` only, the existing bounded journal writer emits one JSON record:

```json
{"type":"bind_failure","diagnostic":9,"phase":"userspace_bind_reply","scope":"trial_setup","trial":6,"role":2,"reply_error":-16}
```

The values above are a **host-fake example**, not the observed B3 role/error.
The raw signed reply value is retained instead of ambient `errno`. Parent setup
uses scope `parent_setup` and `trial:null`; the four child binds use `trial_setup`
and their existing trial number. All six call sites keep their original order.
The same `assert(!reply.error)` follows the failure record. There is no retry,
new exchange or success-path logging. Malformed/truncated replies still fail
the unchanged `exchange` framing assertion before a BIND error can be claimed.
The kernel ioctl branch is unchanged.

With the fixed scopes, roles and ten-trial loop, each failure record is below
256 bytes. A child abort permits at most one such row per trial; a parent setup
abort permits one row before any trial. The existing parent journal sync after
each trial is unchanged. The writer adds no sync, clock query, timing allowance
or durability guarantee beyond the existing workload. Failed writes or missing
records remain missing evidence. All other C text is byte-identical, including
HELLO/sample deadlines, alarms, trial schedule, allocation and retirement logic.

The five host tests derive c94 from the existing pure amendment7 transformer,
then compile the actual returned C through `bind9_fake.c`. Strict C11/O2/
Wall/Wextra/Werror and linker wrappers for socket/connect/send/poll/recv exercise
the real bind function while writing only temporary journal/call files. No
workload main, authority guard, real socket or device is invoked; core dumps are
disabled. Checks cover signed numeric roles/errors, parent/trial identity,
same SIGABRT and single exchange, silent success, malformed replies and exact
deterministic source boundaries. Run from this directory:

```sh
python3 -B -m unittest bind9_test
```

A future native diagnostic build needs a separately reviewed diagnostic9
manifest/label binding this base, derived source and actual new binary hash.
The approved workload binary `40f75fe9…42398` and C03 four-artifact cohort cannot
silently admit that new hash. Do not edit C03 or relax its validators to run it.
No ARM build, target run or experiment is supplied here. B3 remains FAILED,
its role/error/cause remain unobserved, and all original80 comparison trials
and20 excluded pilot trials retain their status. Future diagnostic observations
cannot backfill historical cause or reuse the old comparison metrics.
