# Immutable software-preview bundles

This tooling builds deterministic role-specific candidates and installs a signed,
qualified tuple into immutable slots. It does not download, build, sign, start
services, load modules, grant, rearm, restore a database or resend operations.
Original userspace is Apache-2.0; the authority module and its corresponding
source are GPL-2.0-only. Supply reviewed third-party notices as an input.

**Release identity and qualification remain external inputs.** No production key
is generated or shipped. The example is incomplete and cannot be promoted.
Tests use disposable Ed25519 keys and synthetic ELF/filesystem artifacts. They
establish installer decisions, not actual kernel/module acceptance, crash-media
survival, independent installation, or physical actuation.

## Build and verify

Use Python 3.13 on the selected Debian 13.7 target and installed OpenSSL with
Ed25519 `pkeyutl -rawin`. The Python scripts use only the standard library.
Copy `inputs.example.json`, replace every placeholder and supply *all* required
role paths. The root integration owner supplies actual build and qualification
pins. The release builder never guesses a missing artifact or hashes an
unselected file to invent an approval.

```sh
python3 -B -E -s packaging/release/release.py build --spec inputs.json --out candidate
python3 -B -E -s packaging/release/release.py inspect --bundle candidate
```

`source` is a local file and `sha256` is its independently selected lowercase
64-digit digest. Every input, including binaries, module, profile, units,
installer/preflight scripts, Python SDK and license/provenance inputs, is checked
before creating the candidate directory. Build-source hardlinks are read-only snapshots
(Cargo commonly uses them); bundle, installed and signature inputs must be single-link files. The builder checks the complete role
allowlist, ELF architecture (including the server EM_BPF=247 relocatable observer
object), module `.modinfo` kernel/license and GNU build-id,
fixed compatibility revisions and size bounds. Source revision, compiler,
build-input file and qualification evidence hashes are mandatory manifest fields.
Metadata and license claims still depend on the trusted release review.

Outputs are a canonical sorted JSON manifest and USTAR payload with fixed order,
mode, time, uid/gid and empty owner names. Inputs with different paths/mtimes but
identical selected bytes produce identical output. Unknown paths, device files,
archive links, duplicate JSON/archive fields, unknown archive metadata and trailing bytes
reject. No archive member is extracted by an unrestricted archive extractor.

The external release custodian signs the exact `manifest.json` bytes using its
existing Ed25519 key and supplies `signature.ed25519` and the public key. Example
commands describe the interface; do not create an ad hoc release identity:

```sh
openssl pkeyutl -sign -rawin -inkey EXTERNALLY_MANAGED_ED25519_KEY \
  -in candidate/manifest.json -out candidate/signature.ed25519
openssl pkey -pubin -in release-public.pem -outform DER | sha256sum
python3 -B -E -s packaging/release/release.py inspect --bundle candidate \
  --public-key release-public.pem --key-sha256 EXTERNALLY_VERIFIED_SPKI_SHA256
```

Trust is the externally pinned SHA-256 of the Ed25519 SubjectPublicKeyInfo DER,
not a key discovered in the candidate. Verification snapshots manifest, signature
and key into private temporary files before invoking OpenSSL; source replacement
cannot substitute different signed bytes. A signature authenticates a manifest,
not the truth of its qualification claims. `qualification=incomplete` and every
unsigned candidate report `promotable=false`; installation rejects both. A
qualified signature also does not claim physical acceptance.

A qualified manifest must name a hash-pinned `qualification-bundle` in
`provenance.evidence` and carry an explicit `custodian_attestation` containing
that same `qualification_bundle_sha256`, the manifest role, and scope
`server-independent-D2` or `robot-software-preview`, respectively. The external
custodian reviews the aggregate evidence and signs this role-scoped assertion;
the tool does not invent acceptance evidence or infer approval from arbitrary
hashes. Independent D2 server promotion does not require combined A13 acceptance.
An incomplete candidate uses `custodian_attestation: null`; its evidence can be
partial and remains visibly unqualified. The signature proves provenance only.

## Offline server assets

The server bundle requires the SDK sources and its `pyproject.toml`, exactly
`protobuf-7.36.1-py3-none-any.whl`, and `share/agent/offline-oci.tar`. Acquire the
reviewed wheel outside this tool and record its approved SHA-256; the builder
never uses PyPI or pip. It checks Name/Version, `Requires-Python: >=3.10`, universal
`py3-none-any`/purelib metadata, absence of native extensions/dependencies, bounded
ZIP entries, and safe paths. The SDK itself requires Python >=3.11 and the selected
host is Python 3.13. The server target pins `python3-venv` as an OS prerequisite.

Build the reviewed layout with the existing `packaging/agent/build_oci.py` using
its approved static amd64 agent. Wrap exactly its two metadata files and three
blobs as an uncompressed file-only USTAR, in sorted order with uid/gid/time zero;
then record the archive SHA-256 in the release input spec. One deterministic
wrapping recipe (does not import or execute the agent) is:

```python
import io, pathlib, tarfile
layout = pathlib.Path("REVIEWED_OCI_LAYOUT")
paths = [layout / "oci-layout", layout / "index.json"]
paths += sorted((layout / "blobs/sha256").iterdir())
assert len(paths) == 5
with tarfile.open("offline-oci.tar", "x", format=tarfile.USTAR_FORMAT) as archive:
    for path in sorted(paths):
        assert path.is_file() and not path.is_symlink()
        data = path.read_bytes()
        header = tarfile.TarInfo(path.relative_to(layout).as_posix())
        header.size, header.mode = len(data), 0o644
        header.uid = header.gid = header.mtime = 0
        archive.addfile(header, io.BytesIO(data))
```

The builder verifies OCI layout/index/manifest versions, all blob descriptors,
actual SHA-256 and sizes, fixed amd64/offline process configuration, layer
allowlist, static ELF and bounded JSON assets. It never extracts or imports the
asset. Full runtime approval still uses the existing artifact importer. The
selected OCI manifest digest is the sole descriptor in the verified `index.json`.
After explicitly unpacking the verified archive into a new protected staging
directory, import using that digest and the existing local `actryn server import`.
No service or agent starts as a side effect of packaging or installation.

