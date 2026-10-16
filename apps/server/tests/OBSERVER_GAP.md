# Installed server observer readiness, death and loss

**Source prepared; actual campaign NOT_RUN.** This opt-in campaign exercises the
installed production server, launcher and fixed BPF observer in a disposable
Debian 13.7 amd64 QEMU guest. It changes no binary, BPF object, unit, configuration,
policy limit or artifact. It launches no VM and makes no Robot or provider call.
Actual execution is separately scheduled by the parent/operator.

The approved platform contract permits an existing isolated attempt to finish
after diagnostic-reader loss. Observer death therefore establishes incomplete
diagnostic evidence, not an unknown application outcome or automatic termination.
Each running case observes the durable diagnostic gap first, then sends one
explicit operator cancellation. Enforcement remains the installed namespace,
seccomp and cgroup policy throughout. No diagnostic event is called a policy denial.

## Inputs and preflight

Copy `guest_observer_gap.py` and its unchanged `guest_capacity.py` helper side by
side into a protected directory on the selected disposable guest. Pass an exact
machine ID, current boot UUID, immutable server manifest digest and the approved
credential-free offline OCI digest. The harness checks Debian 13.7,
`6.12.111+deb13-amd64`, x86-64, installation guest hostname, manifest-byte hash,
fixed CLI/BPF managed links, loaded service executable paths and hashes, and
observer thread capability removal. The actual configuration validator runs before
faults. The selected profile uses operator UID 1000 and whole-disk I/O device
`254:0`; it needs no passwd entry for that numeric operator.

The preserved server03 machine ID is `14fea5c769be49d59a0f79d2049d16f4` and its
original installed manifest is
`0f2ea983181abfbcca5a3edffe9d34ebd34f7b129039d8c1f55b95eae278f4bc`.
These are historical source-preparation inputs, not fresh guest readbacks. The
parent must confirm the chosen guest and current boot/payload before execution.
No live service is contacted during source preparation.

All prior attempts must be reaped, no containerd task may exist, and each store
must have room for the three new retained attempt identities. Output must be a
new private `/var/tmp/actryn-observer-gap-*` directory. Retained old attempts,
evidence, state and immutable slots are preserved. Source/helper hashes, command
intents, original replies, return codes and monotonic fault times are retained.

## Three separate cases

1. **Before start:** prepare the original OCI task with verified healthy observer
   coverage. Verify containerd reports **CREATED**, the original prepared PID is
   unchanged and application logs are empty. Stop the actual observer once and
   confirm its pinned process has exited. Send one launch request; it must fail
   specifically because of the observer, with no RUNNING task or application
   output. A created runtime task is not claimed absent. Explicitly start the
   observer once, then cancel once and inspect cleanup. Broker `start_rejected`
   and launcher `cancelled` remain distinct terminal outcomes. No launch retry.
2. **Running observer death:** launch one new normal offline attempt and retain
   its exact one original stdout result and RUNNING PID. Obtain a pidfd for the
   hash-verified observer and recheck its PID/start identity before one SIGKILL.
   Require confirmed old-process exit and `observer_unavailable` rows visible
   through separate read-only SQLite connections to both stores. systemd may
   restart the observer according to its existing unit; that is a new collector,
   not continuity of the old registration. One explicit service-start/readiness
   step verifies the replacement; it does not relaunch an agent. Cancel once.
3. **Actual loss:** launch another normal offline attempt. Reuse the reviewed
   `tests/observer/guest.py` mechanism: a trusted test helper performs exactly
   30,000 `/dev/null` opens inside the exact original attempt cgroup. The parent
   checks the helper's PID/start/cgroup identity before releasing its stdin gate;
   the cgroup inode is checked again before entry. The helper has a 15-second
   alarm, bounded waits/output and a bounded kill/reap path. It is a trusted test
   workload, not agent-generated activity or an isolation claim. Actual original-
   epoch health must report `lost > 0` and `ready == false`; both stores must
   retain the diagnostic gap. If this fixed workload produces no loss, the case
   fails: no increased loop, reader pause, modified limit or fault escalation.
   Cancel once and require the old-epoch synced retirement summary to retain loss.

Each case uses one fault and at most one operator cancel. Lost cancellation
acknowledgements are retained, then only read-only status/store/task/cgroup polls
determine whether cleanup converged. No failed launch, cancel, fault, service
start or workload is retried. The campaign has one 240-second absolute deadline;
read-only polls check it before and after a read, so a late terminal result cannot
turn an expired phase into success. Individual command waits have smaller bounds.

## Evidence and limits

Each final export needs exactly six unique canonical hash-verified artifacts,
the original runtime binding, closed settled ordinary call (none before start),
empty cgroup, complete local resource capture and unchanged raw application logs.
Running fault cases must retain the precise diagnostic gap in their broker
artifact and an explicit omission. Readiness/epoch/loss checks reject a healthy
replacement being used as evidence of continuous old-collector coverage.

The old observer JSONL files remain under their original collector epoch. Death
and pre-start-stop cannot supply a final old-epoch synced summary; their raw
prefix/tail and durability remain explicitly uncertain. A normal local log drain
may still be complete. The loss case requires the actual synced summary, retained
byte count and monotonically nondecreasing source-loss frontier. All complete raw
trace records must match boot, attempt, cgroup, collector epoch and tracepoint
origin. Raw event delivery can be out of order across CPUs; the original order is
preserved and reported, not misclassified as a sequence loss or sorted away.

Successful cleanup leaves no containerd tasks/cgroups, exactly the three new
retained attempt IDs, and no automatic agent reexecution. Exports remain metadata
only and execution-replay-ineligible. This campaign does not measure BPF overhead,
claim hard timing bounds, exhaust observer registration capacity, inject disk
failure, qualify physical actuation or close the entire D2/A16 acceptance gate.

On failure, `FAILED` records which faults/cancels/restorations were attempted.
There is no hidden service restoration or repeated cleanup mutation. Preserve the
guest disk, both databases, output and `/var/lib/actryn-observer` prefixes; the
operator reviews the recorded exact handles before explicit recovery. This may
leave an observer stopped or an attempt charged. The parent retains a separate
overall campaign watchdog and owns VM lifecycle; storage failure is not a measured
finite fsync guarantee.

## Verification and actual invocation

Host checks (no guest/service actions):

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s apps/server/tests -p test_guest_observer_gap.py -v
python3 apps/server/tests/guest_observer_gap.py --help
```

Only after parent review and explicit disposable-guest scheduling:

```sh
python3 /PROTECTED/TESTS/guest_observer_gap.py --allow-disposable-guest \
  --machine-id VERIFIED_MACHINE_ID --boot-id VERIFIED_CURRENT_BOOT_UUID \
  --manifest VERIFIED_SERVER_MANIFEST_SHA256 \
  --artifact sha256:c3013959f5cca4a2275fa5f26de6f030dcc011241dbbe5961993a406e2e53d45 \
  --output /var/tmp/actryn-observer-gap-01
```

Neither example was executed against a guest during preparation.
