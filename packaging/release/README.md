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
Robot enrollment and authority preparation remain separate operator procedures;
do not substitute the server recipe for robot setup. Serverd supports only these
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

After trusted robot quiescence and service stop, explicitly unload the old module.
Only then may `resume` clear the installation gate. It does **not** infer
quiescence from unloading. Next load the exact signed
`/opt/actryn/robot/current/module/actryn_authority.ko` explicitly and explicitly
start the manager and then gateway units. Resume never loads a module or starts a
service itself. Server resume likewise only permits a later explicit unit start.

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