A developer can explicitly create a local venv using installed `python3-venv`,
install the shipped protobuf wheel with `pip --no-index --no-deps`, and set
`PYTHONPATH=/opt/actryn/server/current/share/sdk` to use the SDK. The installer
never runs pip. SDK build-backend tooling is not needed for this source-path use;
creating a distributable SDK wheel is a separate build step.

Run this as the developer in a new writable working directory, outside the slot:

```sh
set -e
test ! -e .venv
python3 -m venv .venv
.venv/bin/python -m pip install --no-index --no-deps \
  /opt/actryn/server/current/share/wheels/protobuf-7.36.1-py3-none-any.whl
export PYTHONPATH=/opt/actryn/server/current/share/sdk
.venv/bin/python -c 'from actryn import Client, RequestHandle'
```

The SDK and wheel exist only in the server payload. Both roles contain the native
`bin/actryn` CLI and this `share/docs/INSTALL.md`. A separate SDK client needs its
own reviewed dependency provisioning. `pip install .` is a source-development
build requiring separately supplied setuptools 82.0.0; the bundle does not ship
that build backend or require it for the source-path procedure above.

## Host prerequisites and maintenance

The only supported tuples are Debian **13.7**, amd64 server and ARM64 QEMU
`linux,dummy-virt` robot, kernel **6.12.111+deb13-{amd64,arm64}**, kernel package
**6.12.111-1**, RPC1/UAPI1/wire2/state-schema1. The manifest supplies exact
vmlinuz/config SHA-256 and package versions, including Python, OpenSSL and systemd;
the server additionally requires containerd **1.7.24~ds1-6+deb13u1** and runc
**1.1.15+ds1-2+b4**. Host version, machine/kernel, kernel files and every package
pin are verified before creating installer state or changing services. Robot also
requires `systemd-detect-virt=qemu`; other hardware is unsupported. Image SHA-512
is retained as build provenance; an in-guest installer cannot rehash its original
qcow2 image, so image identity requires the independent release/bootstrap check.

This installer assumes **exclusive trusted LOCAL operator/root maintenance**.
There is no atomic exclusion of a concurrent privileged operator issuing new
commands between its Describe check and service stop. Do not run normal operator
workflows concurrently. This is the project's trusted-Linux boundary, not hostile
root isolation.

For an existing robot, first explicitly revoke/retire/recover through the local
operator route. The installer requires the actual manager's Describe result to
show state0, operation0, HANDSHAKEN only, no prepared instance, no pending
recovery and `recovery_ready=true`. Missing/failed runtime recovery readiness
rejects even when a kernel HELLO_ACK is present; cumulative event-loss history
is preserved and does not silently become a successful runtime handshake. It never treats module absence as proof of downstream quiescence.
Fresh robot installation is allowed only with all role services inactive, no
loaded authority module, and the exact non-actuating QEMU target check. Server
maintenance requires its role services stopped and no tasks in containerd's
`actryn` namespace. Cleanup/reconciliation and existing unknown debit/state rules
remain the manager's responsibility.

## Stage, switch, recover and rollback

**Do not run these commands on a development host.** The integration owner must
first exercise them on fresh disposable supported guests. The temporary-filesystem
tests below do not perform an actual installation.

Each action requires the signed bundle, separately provided public key, externally
verified fingerprint and explicit role:

```sh
python3 -B -E -s packaging/release/release.py stage --role robot --bundle candidate \
  --public-key release-public.pem --key-sha256 VERIFIED_FINGERPRINT
python3 -B -E -s packaging/release/release.py activate --role robot --bundle candidate \
  --public-key release-public.pem --key-sha256 VERIFIED_FINGERPRINT
# After an interrupted action, inspect retained state, then explicitly finish:
python3 -B -E -s packaging/release/release.py recover --role robot --bundle candidate \
  --public-key release-public.pem --key-sha256 VERIFIED_FINGERPRINT
# Select an already retained, compatible slot; never restore its old state:
python3 -B -E -s packaging/release/release.py rollback --role robot --bundle OLD_BUNDLE \
  --public-key release-public.pem --key-sha256 VERIFIED_FINGERPRINT
```

Layout:

- `/opt/actryn/ROLE/releases/MANIFEST_SHA256`: signed bundle, public signer and
  complete verified payload; no user state, credentials or grants.
- `/opt/actryn/ROLE/current`: atomic pointer to that slot's `payload` directory.
- `/var/lib/actryn-install/ROLE`: installer lock, journal, externally selected
  public-key trust pin, maintenance record and persistent `INHIBITED` gate.
- Stable binary/unit/sysusers/tmpfiles/module links resolve through the role's
  current pointer. Server never publishes robot binaries, kernel or robot policy.

Preflight rejects a mismatch before mutation. Once mutation begins, the persistent
inhibitor is synced before any service stop or tuple switch. Unit drop-ins prevent
service startup while inhibited. The installer then stops services, stages and
syncs *all* payload files, verifies again, publishes the complete slot, and changes
one pointer. It never automatically starts services. A power/process interruption
may retain an old or new complete pointer and partial private staging, with the
gate still preventing startup. `recover` reconstructs only the named
installer-owned incomplete slot. It never deletes a published slot, evidence,
identity, database, secret or prior outcome. A retained maintenance record permits
finishing the same inhibited/stopped maintenance after the manager has stopped;
production still verifies the services are inactive.

All current and selected slots are reverified, including extracted bytes/modes.
A corrupt installed tuple fails closed; do not silently recreate it. Rollback
requires an existing verified slot with the same supported state schema/ABI and
externally pinned signer. There is no database rollback. Unknown outcomes remain
unknown; stale namespaces/grants cannot be recreated. Other schema versions,
automatic migrations, signing-key rotation and unmanaged previous installations
require a separately reviewed procedure and are rejected.

