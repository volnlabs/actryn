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

Credential preflight reads only fixed-path metadata and the POSIX access ACL,
never the private key contents. Ancestors must be root-owned directories without
group/other writes. The credential must be a bounded single-link regular file,
with either private owner-only permissions for root/the configured server UID or
the exact Debian systemd ACL route: root:root mode 0440, ACL version 2, owner read,
only the configured named server UID read, owning-group none, mask read, other
none. Extra/malformed entries, another UID, links or wider permissions reject.
Metadata is retained separately; it is not proof of key bytes or authentication.

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
`/var/lib/actryn-test-campaigns/`. It uses the installed numeric nonroot server operator UID as both UID and GID,
with supplementary groups cleared; a passwd entry is not required.
Local Robot requests check the root daemon peer and retain the exact manager epoch.
The Python SDK/protobuf dependencies and native host CLI must already be available.

The campaign records five fresh server attempts: three pre-start binding rejections
for endpoint, leaf-pin and configuration-digest mismatches; one independent unbound
agent run with a rejected late binding; and one complete delegated operation. The
negative cases temporarily replace only the fixed **public** peer configuration,
compare the expected current value before replacement, and restore it in `finally`.
Both complete read/compare/replace operations and restoration read/restore hold the
same guest `flock` on root-owned `robot-peer.acceptance.lock` beside that file.
A timed-out publication cannot be overtaken by a readback that falsely reports
the original configuration restored. Lock acquisition is bounded; a missing or
lost restoration acknowledgment writes `*-restoration-unknown.json`, aborts the
campaign and requires explicit inspection/reaping of any surviving remote holder
before manual restoration. It never reports successful restoration from an
unserialized read. Fault publication and restoration each have one retained
intent/reply identity and are never retried. Temporary raw remnants remain for
inspection. Do not run a concurrent installer or another server operator during
these cases; this fixture lock does not exclude an unrelated privileged operator.

After explicit recovery readiness, the complete path is server prepare/bind, local
Robot rearm/prepare/readiness/grant/activate, then isolated agent launch. The harness
checks the original trusted observation and lineage digests, stable request/remote
handle, fixed 10/10-tick 1,000 ms target, actual kernel identity, and a terminal,
reconciled `TargetReached` whose terminal revision is durable. Natural completion
requires kernel state 2 (Active), reason 1 (SkillFinished), operation state 4
(Reconciled), zero duties, and both handshaken bit 1 and grant-authorized bit 8
retained for normal reuse. Grant authorization is not an output-open flag. It then
closes server publication and retires the Robot namespace. Read-only `retirement_ready` must become true
before exactly one final Recover request; only recovery releases the prepared
slot. That readiness proves writer termination, not downstream reconciliation or
a known task outcome, and does not require operation state 4 globally. Subsequent
Describe polling requires no prepared slot and matched recovery readiness. The
installed manager must expose this current Report field.

Final server JSON evidence must have the exact schema and all seven artifacts
with valid hashes, no omissions, no final broker gaps/denials, and matching attempt,
artifact, guest boot, cgroup lifetime, Robot binding, original handle/observation
lineage and settled debit. The recorded runtime snapshot must independently show
UID/GID 65532, no capabilities, no-new-privileges, seccomp mode 2, private namespaces,
no network routes, a read-only root and no unexpected mounts. It must retain the
fixed memory/PID/CPU limits, an installed device enforcement program, and the fixed
I/O rates on the device read from installed configuration during preflight.
Cleanup must retain a ready observer with zero loss,
required probe coverage, the same collector epoch and monotone sequence, plus all
selected resource counters captured after descendants are empty. Complete,
untruncated stdout/stderr must match the separately retained actual log bytes,
including full hashes and bounded tails. Evidence unavailable during cleanup
fails this campaign even if earlier inspection was healthy; saved raw exports
remain available for diagnosis and are not labelled acceptance. The final Robot
capture is exported through the existing verified CLI exporter. Neither evidence
export establishes physical actuation or execution replay eligibility.

Server cancellation sends one saved mutation. A lost transport reply or an explicit
`outcome_unknown` response is preserved as uncertainty, never treated as a retry
instruction. Bounded read-only inspection then requires the CLI and both fixed
SQLite stores to report reaped, no cgroup, no publication/provider/Robot debit
left open, no evidence gaps, and a complete observer unregister summary matching
the original collector epoch, monotone sequence, retained JSONL size and zero
reported loss. Required resource snapshots must remain available. Only converged
evidence permits the campaign to continue; the original cancellation
acknowledgment remains labelled unknown. Prepared negative cases have no call row
and do not issue a Result lookup that would fabricate an absent request.

Only read-only readiness/status/query calls poll. Mutations have unique saved
intent/reply records and never retry. Any failure preserves `failure.json`, attempt
identities and earlier results, then stops; it does not silently cancel/recover or
rerun the failed campaign. Inspect the retained state and explicitly close/recover
it before a separately numbered run. A lost reply may leave an unknown outcome or
held debit. No observation is refreshed to rescue a stale model/dispatch result.

The local self-tests check evidence hashes and trusted lineage, grant-preserving
natural completion, retirement/recovery ordering, strict final evidence semantics,
restoration-unknown reporting and a real temporary-file/subprocess flock
interleaving. They do not constitute a guest run. This campaign covers one delegated offline operation.
The separate manager/kernel campaigns establish two operations under one grant,
interruption, restart and malformed/race cases. Live-provider suitability, physical
motion qualification and installation by an independent operator remain separate.
