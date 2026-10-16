# Installed-server capacity campaign

`guest_capacity.py` runs only as root on a disposable `actryn-install-server*`
guest with the pinned Debian kernel. It requires a completed installation and
bootstrap, all three services running from the supplied immutable manifest, the
already imported offline artifact, and no outstanding attempt in either store.
It installs nothing and changes no policy or resource limit.

It prepares one attempt, verifies a second preparation is rejected, then starts
the first. With that agent running, it prepares a second attempt and verifies
both another preparation and a second active launch are rejected. The original
PID/start time, running outcome and single attested proposal must remain intact.
Cancelling the staged attempt permits one replacement preparation. Every known
attempt is explicitly cancelled once, reaped in both stores and exported with
independent artifact hashes; denied requests must leave no extra accounting.
The complete prepared runtime binding is retained before any launch and compared
with every later active/export inspection. Service executables must resolve to
the supplied immutable slot and match its manifest hashes. The original active
stdout bytes, PID and start ticks must survive each denied request unchanged.

Each final export must use `actryn.server.evidence.v1`, have exactly six unique
artifacts (`attempt`, `runtime_binding`, `runtime_facts`, `stdout`, `stderr`,
`broker`), no omissions and `execution_replay_eligible=false`. Hash/length checks
are necessary but insufficient: the terminal identity/digest must match the
prepared binding and independent current inspection; both stores must be reaped
and the cgroup absent. The selected isolation snapshot, healthy same-epoch
observer coverage, final empty-descendant counters, loss-free unregister summary
and bounded retained raw trace must agree. The trace's hash is recorded without
claiming complete-episode coverage. Both log descriptors must be complete and
nontruncated and match independent bounded raw-file hashes/tails. The active
attempt retains one closed, settled offline call and its single original stdout
record; cancelled preparations retain no calls or output. Denials, gaps, missing
resources, unknown outcomes or unexpected Robot delegation fail this campaign.

Run the host predicates before copying the script to the reviewed guest:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s apps/server/tests -p test_guest_capacity.py -v
```

Inside that guest, using the reviewed actual pins and a fresh output directory:

```sh
python3 guest_capacity.py --artifact "$OFFLINE_ARTIFACT_DIGEST" \
  --manifest "$INSTALLED_MANIFEST_SHA256" \
  --output /var/tmp/actryn-server-capacity01
```

Coordinate a quiet window with other campaigns. The harness retains every CLI
intent/reply and failure. It never retries a mutation, including cancellation
after a lost reply; cleanup polls retained identities. A preparation whose reply
is lost may have an unknown ID and requires separate read-only inspection.
Every failed run remains a failure even if cleanup later completes.

Host regressions include the observed false-PASS case of an empty artifact list,
correctly rehashed but semantically conflicting evidence, incomplete raw logs,
changed observer epochs/loss, open publication, unexpected dispatch, and bounded
non-following evidence readers. The complete validator also accepted the
separately retained actual installed-server03 export/raw logs/observer summary
and post-restart inspection without a new guest operation. This is not an actual
execution result for the capacity campaign itself; that campaign remains
`NOT_RUN` until the integration owner executes it once on the reviewed guest.

This covers actual preparation/active capacity and cleanup while slots are full.
It does not inject delayed retirement, broker call pressure, unresolved external
work, storage failure or physical actuation, and does not close all of A08.