Limits: 64 manifest entries, 64 MiB per input, 256 MiB total payload, three retained
slots per role, finite journal/manifest/package/evidence counts. Incomplete slots
remain charged. Capacity exhaustion rejects further staging; explicit retention
management is external, and never deletes runtime evidence to make room. Tar
copies plus extracted payload are included in the finite installer disk budget.

## Explicit bootstrap and startup

Installation preserves every existing `/etc/actryn` configuration, approval map,
identity/key/revocation file and `/var/lib` runtime/evidence/database byte. It does
not allocate local UIDs, overwrite configurations, enroll or import an agent.
On a fresh server installation, use the complete independent-server recipe below.
Use the fresh-Robot recipe below for Robot account/configuration setup and explicit
enrollment/authority preparation. Do not substitute the server recipe. Serverd supports only these
optional credential drop-ins, each exactly `[Service]\n` followed by the stated
line and a final newline:

- `50-openai-credential.conf` uses
  `LoadCredential=openai-api-key:/etc/actryn/credentials/openai-api-key`.
- `50-robot-credential.conf` uses
  `LoadCredential=robot-client-key:/etc/actryn/credentials/robot-client-key`.

They reference locally installed secrets; drop-in bytes and secrets are never
packaged, regenerated or overwritten. Public `/etc/actryn/robot-peer.json` is
optional for an independent server and required only when binding a robot; the
daemon validates it. It remains local configuration. Other unit overrides fail closed.
Server also requires its pinned tmpfiles/cgroup setup and an explicit verified OCI import. Robot needs its QEMU
DTB at guest boot; installation never changes boot firmware or a running DTB.
No credentials, mutable configuration or automatic activation route belongs in a
bundle. These local operator steps are required before `resume`. Resume/startup verify
the configured service UID against the actual named noninteractive sysusers
account and group; they never silently rewrite an identity mismatch. Server
resume/startup additionally invokes the installed `actryn-serverd --check-config`
route after these checks. It runs the daemon's actual `LauncherConfig::read`
validation, including I/O-device syntax and approved artifact properties, without
binding listeners, opening accounting databases, acquiring the daemon lock or
starting work. Failure leaves the installation gate in place during resume.

### Fresh independent server: explicit local bootstrap

Run this as trusted root on the selected disposable Debian server **after** a
successful `stage` and `activate`, with all three Actryn units inactive and the
installation gate present. Install the manifest's exact package prerequisites
beforehand using authenticated OS repositories. This procedure neither upgrades
packages nor downloads artifacts. Require `containerd.service` active. Do not use
this fresh-only recipe to overwrite an existing configuration or layout.

Set these values from the externally reviewed candidate, not a key discovered in
the candidate. The OCI digest is the selected OCI manifest digest, not the hash
of `offline-oci.tar`. The numeric operator UID/GID 1000 need not have a passwd
entry; choose and document another numeric operator identity before configuration
if 1000 is inappropriate for the selected host.

```sh
set -eu
export ACTRYN_BUNDLE=/ROOT_PROTECTED_PATH/candidate
export ACTRYN_PUBLIC_KEY=/ROOT_PROTECTED_PATH/release-public.pem
export ACTRYN_KEY_SHA256=EXTERNALLY_VERIFIED_SPKI_SHA256
export ACTRYN_OCI_DIGEST=sha256:EXTERNALLY_SELECTED_64_HEX_OCI_MANIFEST_DIGEST
/usr/bin/python3 -B -E -s /opt/actryn/server/current/tools/release.py inspect \
  --bundle "$ACTRYN_BUNDLE" --public-key "$ACTRYN_PUBLIC_KEY" \
  --key-sha256 "$ACTRYN_KEY_SHA256"
/usr/bin/systemd-sysusers /usr/lib/sysusers.d/actryn-server.conf
/usr/bin/systemd-tmpfiles --create /usr/lib/tmpfiles.d/actryn-server.conf
```

The configuration step verifies the actual sysusers account and whole-disk I/O
device. In the tested QEMU tuple `/dev/vda` is the whole disk `254:0`; do not
substitute a partition or guess another device. Existing `/etc/actryn` ancestors
must be root-owned, non-writable by group/other and searchable by the service UID.
If a private parent blocks traversal, stop and review a separate local permission
change; never recursively relax configuration or secret permissions. This script
sets modes only on the new public directory and new public configuration.

```sh
/usr/bin/python3 -B -E -s - <<'CONFIG_PY'
import grp, json, os, pathlib, pwd, stat
account = pwd.getpwnam('actryn-server')
group = grp.getgrnam('actryn-server')
assert account.pw_uid not in (0, 1000) and account.pw_gid == group.gr_gid
assert account.pw_shell in ('/usr/sbin/nologin', '/sbin/nologin') and not group.gr_mem
device = pathlib.Path('/dev/vda').stat()
assert stat.S_ISBLK(device.st_mode)
assert (os.major(device.st_rdev), os.minor(device.st_rdev)) == (254, 0)
parent = pathlib.Path('/etc/actryn')
if not parent.exists():
    parent.mkdir(mode=0o755)
    parent.chmod(0o755)
for path in (pathlib.Path('/etc'), parent):
    info = path.lstat()
    assert stat.S_ISDIR(info.st_mode) and info.st_uid == 0
    assert not info.st_mode & 0o022 and info.st_mode & 0o001
with (parent / 'server.json').open('x') as stream:
    json.dump({'server_uid': account.pw_uid, 'operator_uid': 1000,
               'io_device': '254:0', 'artifacts': {}}, stream)
    stream.flush()
    os.fchmod(stream.fileno(), 0o644)
    os.fsync(stream.fileno())
CONFIG_PY
```

Explicitly unpack the signed, verified offline archive into a **new** protected
layout. This bounded extractor admits only the five regular OCI files, creates
no links and refuses an existing layout. The importer independently verifies the
selected digest and contents. A failure leaves the partial layout for inspection;
do not retry extraction into it or silently erase evidence.

