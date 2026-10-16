# Combined offline acceptance

`guest_robot_acceptance.py` runs the installed offline OCI agent through the real
server broker, authenticated Robot manager, Linux authority module and simulated
controller fixture. It is opt-in and accepts only the pinned Debian x86/ARM guests.
Run it only after the integration owner hands over both guests and releases the
storage/CPU quiet window. It does not build, install, enroll, rotate identities,
import artifacts, restart services, or read a live-provider credential.

Prerequisites are the final matching server/Robot binaries and profile, an imported
`offline-preview-v1` artifact, active services and fixture, no existing prepared
Robot namespace, and the server-only `robot-client-key` systemd credential. Supply
the protected public peer configuration and the existing enrolled CA/client
certificate/key files. The host key stays in its supplied file. The public peer
configuration must exactly match `/etc/actryn/robot-peer.json`, including the
server-reachable numeric endpoint, device leaf pin and configuration/profile
digests. The host uses its separate forwarded endpoint for pairing and export.

```sh
python3 packaging/agent/guest_robot_acceptance.py --self-test
python3 packaging/agent/guest_robot_acceptance.py \
  --allow-disposable-guests \
  --ssh-key .cache/qemu/id_ed25519 --known-hosts .cache/qemu/known_hosts \
  --server-port 26220 --robot-port 26221 --tcp-port 27443 \
  --cli target/debug/actryn --guest-cli /usr/local/bin/actryn \
  --artifact sha256:REVIEWED_OFFLINE_MANIFEST \
  --peer-config /protected/path/robot-peer.json \
  --ca /protected/path/ca.pem --certificate /protected/path/client.pem \
  --client-key /protected/path/client.key \
  --output artifacts/combined-offline-guest01
```

The output parent must already exist, be protected against other users' writes,
and the campaign directory must be new. The
harness creates a private guest export directory under
`/var/lib/actryn-test-campaigns/`. It uses the installed nonroot server operator UID.
Local Robot requests check the root daemon peer and retain the exact manager epoch.
The Python SDK/protobuf dependencies and native host CLI must already be available.

The campaign records five fresh server attempts: three pre-start binding rejections
for endpoint, leaf-pin and configuration-digest mismatches; one independent unbound
agent run with a rejected late binding; and one complete delegated operation. The
negative cases temporarily replace only the fixed **public** peer configuration,
compare the expected current value before replacement, and restore it in `finally`.
Do not run a concurrent installer or another server operator during these cases.

After explicit recovery readiness, the complete path is server prepare/bind, local
Robot rearm/prepare/readiness/grant/activate, then isolated agent launch. The harness
checks the original trusted observation and lineage digests, stable request/remote
handle, fixed 10/10-tick 1,000 ms target, actual kernel identity, and a terminal,
reconciled `TargetReached` whose terminal revision is durable. It then closes server
publication, retires the Robot namespace, recovers, and exports both finite server
JSON evidence and the Robot capture through the verified CLI exporter.

Only read-only readiness/status/query calls poll. Mutations have unique saved
intent/reply records and never retry. Any failure preserves `failure.json`, attempt
identities and earlier results, then stops; it does not silently cancel/recover or
rerun the failed campaign. Inspect the retained state and explicitly close/recover
it before a separately numbered run. A lost reply may leave an unknown outcome or
held debit. No observation is refreshed to rescue a stale model/dispatch result.

The local self-tests check evidence hashes and trusted lineage validation; they do
not constitute a guest run. This campaign covers one delegated offline operation.
The separate manager/kernel campaigns establish two operations under one grant,
interruption, restart and malformed/race cases. Live-provider suitability, physical
motion qualification and installation by an independent operator remain separate.
