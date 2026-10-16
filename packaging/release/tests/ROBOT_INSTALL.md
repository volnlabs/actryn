# Fresh installed Robot campaign preparation

Status: **candidate03 prepared; fresh Robot installation and positive startup NOT_RUN**.
This uses the existing role-transition harness and manager lifecycle harness.
It creates no release identity, qualification, provider credential or physical
actuation claim. Every test signing key/site issuer is disposable integration
material. Keep all original prepared directories and failed campaigns immutable.

## Retained preparation inputs

The clean preparation checkout starts at root revision
`2ec9da05bce8f14caff50ad79d0eab9ca67b5600` on `test/fresh-robot-install`.
Do not replace tested components merely to make their source revisions identical.
Record this mixed-artifact fixture accurately; a coherent final release build is
separate. The selected original spec is
`artifacts/release-fixture-inputs-01/robot-inputs.json`; its old prepared campaign
`70aed90b9e80473fa9634ac6f9ce3072` must not be modified or reused as the amended
candidate.

| Input | Selection / required action |
| --- | --- |
| Manager | Reuse tested manager10, `.cache/robot-manager10/actryn-robotd`, SHA256 `c198a0f61a9c6c8709b013555cef522982a6f75b45d3efb44be6387dd31f9eb7`; recorded source `4fc5452d874a72ef1a27ebdce772cea49720b9cc`. No rebuild just for packaging. |
| Authority module | Reuse exact tested module15, SHA256 `2405de617a09b4b3beec5eaec8f83ff6ee6c0cc0a1968d091b0c5634fcff8e1e`; retained input is `inputs/robot/module/actryn_authority.ko` below the original assembly. Original guest build path `/root/actryn-kernel-build15/kernel/actryn_authority.ko` is provenance, **not** the installed load path. |
| Module source | Preserve corresponding retained `share/source/kernel.tar`, SHA256 `c8fed52dab214d59773d4209aa3086680dd49a969092494bede737cb30161c67`; source/build provenance and GPL text accompany it. No complete-corresponding-source legal assurance is inferred. |
| ARM CLI | Fresh locked/offline single-job build from `2ec9da0` passed; original debug SHA256 `258925b0501cd8dd725413f127da67f479f939fe0af644085e9f07d991669687`, private strip-copy SHA256 `2e65aa208d1c70c812d9da8dfc9a6e0facfa1913c261383855918f80fe5616f1` (10,667,216B), GNU build ID `dfc175888336b355c6febb476c16415e9aec8320`. Recorded GCC16.1 linker/sysroot `/usr/aarch64-linux-gnu`, Rust/Cargo1.92 and raw source/build records live in `artifacts/install-robot-inputs-02`. Source `a476239` already contains historical-epoch and install CLI fixes; its earlier binary is not declared obsolete merely from that revision name. New binary guest execution remains NOT_RUN. |
| Gateway | Retain original source/binary transform chain for the unchanged gateway: selected payload SHA256 `8705d2ca43ec18440a8328e1cb24b0de12ed7858c2960548809d516b0f12822f`; source-debug SHA256 `14ad345385ec1d919384138e0dd70950608ebb1d57e1fed129ec7ee398360554`. Reverify bytes before selection. |
| Installer and guide | Select current checked-out `release.py`, `install.py`, and `README.md` as `share/docs/INSTALL.md`, with their actual SHA256. The original prepared installer predates absent-unit and umask fixes. Select current `tests/guest.py`; never relabel the original payload as updated. |
| Profile | SHA256 `6b9f174af8b018e0cf95bfd282ed52b5385d364ebe7e372d54ce6a91d1d99be8`; RPC1/UAPI1/wire2/state-schema1; live actuation and physical acceptance false. |
| External native fixture | Existing prepared executable SHA256 `3684e5f2a5b848ac779336fb4dc1c087413c92d5fb11e63f39e1c72c7007e398` remains untouched and source-unbound. A separately recorded coherent single-job build from `2ec9da0` passed: debug SHA256 `289f7b63fc50a98ff935059efbed8668876e28495290403515e2993411a41938`, private strip-copy SHA256 `d1176146f8b56f21d644bc75c2b9fe686d342b0d8f09ca61532e726276013842` (705,984B), GNU build ID `5974f84a016e6eab6e827660c51e66fc1c5e0bf3`. This does not match the original prepared debug bytes. Use only an explicit numbered preexecution command/hash amendment pointing to the new artifact, never a replacement of the original cache binary or a running fixture. New fixture execution remains NOT_RUN. |

Before producing a new numbered `robot-inputs.json` and prepared directory,
verify every selected file hash and all mandatory package/boot pins, use the
current tool hashes, and preserve the old/new input diff and provenance. Only
then run existing `guest.py prepare`; it keeps one bounded payload plus small
manifest variants. The fixture attestation remains visibly NOT-A-RELEASE. No
private fixture key is uploaded. A missing CLI/fixture source binding must remain
an explicit unresolved input, not a fabricated qualification record. The new
source-bound CLI and fixture do not prove the original cache binary's provenance.