```sh
/usr/bin/python3 -B -E -s - <<'LAYOUT_PY'
import json, os, pathlib, re, tarfile
source = pathlib.Path('/opt/actryn/server/current/share/agent/offline-oci.tar')
layout = pathlib.Path('/var/lib/actryn-install/server/offline-layout')
pin = os.environ['ACTRYN_OCI_DIGEST']
assert re.fullmatch(r'sha256:[0-9a-f]{64}', pin)
layout.mkdir(mode=0o755)
layout.chmod(0o755)
with tarfile.open(source, 'r:') as archive:
    members = archive.getmembers()
    names = [member.name for member in members]
    assert len(names) == len(set(names)) == 5
    assert {'oci-layout', 'index.json'}.issubset(names)
    assert sum(member.size for member in members) <= 64 * 1024 * 1024
    for member in members:
        assert member.isfile() and 0 <= member.size <= 16 * 1024 * 1024
        assert member.name in ('oci-layout', 'index.json') or re.fullmatch(
            r'blobs/sha256/[0-9a-f]{64}', member.name)
        target = layout / member.name
        for parent in reversed(target.parents):
            if parent == layout or layout in parent.parents:
                if not parent.exists():
                    parent.mkdir(mode=0o755)
                    parent.chmod(0o755)
        data = archive.extractfile(member).read(member.size + 1)
        assert len(data) == member.size
        with target.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), 0o644)
            os.fsync(stream.fileno())
index = json.loads((layout / 'index.json').read_bytes())
assert len(index['manifests']) == 1 and index['manifests'][0]['digest'] == pin
LAYOUT_PY
/usr/bin/actryn server import \
  --layout /var/lib/actryn-install/server/offline-layout --digest "$ACTRYN_OCI_DIGEST"
/usr/bin/actryn-serverd --check-config
```

Require `result=configuration_valid`, the expected artifact count (one for this
fresh independent-server recipe) and `authority_issued=false`. The importer owns
the approval-map update; do not write an arbitrary rootfs path into it. The fresh
configuration's empty artifact map is valid only before this explicit import.
This offline path needs no Robot peer configuration, provider key or TLS secret.

Resume clears only the installation inhibitor. Check that all units remain
inactive afterward, then explicitly start the server. Its systemd dependencies
start the matching launcher and observer. Neither action executes an agent.

```sh
/usr/bin/python3 -B -E -s /opt/actryn/server/current/tools/release.py resume \
  --role server --bundle "$ACTRYN_BUNDLE" --public-key "$ACTRYN_PUBLIC_KEY" \
  --key-sha256 "$ACTRYN_KEY_SHA256"
/usr/bin/systemctl show -p ActiveState actryn-serverd.service \
  actryn-launcher.service actryn-observer.service
# Require all three inactive, then explicitly start:
/usr/bin/systemctl start actryn-serverd.service
/usr/bin/systemctl show -p ActiveState -p SubState -p MainPID \
  actryn-serverd.service actryn-launcher.service actryn-observer.service
```

Require all services active/running with nonzero PIDs. The observer loads
`/usr/lib/actryn/observer.bpf.o` through the exact signed current-slot link. A
failed preflight or observer load is a startup failure, not permission to bypass
verification. Operator commands use installed `/usr/bin/actryn` under the
configured numeric operator identity. `server prepare --artifact DIGEST` allocates
a stopped attempt; retain its returned ID before the separate
`server launch --attempt ID`. `server status`, `server result --key preview-1` and
`server export --out NEW_PROTECTED_OUTPUT_FILE` also require `--attempt ID`.
Cancel once with `server cancel --attempt ID`, then inspect durable state and
cgroup cleanup. An independent offline proposal is not Robot authority. A lost
or timed-out mutation reply is an unknown outcome: preserve it, inspect read-only
and do not automatically resend prepare/start/cancel.

The separately retained fresh-install03 software-fixture campaign exercised
negative tuple/signature checks, interrupted publication, recovery and rollback,
then explicit bootstrap/import/start, installed observer loading, real offline
sandbox isolation, cancellation, export and explicit service restart. Restart
readbacks retained both reaped histories and the original single stdout record;
no agent reexecution was observed. The signing key and custodian assertion were
**integration fixtures**, not a release identity or qualification. This expanded
recipe records those verified actions; the earlier immutable slot retains the
earlier guide bytes and is not relabeled as containing this revision.

### Fresh Robot: explicit local bootstrap

Run the following as trusted root on the selected disposable ARM64 Robot after
successful `stage` and `activate`. Require both Robot units inactive, the module
absent and the installation gate present. The guest must already boot the selected
DTB with its `actryn,fixture-v2` serdev node and connected deterministic controller
fixture. The bundle supplies the DTB; this recipe does not alter boot configuration
or launch a controller. Physical outputs remain unavailable.

Set the bundle/key variables to the independently reviewed **Robot** candidate
and its external trust pin; do not reuse the Server bundle path by accident.
For an existing Robot, first obtain the matched inhibited recovery described
under maintenance, stop its services and explicitly unload its old module.
Module absence alone does not establish quiescence. Do not use this fresh recipe
to overwrite existing configuration or identities.

```sh
set -eu
export ACTRYN_BUNDLE=/ROOT_PROTECTED_PATH/robot-candidate
export ACTRYN_PUBLIC_KEY=/ROOT_PROTECTED_PATH/release-public.pem
export ACTRYN_KEY_SHA256=EXTERNALLY_VERIFIED_SPKI_SHA256
/usr/bin/systemd-sysusers /usr/lib/sysusers.d/actryn-robot.conf
/usr/bin/python3 -B -E -s - <<'ROBOT_CONFIG_PY'
import grp, json, os, pathlib, pwd, stat
account = pwd.getpwnam('actryn-gateway')
group = grp.getgrnam('actryn-gateway')
assert account.pw_uid not in (0, 1000) and account.pw_gid == group.gr_gid
assert account.pw_shell == '/usr/sbin/nologin' and not group.gr_mem
parent = pathlib.Path('/etc/actryn')
if not parent.exists():
    parent.mkdir(mode=0o755)
    parent.chmod(0o755)
for path in (pathlib.Path('/etc'), parent):
    info = path.lstat()
    assert stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022
with (parent / 'robot.json').open('x') as stream:
    json.dump({'operator_uid': 1000, 'gateway_uid': account.pw_uid}, stream)
    stream.flush()
    os.fchmod(stream.fileno(), 0o600)
    os.fsync(stream.fileno())
ROBOT_CONFIG_PY
/usr/bin/python3 -B -E -s /opt/actryn/robot/current/tools/release.py resume \
  --role robot --bundle "$ACTRYN_BUNDLE" --public-key "$ACTRYN_PUBLIC_KEY" \
  --key-sha256 "$ACTRYN_KEY_SHA256"
/usr/bin/systemctl show -p ActiveState actryn-robotd.service actryn-gatewayd.service
```

