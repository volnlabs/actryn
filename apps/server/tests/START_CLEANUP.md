# Pre-Start cleanup regression: scratch guest only

This extends `guest_launcher.py` with real runtime failures before the existing
healthy Prepare/Start/Stop control. The old-f32 missing-broker case produced the
expected RED: Start rejected while the attempt remained prepared. Its known
fixture Stop reaped the attempt without output; the observer and positive cases
were unstarted. The frozen RED source and raw failure remain preserved. The
fixed-binary GREEN02 passed the missing-broker case, then failed an overstrict
physical-cgroup-path assertion in the observer case. Its exact socket restoration
and known Stop reaped the attempt; the healthy/admission cases were unstarted.
That failure stays preserved. This corrected fixture is **NOT_RUN** until Root
executes it on a separately bound disposable guest.

**Never run this harness on the retained qualification Server, Robot, A16 VM,
or an operator workstation.** Use a fresh scratch Server VM or a guarded clone
with separate writable disk, unit, ports, serial and QMP. A clone changes its
own copied history; it must never share a writable block/backend with the master.
All packaged Actryn launcher/serverd instances must be stopped. Only the real
observer and containerd dependencies are required before this direct-launcher
test. Root must own their setup and the bounded test process/cleanup.

The existing harness overwrites `/etc/actryn/server.json`, selects server UID991
and operator UID1000, creates `/var/lib/actryn-test-rootfs`, compiles the static
`launcher_agent.c`, imports a test OCI, opens the real Launcher store/cgroups and
broker directories, changes service-state ownership through Launcher setup, and
overwrites `/root/actryn-launcher-test.log`. A copy is disposable, not a baseline
to promote or copy back. No production test RPC, mock runtime or injected policy
API is added.

Stage `guest_launcher.py`, `guest_artifact.py` and `launcher_agent.c` together.
An optional final argument selects a Root-bound, already approved fixture digest.
It requires the sole exact fixture configuration and reuses its verified registry
tree. This mode skips compilation, configuration writes and import, and prints a
retained-artifact marker. Root must bind its original source/build/import evidence;
the new run is not a fresh agent build. This avoids consuming another registry
slot when numbered source paths change C assertion strings. Capacity and retained
trees must not be changed to make a regression fit.

The existing invocation is:

```
python3 -B -E -s /root/actryn-prestart-cleanup-green01/guest_launcher.py \
  /absolute/path/to/reviewed/actryn-launcher \
  /absolute/path/to/reviewed/importer-wrapper \
  /absolute/path/to/build_oci.py
```

The importer must accept `import --layout PATH --digest DIGEST`; the OCI builder
must accept `--agent PATH --out PATH`. Do not assume `/usr/bin/actryn` directly
implements that older wrapper interface. Root binds exact staged hashes and
actual wrapper/old-ELF paths before running the harness. Use the old launcher
SHA `17a0d39250fb67c20b3397ddeeb5201cbd0f650426e06a12bcae918362996b24`
for RED, without rebuilding or changing it.

The failures target these real behaviors:

| Case | Required observation | Break caught |
|---|---|---|
| Missing broker listener | Prepare succeeds; Start returns error; retained inspection becomes retiring/reaped, the original task pidfd becomes dead, cgroup/broker directory disappear and stdout/stderr stay empty. Starting the failed ID again is rejected. | Safety error returns while the task stays prepared until its default 60-second expiry. |
| Unreachable observer | After fresh Prepare and a broker listener, temporarily rename the protected observer socket. Start must reject and cancel. After task pidfd death, a fresh inspection must retain the exact ID/binding, retiring state and cancelled outcome while unregister is unavailable; output stays empty. Restore the exact socket, then wait for reap/removal and reject the old ID. | Health failure returns without cancellation/cleanup or releases durable cleanup accounting before observer closure. |
| Healthy positive | A third fresh Prepare runs the unchanged agent marker/fork fixture, then Stop reaps descendants and rejects replay. | Failure cleanup poisons subsequent healthy preparation or permits repeated execution. |
| Admission preservation | While the positive task runs, duplicate Start is rejected without changing it. A fourth fresh Prepare has a real broker listener; active-capacity Start refusal preserves its exact preparation and empty output. Stop reaps only the staged task while the first task's pidfd stays alive. | Verification cleanup wrongly cancels an admission refusal or duplicate running Start. |

The observer test renames only `/run/actryn/observer.sock` to an exclusive fixed
backup and restores it in `finally`. Restoration checks the same device/inode,
socket type/mode/owner/group/link count and refuses to overwrite another path.
Rename necessarily changes socket ctime; unchanged ctime is not claimed. No
observer stop/restart/kill or synthetic response is used. The retiring state is
a charged live registration under `Store::prepare`'s non-reaped accounting;
this test does not claim a separate global-capacity exhaustion result.
The durable non-reaped row and binding retain that admission charge, independently
of the physical cgroup directory. Runtime task deletion may remove an empty
cgroup before observer unregister succeeds; directory presence is not the charge
predicate. GREEN02 observed an absent path, but did not trace its removal actor.

The first missing-broker case should produce RED promptly on the unchanged old
launcher: its printed `prestart-rejected` inspection stays `prepared`, so the
state assertion fails. The failure is retained before the existing fixture
`finally` attempts one Stop for its known attempt and terminates its own child.
The script stops there; observer/positive cases are then unstarted, not passed.
An uncertain RPC or failed restoration remains failure/unknown; Root must retain
its output and inspect the scratch guest, never rerun the old scenario blindly.

This test targets safety-check failures. The common asynchronous verification
path cancels and attempts cleanup on approval, binding, observer or broker-socket
failure. The prepared-state guard runs first, and `Store::start` admission errors
stay outside that cleanup path. The live admission case above and the separate
`guest_capacity.py` contract require the second preparation and running task to
survive a normal active-capacity refusal.
The CLI `server launch` maps to `Request::Start` through the server socket;
`service.rs` forwards it to the restricted Launcher and closes publication on
Start error. These tests intentionally exercise that Launcher's cleanup directly;
they do not count as a new positive CLI/frontend or complete Broker campaign.

Source/syntax inspection and host Rust tests are not fixed-binary guest GREEN.
The actual old-f32 RED is bound by
`artifacts/server-prestart-cleanup-root-review01/old-red-classification.json`;
its original source is retained under
`artifacts/server-start-cleanup-regression-source-custody01`. These scratch tests
do not establish whole D2 acceptance or physical qualification. The separate
GREEN02 classification is retained at
`artifacts/server-prestart-cleanup-green-root-review02/green02-classification.json`;
its original failed program is not relabelled by this fixture correction.