**Current selection:** candidate03 supersedes only the intermediate module15
input above. `artifacts/install-robot-inputs-03/robot-inputs.json` selects module16,
SHA256 `a49fd1a48bbdc39447a78fc0b0714e2e713c34f4fe25c11e989a790778291112`,
and corresponding source archive
`56e42e74afc899a726b451c1bf73e1cd6a9f06525d4509ea3241aca7b429a5ee`.
The compiled driver matches the seventeen-case plain/lockdep/KASAN/KCSAN GREEN
source; fourteen actual ARM regression cases and both additional owner-lifetime
cases pass on this exact module. Original module15 inputs/evidence remain intact.
The amendment also records current installer/guide hashes and verifies every
unchanged selected input. Mixed binary revisions remain explicit.

The new prepared job is `42fa846cd81c432fa011326549b695ba`; payload SHA256
`e3df7b2eeb8f638cb43300095c03a3c8e6e48ac68bbbdc6bd175dec8e3932a88`
and base manifest SHA256
`dec2aa32b660c3abef80688a903551022e8d811862f04fb236e6f24ce1a5365c`.
Installing these actual bytes with the test platform adapter under umask0077
passes payload hashes/modes and private sentinel preservation. This is filesystem
verification, not guest startup, release qualification or an independent install.
Use this new prepared directory for the scheduled guest campaign, never the old
module15 prepared job. A16 needs its own explicit module16 amendment.

## Disposable guest identity

The existing, never-launched preparation is `.cache/qemu/install-robot`:

- Base Debian13.7 ARM64 image SHA512
  `a34e1c1eea1fbb9ad31ebdfc6c776d1d579ce9e3d740ab10549ebcdca6fe1a46c28e0a42cbcdf1eb561795776733c178f6e816fe1a2cb60d26ffc56c07f915c4`.
- Kernel `6.12.111+deb13-arm64`, package `6.12.111-1`, vmlinuz SHA256
  `5028c424ee9fd0f4d18c38269122e30e3d084deb1b13404ab070a3f478ddd30a`;
  installed kernel config SHA256
  `0f442d89365ea22dc5169463634ee62903925200844558479666cbe3eeb7e555`.
- Initrd SHA256 `ee1f52b37a794606196f48012c634cffe77effdbefe380c86235048d2d76a3bc`;
  DTB SHA256 `b7a13e2f87dccf996274d65e91603b988b4d170bfa3ca9f2610f173d0dcc2011`.
- Pinned QEMU11.1.1 `virt`, TCG/cortex-a72, 2vCPUs/2GiB; guest SSH port26223,
  gateway host-forward27445 to guest7443. The first PL011 is the console; second
  `/pl011@9040000` contains the `actryn,fixture-v2` serdev child at115200 baud.
- Dedicated new SSH key/seed, serial log, controller state/admin/transport sockets
  and QMP socket are already in that directory. Never read or print private keys.
  Record the SSH host key from serial and compare before creating known_hosts;
  retain actual boot ID/machine ID/hostname/kernel/DT compatible readbacks.

Parent owns launch scheduling and at least4GiB MemAvailable preflight. No launch,
disk copy, package installation or controller process change is authorized by
this document. An amended host fixture executable requires a separate numbered
preexecution amendment with original prepared hashes retained. Do not touch the
original preview Robot, server03 preserved disk, A16 guest or any other service.

When separately authorized, provision only the new guest's exact manifest
prerequisites using authenticated APT and a retained simulation. Refuse broad OS
upgrades/removals, unauthenticated packages or replacement kernel pins. Bound
locks/download waits, disable retries and retain failures. The existing Robot
target pins Python3.13.5-1, systemd257.13-1~deb13u1, OpenSSL3.5.7-1~deb13u3,
libc6, libgcc-s1, libssl3t64, libexpat1, libzstd1 and zlib1g with exact versions in
the manifest. No kernel headers are needed to load the supplied module. No
guest protobuf package or SDK pip installation is needed for the native CLI;
the host lifecycle harness uses the already pinned host SDK dependency.

## Existing installer scenario

Use `packaging/release/tests/guest.py run` unchanged with the fresh numbered
preparation, explicit new SSH key/known_hosts, observed boot/machine IDs,
independent image SHA512 and disposable-guest acknowledgement. It checks
unsigned/incomplete/wrong-host/wrong-role rejection, base stage/activation,
interruption after durable pointer publication, explicit recovery and rollback.
It must preserve the test state/evidence/secret sentinels and finish with the gate
present, services inactive and module absent. Never retry a failed mutation or
convert recovered cleanup into a passing original campaign.

Before an actual run, repeat the full real selected-payload lifecycle under
umask077 through the existing FakePlatform seam on a host temporary root, as for
server03. Check exact new payload/public-directory modes and preservation of
existing private configuration/state. This is host evidence only. No new VM
orchestration framework or alternate installer is needed.

## Explicit installed bootstrap

After successful transitions, with the same signed TEST fixture and external
test public-key fingerprint, perform separately logged one-shot actions:

1. Apply `/usr/lib/sysusers.d/actryn-robot.conf` explicitly with systemd-sysusers.
   Verify actual `actryn-gateway` UID/GID, nonzero and distinct from operator1000,
   noninteractive `/usr/sbin/nologin`, no extra group members. Do not assume987.
   Create **new** protected root-owned `/etc/actryn/robot.json` containing exactly
   `{"operator_uid":1000,"gateway_uid":ACTUAL_ALLOCATED_UID}`. Never overwrite an
   existing config or recursively relax the private sentinel directory. The
   manager reads this file as root; the gateway needs no access to private state.
2. Confirm both units inactive, module absent and gate present. Invoke installed
   release `resume --role robot --bundle ... --public-key ... --key-sha256 ...`
   using `/usr/bin/python3 -B -E -s`. Require readiness with no authority issued,
   gate cleared and **both services still inactive**. Resume does not load code
   into the kernel. Existing-robot maintenance requires actual prior matched
   inhibited runtime recovery; module absence alone is not quiescence proof.
3. Hash the exact selected slot module, then explicitly
   `insmod /opt/actryn/robot/current/module/actryn_authority.ko`. Do not use an old
   `/root/.../actryn_authority.ko`, run selftest first, depmod/autoload, or add a
   boot-time module loader. Verify the loaded GNU build-id note equals the signed
   slot module (also enforced by startup preflight), root-owned0600 character
   `/dev/actryn-authority` with matching sysfs dev_t, bound serdev driver and
   `actryn,fixture-v2` OF node. `/dev/ttyAMA1` must be absent; no TTY bypass route.
4. Explicitly start `actryn-robotd.service`, then `actryn-gatewayd.service`.
   Manager runs as root with shipped restrictions; gateway runs as its actual
   sysusers identity, without capabilities or access to authority/private state.
   Verify active PIDs, executable resolved paths and hashes against the selected
   immutable slot, the installed preflight result, and original sentinel hashes.
   Do not enable automatic authority or infer success from process liveness.
5. Use installed `/usr/bin/actryn robot doctor` and `describe` to retain actual
   protocol/UAPI/runtime status. Explicit local recovery is one mutation followed
   by read-only Describe polling (up to14s), requiring `recovery_ready=true`,
   `prepared=null`, `recovery_pending=false`, kernelstate0/opstate0/HANDSHAKEN.
   Never rearm/grant on a mere HELLO receipt or retry an uncertain recovery.

The manager creates `/var/lib/actryn-robot` and its identity/runtime/revocation
children privately. Runtime/StateDirectory modes are0755/0700 respectively.
Mode0600 operator/closure sockets belong to configured operator1000;
gateway-control/relay sockets belong to the gateway UID. The unprivileged
gateway listens TCP7443 and transports ciphertext; mTLS terminates in robotd.

## Positive authority, enrollment and export proof

Reuse `apps/robotd/tests/guest.py` with **explicit** SSH26223/TCP27445/key/
known-hosts/new output directory and selected host CLI, after reviewing its source
hash and installed service pins. It already retains phases and failures; do not
create a second lifecycle implementation. An installed ARM CLI doctor/preflight
readback is separate proof from a host-native CLI network request. If local
installed CLI enrollment/proposal coverage is added, retain a numbered minimal
harness amendment and ensure it does not resend the existing mutations.

The required actual chain is: healthy inhibited recovery -> manager-generated
private key/public CSR -> disposable offline issuer signs matching DNS/serverAuth
chain -> local enrollment install -> separately signed clientAuth certificate
leaf installed with a unique propose principal -> wrong-pin rejection -> mTLS
Describe/pair. Device keys stay in manager state; client/issuer keys remain
private test material and are never bundled. Capture the certificate leaf DER
fingerprint, not the CSR SPKI fingerprint, as the client pin.

Authenticate the workload before binding one immutable attempt/namespace/principal
with its original session ceiling. Explicit rearm, durable preparation readiness,
bounded local grant and activation are separate actions. Require actual fresh
controller observations; propose the fixed typed skill, keep verdict separate
from matched kernel/controller reconciliation, then exercise a second operation
only under the remaining live grant. Existing lifecycle coverage also cancels
an absent key durably, closes on gateway/manager death, preserves UNKNOWN after
restart, rejects stale namespaces, rotates TLS identity and exports retired
captures with byte/hash checks. Never claim physical wheel displacement or full
execution replay from MetadataOnly evidence.

Finish quiescent: retire once, poll `retirement_ready`, recover once and poll
`recovery_ready` with no prepared slot/grant. Preserve original operation IDs,
request handles, snapshots, MCAP/checkpoints, raw remnants and sentinels. Final
current certificate/policy may differ after rotation/revocation; a later fresh
combined run must explicitly enroll/authorize its own unique principal against
the final device identity. Reboot the preserved installed server03 disk only by
parent scheduling; do not reuse stale server Robot peer credentials or endpoint
pins. Combined acceptance remains a separate actual campaign.