Choose a different numeric operator UID before creating the configuration if 1000
is inappropriate. Require both units still inactive after resume. It clears the
installation gate; it does not load the module, start services or issue authority.
Then explicitly load the signed slot module and start each service once:

```sh
wait_unit() {
  /usr/bin/python3 -B -E -s - "$1" <<'UNIT_WAIT_PY'
import subprocess, sys, time
unit = sys.argv[1]
assert unit in ('actryn-robotd.service', 'actryn-gatewayd.service')
deadline = time.monotonic() + 90
last = ''
while time.monotonic() < deadline:
    result = subprocess.run(['/usr/bin/systemctl', 'show', unit,
                             '-p', 'ActiveState', '-p', 'SubState', '-p', 'MainPID'],
                            check=True, capture_output=True, text=True,
                            timeout=max(.001, deadline - time.monotonic()))
    last = result.stdout
    state = dict(line.split('=', 1) for line in last.splitlines())
    if state['ActiveState'] == 'failed':
        raise SystemExit(last)
    if (state['ActiveState'], state['SubState']) == ('active', 'running') and int(state['MainPID']) > 0:
        print(last, end='')
        break
    time.sleep(min(.2, max(0, deadline - time.monotonic())))
else:
    raise SystemExit(f'startup timeout; inspect the existing job, do not restart: {last}')
UNIT_WAIT_PY
}
/usr/sbin/insmod /opt/actryn/robot/current/module/actryn_authority.ko
/usr/bin/systemctl start --no-block actryn-robotd.service
wait_unit actryn-robotd.service
/usr/bin/systemctl start --no-block actryn-gatewayd.service
wait_unit actryn-gatewayd.service
/usr/bin/actryn robot doctor
```

Require the signed loaded-module build-id check to pass, the root-owned mode-0600
authority device to be bound to the selected serdev node, and no `/dev/ttyAMA1`
bypass. Retain unit journals and actual executable/slot identities. The installed
signed-tuple `ExecStartPre` is part of startup: one manager11/module16 campaign
measured 21.82 s of successful gateway preflight and 25.80 s until replacement was
available under the shipped CPU quota. Those observations are not bounds or a
reason to disable preflight/resource limits. The 90 s waiter is an operator stop
condition, separate from authority, recorder and heartbeat deadlines. On failure
or timeout inspect the queued job, journal and state; do not submit another start.

### Robot enrollment and read-only readiness

Use the configured operator or root for local CLI commands. In a new private
working directory, retain each JSON response (`umask 077` and shell noclobber are
appropriate). `doctor` returns the current `robot_epoch` at the top level. Select
that value as `ROBOT_EPOCH`; a manager restart requires fresh inspection. Enrollment
keeps the device private key inside the manager:

```sh
actryn robot enroll-request --dns robot.example
# Give report.csr_pem to the chosen offline site issuer.
# Receive device.pem with the reviewed DNS identity and ca.pem through that issuer.
actryn robot enroll-install --cert device.pem --ca ca.pem
actryn robot install-principal --epoch ROBOT_EPOCH --principal developer \
  --pin CLIENT_LEAF_SHA256 --can-propose
mkdir -m 700 session
actryn robot pair --endpoint 127.0.0.1:7443 --dns robot.example \
  --pin DEVICE_LEAF_SHA256 --ca ca.pem --cert client.pem --key client.key \
  --out session/pair.json
```

The issuer also supplies the scoped client certificate/chain and its protected
private key to this operator. No issuer private key belongs in a bundle or on the
gateway. `CLIENT_LEAF_SHA256` is the reviewed client leaf DER hash;
`DEVICE_LEAF_SHA256` is the device leaf DER hash returned by local enrollment,
not the CSR SPKI hash or a value learned from an untrusted connection. Pairing
checks TLS 1.3, CA/DNS/ALPN and the explicit pin; it issues no authority.

This compact walkthrough runs client commands on the Robot operator account,
using localhost so the stable handle need not be copied between machines. For
a remote client use its reviewed numeric IP:port and maintain the same handle
custody. The CLI is shipped in both roles; certificate/key files are local inputs.

Define the following waiter in the Robot operator shell. Every iteration sends
only a read-only status request; mutations remain one-shot commands outside it:

```sh
wait_robot() {
  python3 - "$1" <<'WAIT_PY'
import json, subprocess, sys, time
phase = sys.argv[1]
limits = {'recovered': 14, 'rearmed': 8, 'prepared': 8, 'retired': 8}
deadline = time.monotonic() + limits[phase]
last = None
while time.monotonic() < deadline:
    remaining = deadline - time.monotonic()
    reply = subprocess.run(['/usr/bin/actryn', 'robot', 'status'], check=True,
                           capture_output=True, text=True, timeout=max(.001, remaining))
    last = json.loads(reply.stdout)
    assert last['result'] == 'report', last
    runtime = last['report']['runtime']
    kernel = runtime['kernel']
    ready = {
        'recovered': runtime['recovery_ready'] and not runtime['recovery_pending']
                     and runtime['prepared'] is None and kernel['state'] == 0
                     and kernel['operation_state'] == 0 and bool(kernel['flags'] & 1),
        'rearmed': kernel['state'] == 1 and bool(kernel['flags'] & 1),
        'prepared': runtime['preparation_ready'],
        'retired': runtime['retirement_ready'],
    }[phase]
    if ready and last['report']['clock_healthy'] and runtime['health']['healthy']:
        print(reply.stdout, end='')
        break
    time.sleep(min(.1, max(0, deadline - time.monotonic())))
else:
    raise SystemExit(f'{phase} readiness timeout; retain state, do not resend: {last}')
WAIT_PY
}
```

These finite operator wait bounds do not extend any production deadline. Stop on
timeout, malformed/unavailable status or unhealthy state. Preserve the response
and original handle; never resend an uncertain mutation to make a wait succeed.

### Delegated offline agent execution

This path connects the installed isolated agent, Server broker and Robot. It uses
the shipped offline OCI asset and native CLI; no provider credential, source
checkout, test harness or issuer private key is needed. Complete Robot bootstrap,
enrollment and operator pairing above first, leaving no prepared namespace or
live authority. On the Server, complete account/configuration/import setup but
install the peer inputs below **before** its explicit resume/start. If services
already ran, first close and inspect every retained attempt/debit, then stop all
three Server units for this local configuration change. Preserve existing inputs;
this recipe creates new files and refuses replacement.

The site issuer supplies a separate Server workload certificate/chain
`server-client.pem` and matching key **only to the Server**. It uses the site CA
trusted by the Robot. Obtain the workload leaf DER SHA-256 through the trusted
issuance process. On the inhibited Robot, install that public pin with proposal
scope and retain a current public description:

```sh
actryn robot install-principal --epoch ROBOT_EPOCH --principal server-broker \
  --pin SERVER_CLIENT_LEAF_SHA256 --can-propose
actryn robot doctor
```

Retain the doctor's complete JSON as `robot-description.json` and transfer this
public file to trusted Server staging. Verify its `robot_epoch`, device leaf pin,
DNS name, configuration digest and profile against the selected Robot. Do not
learn those approvals from a remote connection. The existing operator's
`session/pair.json` remains on the Robot; the Server workload key never goes there.

As root on the stopped Server, place the reviewed public description, `ca.pem`,
and `server-client.pem` in `/ROOT_PROTECTED_SITE_INPUTS`; the issuer-delivered key
is `server-client.key` in that protected Server staging directory. Set the
numeric Robot address reachable **from the Server guest**, including its reviewed
port (IPv6 uses brackets). The configuration stores exactly these eight public
fields; digest strings are bare lowercase hex, not `sha256:` strings:

```sh
set -eu
export ACTRYN_ROBOT_ENDPOINT=192.0.2.10:7443
/usr/bin/python3 -B -E -s - <<'PEER_CONFIG_PY'
import json, os, pathlib, stat
source = pathlib.Path('/ROOT_PROTECTED_SITE_INPUTS')
def read_input(name, limit):
    path = source / name
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1
    assert not info.st_mode & 0o022 and 0 < info.st_size <= limit
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    assert len(data) <= limit
    return data
def create(path, data, mode):
    with path.open('xb') as stream:
        os.fchmod(stream.fileno(), mode)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
description = json.loads(read_input('robot-description.json', 65536))
assert description['result'] == 'report'
report = description['report']
configuration = bytes(report['configuration_digest']).hex()
profile = bytes(report['profile_sha256']).hex()
assert len(configuration) == len(profile) == 64
peer = {'endpoint': os.environ['ACTRYN_ROBOT_ENDPOINT'],
        'dns_name': report['identity']['dns_name'],
        'robot_leaf_sha256': report['identity']['device_certificate_sha256'],
        'principal': 'server-broker', 'robot_configuration_digest': configuration,
        'robot_profile_digest': profile, 'ca_pem': read_input('ca.pem', 24576).decode(),
        'client_certificate_pem': read_input('server-client.pem', 24576).decode()}
encoded = json.dumps(peer).encode()
assert len(encoded) <= 65536
parent = pathlib.Path('/etc/actryn')
for path in (source, parent):
    info = path.lstat()
    assert stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022
create(parent / 'robot-peer.json', encoded, 0o644)
credentials = parent / 'credentials'
if not credentials.exists():
    credentials.mkdir(mode=0o700)
info = credentials.lstat()
assert stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o077
key_info = (source / 'server-client.key').lstat()
assert not key_info.st_mode & 0o077
create(credentials / 'robot-client-key', read_input('server-client.key', 8192), 0o600)
dropins = pathlib.Path('/etc/systemd/system/actryn-serverd.service.d')
if not dropins.exists():
    dropins.mkdir(mode=0o755)
info = dropins.lstat()
assert stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022
create(dropins / '50-robot-credential.conf',
       b'[Service]\nLoadCredential=robot-client-key:/etc/actryn/credentials/robot-client-key\n', 0o644)
PEER_CONFIG_PY
/usr/bin/systemctl daemon-reload
```

The script prints no key material. Retain the site's protected source credential
according to its custody policy; never place key bytes in arguments, public JSON,
the OCI image or evidence. On partial failure inspect the new files; do not rerun
the script to overwrite them. Complete the earlier Server resume/start checks,
requiring all three installed services active before preparing an attempt. The
allowed drop-in supplies the key only through the Server service credential.
Actual binding below verifies the peer, certificate and configuration together.

Stage the following commands in the two operator terminals before starting. The
Server preparation and binding have finite lifetimes, and the local grant lasts
30 seconds; copying IDs or pausing does not extend them. Choose one new namespace
on the Server and retain it alongside the attempt:

```sh
# Server operator:
python3 -c 'import secrets; print(secrets.token_hex(16))'
# Retain that 32-hex value as NAMESPACE_ID.
actryn server prepare --artifact sha256:REVIEWED_OFFLINE_DIGEST
# Retain inspection.attempt.id as ATTEMPT_ID.
actryn server bind-robot --attempt ATTEMPT_ID --namespace NAMESPACE_ID
```

Require `result=robot_binding`, the intended attempt/namespace,
`principal=server-broker`, and the selected manager epoch and digests. Binding
authenticates the Server workload without granting authority. If the reply is
unknown, inspect `server status --attempt ATTEMPT_ID`; never bind a replacement
namespace to evade the uncertain result. Continue only with the retained binding.

On the Robot, use its current operator pairing and exactly those public IDs. This
CLI handle selects the namespace for preparation/export; **its random key is
never submitted**. The broker will allocate and durably retain the actual operation
key. Use `wait_robot` from the preceding readiness section:

```sh
set -e
actryn robot handle --pair session/pair.json --attempt ATTEMPT_ID \
  --namespace NAMESPACE_ID --out session/delegation-namespace.json
actryn robot recover --pair session/pair.json
wait_robot recovered
actryn robot rearm --pair session/pair.json
wait_robot rearmed
actryn robot prepare --handle session/delegation-namespace.json --principal server-broker
wait_robot prepared
actryn robot grant --pair session/pair.json --duration-ms 30000
actryn robot activate --pair session/pair.json
# Server operator, immediately after local activation:
actryn server launch --attempt ATTEMPT_ID
actryn server status --attempt ATTEMPT_ID
actryn server result --attempt ATTEMPT_ID --key preview-1
actryn server robot-query --attempt ATTEMPT_ID --key preview-1
```

Review the pinned offline fixture target (left 10, right 10, duration 1000 ms) before
the grant. Launch once. The broker commits its own stable handle, obtains the
actual Robot observation, persists the proposal intent, then submits the typed
target through the kernel gate. It retains the original observation's one-second freshness bound and never
refreshes or resends an expired/uncertain request. Do not issue `robot propose`
from the namespace handle or copy the broker's key into a new submission.

Poll only `server status`, `server result` and `server robot-query` for up to 12 s;
unknown/pending/absent output is not a successful operation. The latter queries
the same remote key and updates retained reconciliation/accounting, without
dispatching again. Require the result's `value.robot_handle` to equal the
`robot-query` response's `request.handle`, with matching attempt/namespace and
`preview-1`. Retain `trusted_robot_observation`, `observation_digest` and
`lineage_digest`. After terminal controller evidence, the Robot operator may issue
one `robot reconcile --pair session/pair.json`; continue read-only inspection.
Normal success requires `request.phase=settled`, `outstanding_debit=false`, and
`last_remote` terminal/reconciled with `verdict=TargetReached` and equal positive
durable/current revisions. A published model result alone does not prove dispatch
or completion.

For interruption, use `actryn server robot-cancel --attempt ATTEMPT_ID --key preview-1`
once, including before an operation-ID reply, then inspect that same broker key.
An absent broker key may be fenced without any remote handle existing; it is not
a remote cancellation receipt. If Server transport is unavailable, the Robot
operator can revoke locally using its retained epoch/pair. Unknown remote work
remains charged until the retained outcome is reconciled; never clear databases,
replace IDs or repeat launch to escape it.

After retaining the actual broker operation outcome, close publication and export:

```sh
# Server operator: cancel the attempt once, then inspect its same identity.
actryn server cancel --attempt ATTEMPT_ID
actryn server status --attempt ATTEMPT_ID
actryn server robot-query --attempt ATTEMPT_ID --key preview-1
# Robot operator:
actryn robot retire --pair session/pair.json
wait_robot retired
actryn robot recover --pair session/pair.json
wait_robot recovered
actryn robot export --local --handle session/delegation-namespace.json --out delegated-robot-evidence
# Server operator, after reaped state and settled retained debit:
actryn server export --attempt ATTEMPT_ID --out delegated-server-evidence.json
```

Before export, inspect Server status for up to 12 s for `attempt.state=reaped` and
every retained `robot_requests[].outstanding_debit=false`; otherwise preserve
the unresolved accounting and report the failure. Robot export reads the whole
retired namespace. Its inspection snapshot for the unused preparation key is
expected to be empty; that key is not the operation. The actual broker
`robot_handle`/`robot-query` response and Server export retain the operation and
debit identities. Keep both exports and the binding/result/query responses.
This source-backed operator recipe has not itself been executed as an independent
installed walkthrough and does not close any release or physical acceptance gate.

### Manual offline proposal and explicit operator submission

This is a **manual operator-reviewed handoff** from the isolated offline agent to
the Robot CLI. It does not establish server-to-Robot broker delegation or combined
acceptance. Use the delegated offline recipe above for the installed
agent-to-broker-to-Robot path; this manual alternative is a diagnostic handoff.

After the independent Server bootstrap/import/start above, run as its configured
operator. Use the actual OCI manifest digest already imported:

```sh
actryn server prepare --artifact sha256:REVIEWED_DIGEST
# Retain inspection.attempt.id from this response as ATTEMPT_ID before launch.
actryn server launch --attempt ATTEMPT_ID
actryn server status --attempt ATTEMPT_ID
actryn server result --attempt ATTEMPT_ID --key preview-1
```

Poll only `status`/`result` for up to 30 s if the result is not ready. Retain the last
response on timeout and inspect/cancel the same attempt; never repeat prepare or
launch. The fixed offline agent keeps publication open for 60 s after its output,
within the attempt ceiling. Save the successful result in a new private
`proposal.json`, check its attempt/request identity and typed `value.output`, and
review the deltas/duration before granting. Retain the exact file on the Robot
operator's side and its SHA-256 as `PARENT_DIGEST`. The offline reference string
is diagnostic provenance; obtain a fresh Robot observation below.

Stage all reviewed inputs first. The example target must equal the reviewed
proposal; substitute its typed `LEFT`, `RIGHT` and `DURATION_MS` values. Use the
Server's retained `ATTEMPT_ID`. Pairing above authenticates the selected principal;
if its session has expired, authenticate again before preparation. Then:

```sh
set -e
actryn robot handle --pair session/pair.json --attempt ATTEMPT_ID \
  --out session/operation.json
actryn robot recover --pair session/pair.json
wait_robot recovered
actryn robot rearm --pair session/pair.json
wait_robot rearmed
actryn robot prepare --handle session/operation.json --principal developer
wait_robot prepared
actryn robot grant --pair session/pair.json --duration-ms 30000
actryn robot activate --pair session/pair.json
observation_json=$(actryn robot observe --pair session/pair.json --cert client.pem --key client.key \
  --handle session/operation.json)
observation_id=$(printf '%s\n' "$observation_json" | python3 -c \
  'import json,sys; print(json.load(sys.stdin)["observation"]["id"])')
# Submit immediately, within the observation's original freshness limit:
actryn robot propose --pair session/pair.json --cert client.pem --key client.key \
  --handle session/operation.json --observation "$observation_id" \
  --parent-digest PARENT_DIGEST --left LEFT --right RIGHT --duration-ms DURATION_MS
actryn robot query --pair session/pair.json --cert client.pem --key client.key \
  --handle session/operation.json
```

Fresh Recover starts a new inhibited clock exchange even if an old mapping is
valid; a pending recovery is inspected, not resent. Grant must fit the remaining
mapping/session/preparation lifetime and is rejected before authority mutation if
it reaches the mapping cutoff. Never grant merely because a HELLO was received.
An expired or unhealthy preparation needs explicit retirement/recovery and a new
reviewed preparation, not an automatic extension.

The CLI durably marks this handle before proposal transmission and refuses its
resubmission. Query that same handle for at most the reviewed operation duration
plus 8 s. Require a terminal snapshot, successful task verdict (`TargetReached`
for normal completion) and reconciliation separately. After terminal controller
evidence, use `actryn robot reconcile --pair session/pair.json` once and inspect
read-only status/query until `reconciled=true`; a finite wait expiring is a failure,
not proof of completion. A second operation under the same still-valid grant needs
a fresh handle key with the same attempt/namespace, a fresh observation and the
first operation reconciled. Do not Recover between those operations: it retires
the prepared namespace.

To interrupt, send `actryn robot cancel --local --handle session/operation.json`
once on the Robot, even if the initial proposal reply/operation ID was lost. Query
the same handle afterward. An unknown reply or failed cancellation does not
establish remote closure; retain the handle and use explicit local revoke if
needed. To retire the workflow and release the capture writer:

```sh
actryn robot revoke --pair session/pair.json
actryn robot retire --pair session/pair.json
wait_robot retired
actryn robot recover --pair session/pair.json
wait_robot recovered
actryn robot export --local --handle session/operation.json --out robot-evidence
# On the Server, cancel its same retained attempt if still active, then export:
actryn server cancel --attempt ATTEMPT_ID
actryn server status --attempt ATTEMPT_ID
actryn server export --attempt ATTEMPT_ID --out server-evidence.json
```

Export destinations must be new. Retain incomplete exports, raw uncertainty and
original IDs on failure. Neither software completion nor these installation
instructions establish physical qualification or close the release gates.

The installed entry is `/opt/actryn/ROLE/current/tools/release.py`; invoke it as
`/usr/bin/python3 -B -E -s /opt/actryn/ROLE/current/tools/release.py ...`.
`-B` disables bytecode writes, `-E` ignores Python environment overrides, and
`-s` excludes user site packages. The script itself also disables bytecode before
importing its sibling installer, so direct invocation cannot add `__pycache__`
to the immutable signed slot. Keep the separately verified bootstrap scripts
available: an interrupted initial publication can leave the installed CLI/current
pointer absent, and recovery must use that external trusted entry.

Every unit startup has a root, read-only `ExecStartPre` (systemd `+` prefix), with
`/usr/bin/python3 -B -E -s`, that re-verifies the
installed signed tuple, actual host pins and local configuration. Startup verification
streams archive hashes and installed files; it does not buffer the entire release
inside a service memory limit. Robot startup
also requires the loaded module's GNU build-id note to equal the signed module's
note. This is loaded-build identity, not a cryptographic measurement of all
kernel memory or protection from hostile root. Missing/wrong modules prevent
startup even if a crash follows gate removal. Preflight never loads a module,
changes runtime state, grants or rearms. Local robot recovery, explicit rearm,
fresh delegation and activation remain separate after startup.

Test with no host/guest installation:

```sh
TMPDIR=/dev/shm PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest discover -s packaging/release -v
```

Temporary-filesystem interruption tests model failures after recorded durable
boundaries. They do not establish arbitrary-media power-loss guarantees. Fresh
QEMU install/update/startup, module-note availability, unit hardening interactions,
operator repeatability and the real externally signed candidate remain open
qualification gates.

The server tuple includes `lib/observer.bpf.o`, linked immutably at the observer's
fixed `/usr/lib/actryn/observer.bpf.o` path. The matching observer C source, unchanged `bpf/Makefile` retained as
`share/source/observer.Makefile`, and GPL-2.0-only text accompany this GPL object; original userspace remains Apache-2.0.
The object is checked and hashed during building, loading and installed slot
verification. It is not generated by the installer.

Runtime shared libraries are prerequisites, not copied into the bundle. Both
roles must pin `libc6`, `libgcc-s1`, `libssl3t64`, `libexpat1`, `libzstd1` and
`zlib1g`; the server additionally pins `libelf1t64`, matching the selected
executables and the Python/OpenSSL installer tools' observed `ldd` closure and
`dpkg-query -S` ownership. Record those raw observations with build provenance
and recheck the closure when binaries change. Every selected package version is
verified before installation changes state and at startup preflight. A fresh
guest must already contain those exact packages; the installer never downloads
packages or performs an OS upgrade. These pins supplement the exact Debian,
kernel, containerd/runc and Python prerequisites.

This guide is included verbatim as the pinned `share/docs/INSTALL.md` in each
role payload, available below `/opt/actryn/ROLE/current/` after installation.

New public installation directories and payload modes are set explicitly before
syncing, independently of the caller's umask. New installer-state directories and
metadata remain 0700/0600. Existing configuration, evidence and directory modes are
preserved; installation never relaxes them to make startup succeed.
