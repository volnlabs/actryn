# Release cohort and case evidence

Source/evidence reconciliation, 2026-10-19; preceding verified push
`117cc93` ([push26](../../artifacts/reconciliation-checkpoint-push26/result.json), zero CI runs; no CI pass).
This additive map closes no whole D2 or whole-release qualification. It records selected bytes,
actual case evidence and the specific work still needed to make a release claim.
The [approved matrix](../superpowers/plans/2026-10-16-actryn-v0.0.1.md#acceptance-matrix),
[D2 contract](../superpowers/specs/architecture.md) and
[platform profile rules](../architecture/platform-release-contract.md) remain authoritative.
All hashes below are SHA-256. Artifact links refer to retained, ignored local
evidence; pushing this document does not back up those files.

## Incomplete qualification packet

The tracked [qualification packet](final-qualification.json), SHA256
`b82dd3d118f039da366e885eaa2b56854f0e42605dda77bcc1ead8204144a727`, binds
Server9f/Robotda6,44 payload entries,17 D2 predicates and A01–A16. Static checks
verify107 small public receipt hashes, both manifest projections and all44
component-record pointers;12 entries carry explicit build-revision pointers.
Four larger source inputs and the two payload archives retain their previously
selected evidence pins and were not reread during this assembly.

The existing release format requires a named qualification-bundle hash and
role-scoped custodian attestation but defines no inner acceptance schema. This
packet is an incomplete review input: its frozen associations remain OPEN and
its A16 field predates the separately qualified successor below. A13/A14/custodian
inputs remain external. No manifest is
changed or signed; adding approved qualification metadata later changes its
identity. The tracked packet preserves the map, not its ignored local receipts.
[Static validation](../../artifacts/final-cohort-qualification-packet01/validation.json)
and [Root binding review](../../artifacts/final-cohort-qualification-packet-root-review01/result.json)
record checks only, with no new build, target action or functional test.

## Selected artifacts, not a homogeneous build

The installed Server is disposable TEST manifest
`f32f1c85ff58095034d7b82f80e59454fac826b83760f7013a585a27025c54ad`, with payload
`c7db8cdb7784f0b6e63a9e5e7f5de55740e269076da3c81072d7eda67b881097`.
Its unsigned reference is `fbfc394a2e710cadf738596830dcfc1b7f778e99b8a1336d85a9bf2a64547c78`.
The 27-entry [component map](../../artifacts/server-device-policy-package01/component-map.json)
is `51d45112d30e6d74c2e8ebfc91810b90f35b2f44b89d60f335ffe7da057f78f0`.
Only the launcher executable and its unit changed from the preceding Server package;
the other 25 payload bytes, modes and licenses were preserved.

| Server payload | Selected hash | Build origin / boundary |
|---|---|---|
| `bin/actryn-launcher` | `17a0d39250fb67c20b3397ddeeb5201cbd0f650426e06a12bcae918362996b24` | `14afd962b9bea0986a4507230c2dd5710c52dca9`; integrated as `2e93ccd` |
| `units/actryn-launcher.service` | `778d4698d09a94b8a94a6d4981a39fd324ec6d42bf7c2191aee8d9e41a4f9acb` | Same source; adds launcher `CAP_BPF` |
| `bin/actryn-serverd` | `afef317ba581fe2feedf24bd46c244c17fdbd5aacf4b75dd62058a64a93ada5b` | `8d6e71df39738fe742421348e6c16d68d1cbb727` |
| `bin/actryn` | `f5840d33b5ffff7b9de58cf32581299fb25289c186ba38f1ede69a1f9c42443c` | `544c3824a486097ca30b66b56220a148d9bbd742`; importer correction |
| `bin/actryn-observer` | `bf2b4d2214940722c8ac3e5f11c67321787834126a0bdb7c787cc76f88537a7c` | `770c87915b329e4c597cc298f4cc02ad74fcc157`; reused binary |
| `lib/observer.bpf.o` | `13c4882895fb92567c34abdc1a77a0c00b184cbe61e7af621f3547c9887b734d` | Original build receipt unavailable; later byte-identical matching build at `c72bfe0` is separately retained |
| `bin/controller-fixture` | `d1176146f8b56f21d644bc75c2b9fe686d342b0d8f09ca61532e726276013842` | `2ec9da05bce8f14caff50ad79d0eab9ca67b5600`; reused binary |
| `share/agent/offline-oci.tar` | `8f0656fc10fb7b78e4667f16ce0efa9d9eaf8c8ec84559fbf35408276b35b928` | Packaged offline artifact; distinct from imported capacity-diagnostic and D2 test artifacts |

The new cleanup launcher candidate is
`3ead4e49f73954137034910028e49a5fad4b0b34d0eeb36c908581447f2afe30`, built
from `e6c3fd6` and integrated as `e6120d3`. Its actual corrected GREEN04 fixture
passes below. It ran directly on the private regression clone; no installed
Server payload or signed release package was replaced. Final Server candidate
assembly is complete as the unsigned selection below; applicable cohort qualification remains open.

**Final Server package: selected unsigned candidate, exact payload target-exercised.**
Manifest `9f749ca31d975e870c2a358762fd01c6c04ebf1e170ca569fe0ea1aa8563a90f`
has payload `7b596c872290039cee2491595cc23515cc8a0eb559f0da3fcba619455518fe71`
(70666240 bytes). The [assembly](../../artifacts/server-final-cohort-package01/result.json)
and [independent byte review](../../artifacts/server-final-cohort-package-root-review02/result.json)
verify all 27 entries: only launcher3ead replaces launcher17a0; the other 26
entries, modes and licenses are unchanged. The [component map](../../artifacts/server-final-cohort-package01/component-map.json)
retains mixed build origins. Source e6/integration e612 and assembly b89 remain
distinct. Build/inspect both return zero; this assembly performs no compilation,
installation or signing. The canonical bundle remains uninstalled, unsigned,
nonpromotable and qualification incomplete, with no custodian attestation.

A fresh Debian 13.7 amd64 guest subsequently installed the exact
`7b596c87…fe71` payload through disposable test manifest `6346a2fb…c780`.
Campaign `fa45517ec6f644abb5298e441be5ee07` binds the same payload bytes and
launcher `3ead4e49…fe30`; it passes tuple/signature rejection, interrupted pointer
publication, explicit recovery/rollback, bootstrap/offline import, tamper
rejection, live isolation/limit readback, cancellation/reaping, service restart
without reexecution, six-artifact export and normal poweroff. Fixture job
`6b8c14cf…bf23`, exact-tuple receipt `59ec6f6d…9395`, installation log
`0e0e8e57…cac0`, lifecycle receipt `a84bc238…b5f1`, export
`6e152833…1d8e` and stopped custody `19a02faa…f56` are retained locally.
This target exercise is test-signed and `release_qualification=false`; it does
not promote the canonical manifest or supply A13, A14, a release signature,
durable archive custody or physical proof. Installed historical f32 stays
unchanged; its negative/fault cases and GREEN04 retain their stated scopes.

The installed Robot is disposable TEST manifest
`d77a269823b55ba8fe2541be15b3202651489fdd3c784cab69cd242821a2f012`, with payload
`3ddf8ff34ea418b16813c522718beb85da7c02c7aebc40fa6d4daeec5c276367`.
Its unsigned reference is `dadd347413b23833d1272bbdf0c45b0e46259b5e8bdd3e40dcc0a907eedbca6a`.
The 17-entry [component map](../../artifacts/robot-reconciliation-package01/component-map.json)
is `80ca5934debfd7ad2dec6bc4baad5ad497ca07dd218083ae4066549cfd76bd9c`.

| Installed Robot payload | Selected hash | Build origin |
|---|---|---|
| `bin/actryn-robotd` | `e36d5b2857bfa85b9042d529246b0b173c9cc4cac8c7686c3a6bf047a2ce372a` | `8d6e71df39738fe742421348e6c16d68d1cbb727` |
| `bin/actryn` | `4102e793c48fc43767680ed3c9cf4ffd2f8512171271e3340ab2632090fd1fc5` | `544c3824a486097ca30b66b56220a148d9bbd742` |
| `bin/actryn-gatewayd` | `8705d2ca43ec18440a8328e1cb24b0de12ed7858c2960548809d516b0f12822f` | `a47623935380d37310154fbfa0d8ce7a4294f53f` |
| `module/actryn_authority.ko` | `a49fd1a48bbdc39447a78fc0b0714e2e713c34f4fe25c11e989a790778291112` | Module16, source `d3f48e8694faac2ae4f360e8d4d010824d50ec0a` |

Both roles select profile `6b9f174af8b018e0cf95bfd282ed52b5385d364ebe7e372d54ce6a91d1d99be8`
and build inputs `60ec99a5d032831a94c36036555a2c9b1b969fa3f2e9436293d521459f0e1831`.
The Robot DTB is `b7a13e2f87dccf996274d65e91603b988b4d170bfa3ca9f2610f173d0dcc2011`.
These identities do not establish current package/provider equality on every test disk.

**Final Robot package: selected unsigned candidate, pending qualification.**
Manifest `da6b6862768071ae839c64d73be56f63e23d852ab99e0b7d12f1541f987cc5a9`
has payload `1e71fe911512a61b164e1a3763b41fdcca3af03627c9400a9f663244b02066bb`.
The [actual assembly](../../artifacts/robot-final-cohort-package-plan01/result.json)
and [independent saved-byte review](../../artifacts/robot-final-cohort-package-review01/review.json)
verify all17 entries: INSTALL.md selects `c8b5f4a7e47e06b198b511bdd8c9ba9dae35018f078afc32bfbf629c08890add`,
notices02 selects `98ec4b48f120976337d35ff57ea16e4b56b18c9c10406a237206c401d410a985`,
and the other15 entries remain byte-identical to dadd with every mode/license unchanged.
The [component/evidence mapping](../../artifacts/robot-final-cohort-package-plan01/component-map.json)
retains mixed build origins. This host assembly did not install or change d77;
the older `878732d8…` cohort is not selected. The candidate remains unsigned,
nonpromotable, qualification incomplete and custodian null; document selection
does not supply target qualification or release approval.

## Source-impact boundaries

The following comparisons read retained source archives, without rebuilding or
using a current branch as a substitute for a component's build source.

| Comparison | Concrete result | Permitted use / remaining work |
|---|---|---|
| Server `8d6e71d` archive `79acc8689f9eef8098be5ca4ba0911e0e5285cfa9e2ac34375f73a4d55732831` → launcher `14afd962` archive `270cda4667aea8206012a35c2395f4f705e9448e86a25f9e230d679f91ce7d03` | Within Server production source, Server Cargo.toml, robot-rpc, Cargo.lock and service units, only `bpf/device_policy.insns`, `src/{device_policy,launcher,lib,policy}.rs` and the launcher unit differ. | The final delta is fixed-filter installation after gated CREATED task creation, direct/effective MULTI inventory verification before Start, and loader capability. Host instruction/interpreter and binding regressions plus actual D2 filter evidence cover that delta; they do not re-execute every older sandbox case. |
| Historical launcher `d58dd102` archive `515c8a0d4d1186a09f503a02811a7ee3052f6707438921c37dd664457d7093ab` → `14afd962` | Server source additionally changes `artifact.rs`, `robot.rs`, `service.rs`; Cargo.lock also differs. | Do not call the entire old→new build a device-only change. Reuse importer, credential/settlement and final-filter receipts separately; review the applicable dependency/link closure for each older claim. Unrelated workspace changes are not automatically linked code. |
| Manager11 `02779a0e` archive `e6b4cbecc216a5169a2de20b693c7162691a34642003f286dd24563a1d364747` → Robot `8d6e71d` archive `fbe3e0f227c1579ad00e8d15cdae0e2b76b851d973e13b5f804c4d00aadef085` | In the compared daemon, runtime, intent, evidence, authority-client, RPC and lockfile scope, production changes are intent `src/{lib,store,types}.rs` and runtime `src/{lib,reconciliation,types}.rs`; tests/READMEs also differ. The other named scopes match. | Durable legacy Completed remains reconciliation proof with OutcomeUnknown task verdict; allocated cancellation needs an exact operation/revision marker, queued before writer stop and credited only durably. Missing/corrupt/legacy cancellation proof stays uncredited. Old-reader conservatism is not general downgrade qualification. |

Source archives: [Server 8d6](../../artifacts/server-reconciliation-build01/source-8d6e71d.tar),
[launcher14](../../artifacts/server-device-policy-build01/source.tar),
[launcher d58](../../artifacts/release-source-materials01/sources/actryn-d58dd10235d906644027a973dfd297d7841a492c.tar),
[manager11](../../artifacts/release-source-materials01/sources/actryn-02779a0e36e6a587eceaa7daa0229393bb93906d.tar),
[Robot 8d6](../../artifacts/robot-reconciliation-build02/source-8d6e71d.tar).
The Robot build review checks 363 source leaves, 28 allocated sections and 147
target imports; the ARM CLI ABI receipt checks 136 imports. Launcher build checks
31 allocated sections and 154 historical target imports, followed by fresh four-provider
readback before installation. These are static/build facts, not behavioral tests.

## Case-level reuse and remaining predicates

| Required scope | Evidence that can be mapped | Boundary still requiring an explicit disposition |
|---|---|---|
| D2 existing-device denial and memory pressure | **Two-case composite only:** f32/launcher17a0, existing char1:7 with allowed/absent controls, open results3,-2,-1, 177 loss-free records, fresh max18/oom1/oom_kill1 and natural137; all 27 cold payload/policy files subsequently verified. | Original run05 is FAILED; normal capture05 NOT_RUN. The corrected offline validator and separate custody establish these cases without a new attempt. Trace attribution combines fixed probe/node/control evidence, not a device-policy-origin event. |
| D2 fixed-policy installation failure | One Server111 Prepare without CAP_BPF reports load EPERM; durable rows retain one reaped/cancelled attempt with null snapshot/device proof, unchanged Broker and no debit. Separate cleanup validates 157 contiguous trace records with no loss, exec or output, then stops once/restores four policy files exactly. Final 25/23 Server, 16/21 Robot, zero debits/all 374 and normal poweroff custody pass. | Original owner remains FAILED on its two-key reply predicate; actual six-field `server_error` keeps `outcome_unknown=true`. Current durable cleanup proof does not relabel that reply or case. No replay, agent Start or whole-D2 PASS. |
| D2 native sandbox and Broker policy | One source-bound native OCI attempt on kernel111/f32 passes ten syscall denials, five Broker cases and 196 loss-free trace records through unchanged offline validators. Separate status, cleanup, three-file Restart restoration and normal poweroff pass. | Original runner remains FAILED on Launcher Cancel/Broker Status confusion. Retain both independent deadlines and all failures; source-only harness amendment02 is target NOT_RUN. Exact scope and current imported configuration are below. |
| Other D2 isolation, attribution, method policy, cleanup/export | Historical `server-services-guest05.log`/`-unknown.log`, installed Server receipts, `server-a08-pressure-run11`, and `observer-installed-01` supply separate scopes. Selected observer/BPF and serverd retain their own origins. | Map every [profile rule](../architecture/platform-release-contract.md) to actual controls, prepared snapshots and negative/cleanup evidence. Check the launcher/dependency delta above; do not transfer all older claims solely because package filenames match. Whole D2 remains `OPEN_FINAL_COHORT_RECONCILIATION_REQUIRED`. |
| A01/A03 | Manager11 lifecycle03: two natural completions under one grant, reconciliation before reuse; module16 stale/replay cases. | Older manager execution is not execution of e36. Bind the reviewed reconciliation delta and its tests/actual settlement separately; no combined-two-operation claim from the one-operation combined demo. |
| A02/A09 | Replyloss02: initial reply withheld and durable cancellation; contention04: allocated closure during 611 ms SQLite lock, zero STARTs; registry race tests remain separate. | Manager10/module16 evidence. SQLite contention is not fsync-stall, EIO or media-power-loss proof. Current command/front-end coverage is separate below. |
| A04/A05/A08 | Existing crash/unknown-history evidence, pressure-run11 allocation/reclaim cases, and final existing-handle cleanup with e36/afef: four historical settlements preserve OutcomeUnknown; exact raw cancellation markers and 22/21 Server,16/21 Robot,zero-debit custody. | Finalize-run01 stays FAILED at recorder-inclusive cutoff; its consumed abort remains unknown and must never be resent. Separate cleanup does not create task success or a whole-campaign PASS. Package drift during the interval must not be silently described as exact original-cohort execution. |
| A06/A07/A15 | Unchanged module16 aggregate: 16 actual ARM cases and 17 cases each in plain/lockdep/KASAN/KCSAN, including retained FD, leader exit, genuine PID reuse and concurrent closure. | Reuse exact module/source/config receipt; no blanket diagnostic rebuild. Mocked serdev byte offsets and PM/shutdown callbacks do not prove physical UART or real-platform suspend/poweroff behavior. |
| A10 | Traffic03 corrected unchanged-capture analysis; lifetime09 gateway replacement/retained-FD, local offline recovery and export. | Preserve earlier failures, uncertain negative reply and the capture-prefix boundary. Zero SAMPLE records are not applied-motion proof. Bind manager11→e36 delta. |
| A11 | Actual source80→82 gap and hot-journal committed-prefix recovery. | Preserve raw remnant/unknown tail and read/queued/durable distinctions. Metadata-only capture intentionally remains execution-replay-ineligible. |
| A12 | Fresh installation/interruption tests; exact final Server and Robot payload bytes now pass fresh test-signed derivative campaigns, bootstrap and installed lifecycle. The canonical unsigned manifests remain unchanged. | Canonical candidates remain unsigned, uninstalled and unqualified; test keys do not supply release custody. Runtime-only qualification Restart=no drop-ins are recorded test configuration, not the packaged Restart=on-failure policy. |
| A13/A14/A16 | Live-policy/missing-credential controls remain separate. A13 consumed two calls without retry: standalone PASS; combined FAIL after 33 tokens when Robot recorded clock-mapping expiry, with no operation, zero output, retained uncertain debit, explicit recovery/export and stopped custody. The [original A16 comparison](a16-comparison.md) stays FAILED79/80. A separately frozen passcred10 successor passes two excluded pilots and all 80 ABBA trials on six distinct pinned-kernel boots, with 78/78 correlations in every traced run, independent local analysis and stopped custody. | A13 requires a reviewed clock/protocol correction and renewed budget; its failed call cannot be replayed. A16 successor software comparison passes while historical causality remains unproven. Independent installer, signing custodian and release identity remain unconfirmed. No physical, UART-drain, WCET or superiority claim follows. |

The preceding capability-denial Server case leaves 25/23 Server rows, 16/21 Robot records and zero
debits. Separate durable-state cleanup, cold stop, exact policy restoration and
normal poweroff preserve all old rows and 374 entries. Earlier run05 leaves 24/23;
the still earlier retained-debit cleanup leaves 22/21. All original failed records
and uncertain replies retain their status.

The [additive enforcement review](../../artifacts/server-final-d2-predicate-map01/enforcement-followup01.md)
resolves the running-device-filter lifetime question under the stated trusted
Linux/administrator assumptions: the cgroup owns the attached program reference
through loader/reader exit. This is an invariant disposition, not a periodic
monitor or hostile-root claim. The later one-Prepare/no-Start capability-denial
case and separate cleanup are recorded below. The original owner remains FAILED;
the durable current-state proof is distinct from its uncertain CLI reply.
The [additive D2-12 association](../../artifacts/server-final-d2-predicate-map02/association.json)
binds that evidence to the selected launcher without changing the original map.
The later native evidence below supplies attributed individual sandbox negatives and a forbidden Broker-method record; whole-D2 reconciliation remains open.

The [sandbox/method-policy follow-up](../../artifacts/server-final-d2-predicate-map01/sandbox-method-followup01/result.json),
SHA `e1b774964b38b707b6b60ce3772200c65a4f09fac11fb1f685352208ac229f19`,
binds the older installed offline positive to its exact manifest/service/agent
identities and settled call. The selected source comparison retains unchanged
fixture, harness and policy rules. The early native sandbox summary lacks
individual negative records and executed-agent attribution; no negative-case
credit transfers from that summary. The later source-bound native attempt below
supplies its own selected-f32 records. The proposed installation-failure
case has eight passing host checks. Its separately frozen finite owner has nine
passing host checks at
`artifacts/server-enforcement-negative-owner-plan01/verification.json`; those
source-only records precede the later single Prepare and failed owner below.

## Server111 capability-denial cleanup evidence

Guest boot `62353823-df1e-4515-a744-3d767565835e` binds exact kernel
`6.12.111+deb13-amd64` and the installed f32 cohort above. Cold prerequisite01
remains FAILED on selection of pre-Stop raw baseline `42d99…`. Saved-only amendment02
proves exact raw bytes/metadata/absences against last cold capture `ca68bcd1…01c9`
and the acknowledged prior normal poweroff; it does not rerun collection.
The first separate cold integrity invocation uses the unchanged 55-second guest
scope/65-second transport and verifies 27 payload files, five registry trees,
persistent policy/configuration and four exact providers.

The sole Prepare is `aa4055e973266e3b6fda034d3597b2ea`. Its fixed-policy load
EPERM reply has six fields and retains `outcome_unknown=true`. The two-key
validator fails; the original owner and markers remain FAILED. Read-only 25/23
rows resolve current terminal state only: reaped/cancelled, null snapshot/device
proof, unchanged Broker, no debit and empty runtime. Separate cleanup validates
all 157 contiguous trace records with no loss, exec or stdout/stderr before one
three-service Stop and exact four-file policy restoration. It creates no new
Prepare or agent Start. Normal poweroff then confirms the original VM pidfd dead
and fresh serial shutdown markers, with known owner exit0/empty scope.
The hashed guest's capset check executes before the persistent Prepare intent:
exact `0x8100b`, with CAP_BPF and CAP_SYS_ADMIN absent. No separate raw
`/proc/<pid>/status` dump is retained; this is source-path proof, not an independent dump.

Final custody records all 35 host units inactive with empty cgroups and NRestarts0,
and no repository VM, fixture, QSD, FUSE mount, image holder or selected listener.
Counts are 25/23 Server, 16/21 Robot, zero debits/all 374 retained. Server disk SHA256 is
`6ffb2dad642c3d84d0ce3d1fce0d68099d58eb2964b041bc7e6410f5dc79def3`;
other eight public byte/metadata records, three metadata-only keys, both fixture
journals and extracted boot files are unchanged. Whole D2/final-cohort mapping
remain open; A16 stays FAILED 79/80 and no physical qualification follows.

| Capability-denial window receipt | SHA-256 |
|---|---|
| [Original cold prerequisite FAILED](../../artifacts/server-kernel111-cold-readonly01/result.json) | `5d8ff9c76ec0a2c6acced080fed82e6886769db4c3fdda1f46348e18414160e7` |
| [Saved-only cold-baseline amendment](../../artifacts/server-kernel111-cold-readonly-root-review01/cold-receipt-amendment02.json) | `44fc914b4971e5a11ca1ac615fdf7441189f2d342ad2fdd918104a24b94905f9` |
| [First cold integrity](../../artifacts/server-kernel111-cold-integrity01/integrity.json) | `5c4968d527905bcee992367937afd366267f63a789e3940e9759c7db5fe24808` |
| [Original negative owner FAILED](../../artifacts/server-enforcement-negative-owner01/result.json) | `e20d3373bb7793a5b21e3f2195ff6065684272e028b773c34c8435d2e4cbebbf` |
| [Independent read-only state review](../../artifacts/server-enforcement-negative-readback-actual-review01/review.json) | `1aa7a93b39e864e2fe41240dfb5ca2916724a84d9de83e9a6eac3adb22c19076` |
| [Retained 157-record trace summary](../../artifacts/server-enforcement-negative-cleanup01/retained-summary) | `20a2a73b3ee49013b2e878e6e0198fed12f180df984584996754b05688d4ef55` |
| [Separate durable-state cleanup](../../artifacts/server-enforcement-negative-cleanup01/result.json) | `ad81ee302af77fb5e8bbde651be5324573eb6b2d135e39691a19dada0634ed46` |
| [One normal Server111 poweroff](../../artifacts/server-kernel111-normal-poweroff01/result.json) | `ded572661a5c4630be0375374d96df051b6b3f9815494cea683af659ea15ad84` |
| [Independent cleanup/poweroff review: 57 saved files](../../artifacts/server-enforcement-negative-final-actual-review01/review.json) | `2e52eb289a4e7af8061ee6e7667584ea3e62713a9152c8bc994a5ca814573344` |
| [Final stopped custody](../../artifacts/server-enforcement-negative-final-stopped-custody01/result.json) | `48f938cea1a2980d46304005423f6cb0e05b36a776a17d01908f34a45ca31e55` |
| [Additive D2-12 evidence association](../../artifacts/server-final-d2-predicate-map02/association.json) | `68db7b6aa9fbd146adfbd5c8b9bd2a9d075034bf775987453902a8ff4bddf36e` |

## A16 kernel11 excluded-pilot evidence

One kernel11 invocation passes all 10 trials, including cold trial 0, with zero
recorded loss and all 78 eligible dispatches correlated from 98 capture records.
This is the excluded kernel correctness/instrumentation pilot, not a comparison
result. Guest boot is `6c464096-b1a9-4403-bf5b-cfc8da9dabd4`. Before execution,
Root approved a new full 375-record catalog (all `ii `, architectures all/arm64),
two resolved `libc6:arm64 2.41-12+deb13u4` provider files and the four frozen
artifact hashes below. Historical names/versions match; the old full provider
byte baseline was unavailable and is not inferred. Exact canonical catalog,
providers and artifacts fields match before/after; the two observation files
are also byte-identical. C03 retains the common four masks, qualified passive
shutdown-helper checks and original binaries, 10 ms HELLO limit and denominator.

One normal VM poweroff and one supported fixture shutdown complete within the
original 490-second window. Original process pidfds confirm death; exact exit
codes are unavailable after transient-unit collection. The full stopped receipt
records all 12 carrier/owner units inactive/MainPID0/empty cgroups/NRestarts0 and
no repository VM/fixture processes. Fixture boot 39→49 adds 200 bytes, leaving a
1004-byte journal with the old 804-byte prefix unchanged. Other stopped public
files and metadata-only private keys remain unchanged. The saved A16 disk hash
is `3b53d71caab1a38eec3a4dedb29594df8812131abf61889f8cf069d4911cf00e`;
no disk or private-key hash was collected for this documentation update.

| Kernel11 input or receipt | SHA-256 |
|---|---|
| [C03 frozen runner](../../artifacts/a16-common-quiescence-plan03/source/kernel/tests/a16/campaign.py) | `21f93e10d4a1a8883bd6c85ad70adefcc30bb19a3fc53ed3f788790072a61ae2` |
| [C03 frozen campaign manifest](../../artifacts/a16-common-quiescence-plan03/source/kernel/tests/a16/campaign.toml) | `28e0038947adc3c3d491af65040befca6170be59a05fa55a079d0dd5187d8d9c` |
| Selected amendment7 workload, as bound by independent review | `40f75fe9d898bcd2320f97e70257426f3ca71cdddffe562a25f7581ccba42398` |
| Selected amendment7 gateway, as bound by independent review | `305f5e1d15df9d2037b7ecc8246825a791a18d92c5f1408fed8de5b1062c9720` |
| Selected production module16 | `a49fd1a48bbdc39447a78fc0b0714e2e713c34f4fe25c11e989a790778291112` |
| Selected ABI7 capture module | `fae8eccb64cbe586f55a5c92c4b0521173dc2c4308fd5fa60f0c6cb3f646b403` |
| [Pre-pilot cohort approval](../../artifacts/a16-kernel11-cohort-approval01/approval.json) | `6a65f6fac9c05d4d412a2332602a6dfbb009bbb29eb26db0bda245a430036bec` |
| [Approved catalog/provider/artifact baseline](../../artifacts/a16-kernel11-cohort-approval01/baseline.json) | `a9a58ed7f1183db55f87c4b70210d0a85487895d5045fb33ce88202c75ff5f86` |
| [Before observation](../../artifacts/a16-kernel11-boot-observation01/boot/package-provider-observation.stdout) and [identical after observation](../../artifacts/a16-kernel11-pilot-owner01/after-observation.stdout) | `862e26f063de85b455f0503952a07891a338379981c8a3a73a36152d49bdc0b8` |
| [Three-field equality validation](../../artifacts/a16-kernel11-pilot-owner01/pair-validation.json) | `093ee4d3f5b58537930d2be06fc37318ad084f20c80a4bf1b0f31abd0302d394` |
| [Pilot and known poweroff](../../artifacts/a16-kernel11-pilot-owner01/result.json) | `852d2137807445b01ebc143c939be6f7740707321e4765083b1a28c71197e28f` |
| [Supported fixture shutdown](../../artifacts/a16-kernel11-fixture-shutdown01/result.json) | `08b2d2caa343552f591b76ab88dcd742341cae6a7f643007b0d0190adeb09ad9` |
| [Independent saved-evidence review](../../artifacts/a16-kernel11-actual-review01/review.json) | `bbf9691a540e8508fc67b9b67ffc3afdf0019451ef471d489e79bd1db6c1a4af` |
| [Final stopped custody](../../artifacts/a16-kernel11-final-stopped-custody01/result.json) | `3c0af6209cc09236c9fa623fb78ee860a97cc9c4d45dfd803da6285cab339046` |
| [Stopped public-byte custody](../../artifacts/a16-kernel11-final-stopped-custody01/public-custody.json) | `a450475c1c8e68d4b38abacbf3fab8e43ca566f9f097751cfbc33b640d4e1c85` |
| [Local byte-identical raw copy: 44 files/728235 bytes](../../artifacts/a16-kernel11-raw-preservation02/inventory.json) | `ed60356cc63c6b0978f48c2b204b29b4e3a58ee894f02d14ff2a2aa9c12145ed` |

Userspace11 subsequently passes below. Four frozen ABBA boots/eight comparison
runs remain required.
Prior pilot07 is FAILED at 9/10; boot09/10 failures and their NOT_RUN pilots remain
unchanged. Kernel11 establishes no original-failure cause or fix. Dispatch ends
at complete immutable-frame acceptance into the Linux serial buffer, not physical
wire drain or actuator response. No physical, WCET or superiority claim follows.
The raw copy is ignored local evidence, not a Git backup. External A13/A14,
genuine release signing and final whole-cohort qualification remain open.

## A16 userspace11 excluded-pilot evidence

Userspace11 passes all ten trials, including cold trial 0, with zero recorded
loss, 98 clean capture records and 78/78 independently correlated dispatches.
Guest boot is `c9b6f5a0-7272-48cc-ad42-82c3007de583`. The same C03 runner and
four selected binaries above are unchanged. Its fresh catalog/providers/artifacts
match the original kernel11 approved baseline before and after; the original
approval remains bound to its original observation. No new baseline is selected.
The raw arm uses the reviewed gateway and raw UART, with no authority module or
ADMIN_BIND. Gateway stop, retirement fences, absent relevant descriptor holders,
capture unload and passive tracing precede normal poweroff.

One pilot, one normal VM poweroff and one supported fixture shutdown complete
within the original 490-second window. The fixture journal advances 50 to 60 by
ten CRC entries/200 bytes; its original 1024-byte prefix remains unchanged. Full
stopped custody records all 16 carrier/owner units inactive/MainPID0/empty cgroups/
NRestarts0, no repository actors or disk holders, and unchanged other public files
and metadata-only private keys. The new A16 disk SHA256 is
`cf2b518d110b47f2a752c132fca32ce74a281755d2c6235075757bb8ce7206c8`.
Exact QEMU and fixture exit codes are unavailable after unit collection;
original pidfds and serial shutdown markers establish the recorded deaths.

| Userspace11 receipt | SHA-256 |
|---|---|
| [Fresh before-cohort validation](../../artifacts/a16-userspace11-cohort-binding01/before-validation.json) | `05b72aecc16cfb043448866734aa47d5a690755fcb920af15377d48cc3884984` |
| [Same-cohort before/after validation](../../artifacts/a16-userspace11-pilot-owner01/pair-validation.json) | `05b72aecc16cfb043448866734aa47d5a690755fcb920af15377d48cc3884984` |
| [Pilot and known normal poweroff](../../artifacts/a16-userspace11-pilot-owner01/result.json) | `7096e1bb6bbaae62f1d83a60e86197f954c4d51b59c1b5ebe45d8f8262e592ae` |
| [Supported fixture shutdown](../../artifacts/a16-userspace11-fixture-shutdown01/result.json) | `2e10d230865493184aaf8b3eaa7a08af2002310b9f54f60d46dad6bebc255e26` |
| [Independent saved-evidence review](../../artifacts/a16-userspace11-actual-review01/review.json) | `5468d1b830e9a29167c31f2670879da2e56e8057dcee1c3eb52f96b3d88260ca` |
| [Final stopped custody](../../artifacts/a16-userspace11-final-stopped-custody01/result.json) | `edf9b4896cbc5356306c5f0ce6a768b9fb360a8b65097f6638c9737f6c14b97a` |
| [Stopped public-byte custody](../../artifacts/a16-userspace11-final-stopped-custody01/public-custody.json) | `a03e6cab092f995925ea8ea83518390cce402df0cae146ad1a6e49fb08e647d3` |
| [Local byte-identical raw copy: 48 files/733882 bytes](../../artifacts/a16-userspace11-raw-preservation01/inventory.json) | `40eac1f36fa1555cd3e8495e81d96fc902bf5f010f7a7f11d3e2f92e63c5a2b7` |

Both pilots remain excluded from measured comparison. The subsequent four frozen
ABBA boots/eight runs are complete and FAILED: 79/80, with all 80 begun/ended and
B3 evidence trial 6's BIND abort retained. Six original-K11 cohort pairs and four
78/78 trace correlations pass; these do not repair workload acceptance. See the
[actual eight-run report and exact receipts](a16-comparison.md), including final
independent audit `4257e045…ef0865`. At that comparison checkpoint, A16 stopped custody is B4: 24 inactive
empty units and journal 144/2904 bytes, with unchanged other public/key-metadata
records. Pilot07/boot09/10 failures remain unchanged; local raw copies are not
Git backups. No equal-work, significance, superiority, physical or WCET claim follows.

D2 remains open. Prior read-only extraction failures remain preserved; the
separate extraction02, exact111 boot, cold integrity, one failed negative and
durable cleanup/poweroff are recorded above. They do not close the final-cohort
map or relabel the original failed owner. No independent installer, signing
custodian or release signing identity is confirmed. The documented broker route
is `/etc/actryn/credentials/openai-api-key` via `LoadCredential`; actual provisioning
remains unconfirmed for the user to check.

## ARM CLI coverage to bind

The selected `4102…` CLI has actual installed `robot describe` and `robot recover`
execution in the d77 startup/update receipts, plus the static ABI result above.
The startup capability-parser failure is preserved; its retained known Recover
reply and ready proof are not another startup invocation. Manager11 lifecycle03
calls `pair`, `handle`, `cancel`, `query` and `export` using the **host**
`target/debug/actryn`, SHA `76264fae868e823b2010204001b8e7444311e8259a6da2c8a946b41b1f430daf`.
Its exact build-origin receipt is not identified in the inspected chain. Those
calls are not execution of the installed ARM2e65 binary.

The additive [saved-source proof](../../artifacts/arm-cli-coverage-source01/result.json),
hash `e8cbec1e75f312601cdf428a3868897551026234629510e6562d3cacce5a2a66`, compares
selected544 with old ARM2ec9: all CLI, RPC/authority-client and schema production
sources match. Across 36 compared production/build/schema files, only the Server
artifact importer differs; 259 conservative locked dependency records match.
The sole workspace lockfile change is outside that closure. This supports
front-end reuse, not native binary equivalence or e36 manager qualification.
Enrollment01 supplies actual old-ARM `enroll-request`, `enroll-install` and
`install-principal` results; its pairing uses same-source544 **native** CLI f584.
The [proof notes](../../artifacts/arm-cli-coverage-source01/README.md) retain exact
invocation, provenance and historical-catalog boundaries.

Actual CLI execution of `prepare`, `grant`, `rearm`, `activate`, `observe`,
`propose`, `reconcile`, `revoke` and `retire` is not established by this chain:
the lifecycle exercises these through RPC/SDK. Selected-ARM `doctor`/`status`
and `revoke-principal` also remain unbound here. This describes coverage, not a
new requirement for a second, CLI-only target campaign. The approved spec requires
the operator CLI and shared API; A12 concerns installation/tuple/update behavior,
and A14 requires independent developer use. Neither demands every subcommand run
on the target separately. Bind source/host command-dispatch, RPC/handle and ABI
proof to the real SDK workflow; review missing positive front-end checks before
deciding whether any new target execution is necessary. Do not promote generic
RPC tests to positive tests of every command. Any genuinely needed fresh target
flow must preserve the full old history and use a future fresh-data VM/candidate,
without old Cancel/Recover replay or capacity widening.
[CLI dispatch](../../apps/cli/src/command.rs) defines the names; there is no separate
`robot execute` or `authorise` command to invent. All original failures remain.

## Hash-bound receipt index

These are existing records, not new acceptance results. Earlier package/build
records saying target NOT_RUN remain historical; later actual receipts supplement
them without rewriting them.

| Receipt | SHA-256 |
|---|---|
| [Launcher build](../../artifacts/server-device-policy-build01/provenance.json) | `fd7c18d41c2fbad01d119d58d3efee3b04dcaabe7b7c46f33199b82153b85193` |
| [Serverd build](../../artifacts/server-reconciliation-build01/provenance.json) | `39150625840f9a85875fc7017c9a11e28434c865b597506a56c9304ac518a539` |
| [Robot build review](../../artifacts/robot-reconciliation-root-review01/result.json) | `72c37e7ee8a3df6d19dc2b4a95206e651e014152027920ac7ffe8e4701a6964a` |
| [ARM CLI ABI](../../artifacts/arm-cli-runtime-collection01/abi/result.json) | `080fd43f46d218449ad6d79c5c2141e684736ec0de7827b5f75708488cbed67a` |
| [Device-policy host checks](../../artifacts/server-device-policy-root-tests01/verification.json) | `2e0fb58ecf830e9932c4877867fd82ab8e43b42710bdf34c2089264453d56b49` |
| [D2 corrected offline review](../../artifacts/server-diagnosis-thread-exits-regression01/review.json) | `ad5269e4afebe064d8033aa1871d42a4ebd2fcec54826128b210c1562e05b7d0` |
| [D2 two-case composite](../../artifacts/server-device-policy-composite-cases01/result.json) | `b66f7bb4516443854b4c222b4b69a76d19eebb423ecfa148607bcb04801d993c` |
| [Current Server cold integrity](../../artifacts/server-device-policy-cold-integrity-owner01/result.json) | `d94805cb2ba5bad6ee999ae15df10b971f4984bee1292e7dc3bcd9b4fc484507` |
| [Manager11 lifecycle03](../../artifacts/robot-manager11-lifecycle03/result.json) | `296fcc3762d692f38c1934753a79577cc54bfb28c0fb42256aee86a5ee21a4df` |
| [Replyloss02](../../artifacts/robot-a02-replyloss-02/result.json) | `b6744e8bdd9a0d54ec973dc19cbe579ffa06cb102d2054e651910f73c83f02d4` |
| [Contention04](../../artifacts/robot-a09-contention-04/result.json) | `59c49b6b9c1eac0d6b2173a278f7519721e8a4d0f4970e218ddcdf200cbc9927` |
| [Lifetime09](../../artifacts/robot-a10-lifetime-09/result.json) | `730b8fa965f8b714c1ba6ed25662c61faaa7535ae308dc10e6f5f88119db989f` |
| [Pressure-run11 capture validation](../../artifacts/server-a08-pressure-run11/capture-validated.json) | `92875b5c76811026708b67c025c54db14f3b3fe6d50c0b2228ee92301caaf840` |
| [Existing-handle cleanup review](../../artifacts/robot-retained-debit-finalize-cleanup-actual-review01/review.json) | `19223fd1dd083fcf8e56321c02bc830f9a70274f68385a1ede55db8a77b757c6` |
| [Module16 acceptance aggregate](../../artifacts/kernel-module16-acceptance01/manifest.json) | `00120810d6e385e32fe4d915852fbed819b9182cbf013aee668538dcb8d9a298` |
| [Selected Robot startup/parser review](../../artifacts/reconciliation-robot-startup01/parser-review.json) | `f34be51899457fbf245bcb74a85a210fa795aaec2bb80e9e5e6574d8a44304a8` |
| [Installed Robot package inspection](../../artifacts/robot-qualification-package-inspection01/capture.json) | `f774c54897482e119be5b52b2ce587dd906643c8950c655929e1df9f97ce02a7` |

Robot package inspection matches nine of ten pins: Expat remains2.9 against
pinned2.8.3. That limits exact installed-Robot cohort equality and says nothing
about the separate A16 disk. A16's new kernel11 baseline is separately approved
and bound above; it does not establish historical provider equality. Final
selection must also retain build/link/source-material and notice
provenance, genuine release-signing inputs and external A13/A14 evidence. No row
in this document is a whole-release PASS, physical qualification or CI result.

## Server111 native sandbox and Broker evidence

Fresh guest boot `364d9871-2a69-475d-8d6a-0db37b4275f8` binds exact kernel
`6.12.111+deb13-amd64` and TEST f32. Cold preflight verifies all 27 payload files,
four providers, five old registry trees, full 25/23 rows/logs and the Server
preservation subset. One supported `server import` adds OCI
`sha256:25e3512d1392fda61c701373fe2ff9885e1b173a01edcd9dfa4da5db1e95fe7c`,
with static agent SHA256 `0669b102259bbe325c676355ebbbe9dfee800248e0d5209c682ac6bdad006e53`.
The new configuration is
`cd9a365ff014879670fda6cfc6dbdefa3addf84e5475363deccac4f25bc93d03`:
six charged registry trees and five approvals, preserving every old tree and
approval; capacity remains eight. This is an additive qualification fixture,
not a new release package or a post-import repeat of the full payload audit.

One sandbox attempt `e4fcd5e8dee07e05f67fd0842d765045` emits individual native
negative records and five Broker cases. Independent saved-only review passes the
unchanged complete proof: ten syscall denials, 196 trace records/loss0, selected
OCI/ELF/runtime/device/cgroup attribution, fork/both exits and exact export/logs.
Agent stdout remains untrusted but bound to the selected source and execution.
Only the `admin.grant` record supplies Broker policy-denial origin. AF_INET socket
denial and zero routes do not establish an attempted external connection;
missing seccomp-enter events do not establish policy origin. No host execution
of the ELF, Robot request/binding, operation replay or physical actuation occurs.

The original owner remains **FAILED**: after known Cancel it skips Broker Status
when Launcher already reports reaped, then compares empty delegated calls/denials
against the Broker export. A separate bounded Status obtains the actual two calls
and one denial. Shared attempt/artifact/runtime/state/outcome match; Launcher and
Broker Start deadlines are independently set, 727224 and 727172 ms. Both raw
replies and deadlines stay unchanged. The original failure reproduces using the
original Launcher view; full unchanged validators pass using the actual Broker
view. These are separate results, not a corrected campaign PASS.

Separate known cleanup stops the same three service lifetimes and restores the
three temporary Restart files. Cold full-row/log proof retains 26/24 Server,
16/21 Robot, zero debits and all 374 preservation entries. One normal poweroff
confirms original pidfd death and new serial markers. Final stopped custody02
verifies 42 inactive host units with empty cgroups/NRestarts0, no repository
VM/fixture/QSD/FUSE, selected listeners or image holders. Current Server disk is
`e9aea9961786c5f30d9cf5c83911e74bdd245b14c0f6891a3924386d9d2f7ecd`;
other eight public records, both fixture journals, extracted boot files and
three metadata-only keys are unchanged. Custody01's overstrict host user-systemd
exe permission check remains FAILED; its numbered correction performs no target
action. A non-dumpable unrelated systemd process is filtered by readable argv
before resolving executable links for repository/actor candidates.

The poweroff review copy's generated-program hash `82e11267…3e658` differs from
actual dispatched bytes `bc307375…1778c`. Saved-only regeneration proves equal
CTX values, an identical frozen guest-source tail and exact reproduction of the
actual bytes from the pinned saved context; the difference is first-line Python
dictionary key order after JSON reload. [Exact association](../../artifacts/server-native-proof-final-independent-review01/poweroff-program-association.json)
SHA256 `166ca44dc8a9363af3e135a01498ae9711326e71c3acb8e41605b9a627247ff2`
retains both hashes. The review copy is not claimed byte-identical to dispatch.

The additive [D2 predicate association03](../../artifacts/server-final-d2-predicate-map03/association.json)
SHA256 `fcebbe2d6a1d752f276d96659eea3e5783f7aac88aa47241f94676f95ec72853`
retains all 17 original predicate IDs and their remaining source/cohort scope.
At frozen map03, D2-05's literal negative-connect test stays **OPEN**: the fixed profile denies
AF_INET socket creation, the prebroker scan finds no inherited socket and topology
has no route, but no external/controller connect syscall is observed. The supported
prevention invariant is recorded without waiving that test or relaxing the profile.
The later [namespace association](#created-task-network-namespace-proof) adds a
separately attributed functional negative; this frozen map remains unchanged.
Root's [separate composition decision02](../../artifacts/server-final-d2-predicate-map03/root-composition-decision02.json)
SHA256 `0ebd4ac246d2931988b177d15fdb5123a216f38c4404195a6a022b949bfe2644`
accepts the existing device/OOM and native access/Broker/export/cleanup cases as
preview diagnosis coverage. They remain separate attempts/configurations; the
exact single multimodal-batch story is **NOT_RUN**. This resolves the preview
composition decision only, preserves frozen map03 and closes no whole D2 gate.

The maintained [Broker regression](../../apps/server/tests/test_broker_evidence.py)
and [inspection contract](../../apps/server/tests/BROKER_EVIDENCE.md) pass 83 host
Python tests. Separately numbered guest harness amendment02 always fetches Broker
Status after known Cancel and retains both source deadlines; four original
counterexamples fail and six amended host checks pass. Its target execution is
**NOT_RUN**. Frozen original sources/validators and failed markers are unchanged.
Whole D2, final coherent artifacts, failed A16, live-model acceptance, independent
human installation and genuine release signing remain incomplete.

| Saved receipt | SHA-256 |
|---|---|
| [Native build](../../artifacts/server-native-proof-build01/receipt.json) | `4db2527e9f4be5feab889d3259660c85ecdc18e270526d5dd833b9cc509f82a0` |
| [Cold preflight](../../artifacts/server-native-proof-preflight01/result.json) | `a9be31803c35ef70b94e5ff4921cb27e1bbf3209ae46f6f47521d434c39168b2` |
| [Original FAILED owner](../../artifacts/server-native-proof-owner01/result.json) | `a437ea07e9792d790420647b6641865c5f4ee67fb607f2ffcab5129e01b8871d` |
| [Separate status/readback](../../artifacts/server-native-proof-failure-readback01/result.json) | `9796a860dafa0896cc4c7756cb2972b895e168d7a2c572b524e4a8dd84e93403` |
| [Independent complete proof](../../artifacts/server-native-proof-actual-peer01/review.json) | `9da8100dfe14880e462d850fa039c65bb921088a3413a27540be8c4f3b326b87` |
| [Final independent custody/action audit](../../artifacts/server-native-proof-final-independent-review01/review.json) | `ce636fd43f7d39498f7ffab10a16e8ccddeda8f60ed1262d0e1bcdaecd709190` |
| [Separate known cleanup](../../artifacts/server-native-proof-failure-cleanup01/result.json) | `8eb6433cc837fed52695b656bb23b41222606b39c3467ea1be8b65fc37ee0d9b` |
| [Final full Server rows](../../artifacts/server-native-proof-failure-cleanup01/native-cleanup-cold-final-seven-tables.json) | `e9386c04fdf07b6b2ff9739cc0ccf605a5693fd572668d89ed0ef2f2b0fd3f52` |
| [Normal poweroff](../../artifacts/server-native-proof-poweroff01/result.json) | `ded572661a5c4630be0375374d96df051b6b3f9815494cea683af659ea15ad84` |
| [Final stopped custody](../../artifacts/server-native-proof-final-stopped-custody02/result.json) | `35daa5f810cc4b0ff2461e19439d252fe2421ebbe14cbb3014634bbb71b67bf4` |
| [Host-only harness amendment](../../artifacts/server-native-proof-inspection-amendment02/verification.json) | `79374428cbdedf83712846713c94e1e02e27e88e6c7e1e9d892a37f34917830a` |

## Diagnostic9 build only and current source gaps

One compile-only boot `b0e13f6b-b80b-4dcb-ba56-ab08c56cb7ca` runs exact
`6.12.111+deb13-arm64`, protected DTB, 2vCPUs/2GiB and the null controller backend.
The actual guest GCC14.2.0 build verifies the approved 375-package catalog,
compiler-driver/linker/readelf hashes, two resolved providers and four original
artifacts. It preserves original workload source c94c2972…6b32 and uses the
reviewed diagnostic9 derivative 1c4fae3c…a0a43. The result is a 74704-byte AArch64
ELF, SHA256 `045d9bcd534dc673ad091b842d2ae4f21146862a882450660e295003a638a612`,
GNU build ID `9d25126cec88dafbfadd892be2b6c0699be02946`. Public source, actual
compile argv/catalog/tool reports and ELF are retained; a complete historical
compiler helper/header/startfile closure is not claimed.

The binary is never executed on host or guest. No module, gateway, fixture or
controller protocol runs. This null-transport compile environment is distinct
from the future raw-userspace observation configuration. The build candidate
keeps Root observation approval, future observation boot/fixture and execution
NULL/NOT_RUN. No new A16 comparison trial has run; the original 80 trials,
20 excluded pilot trials and FAILED79/80 result remain unchanged.

One normal poweroff and independently bound host/guest closures precede current
stopped custody: 46 inactive checked host units, no repository VM/fixture/QSD/FUSE,
selected listener or image holder. Both fixture journals, three metadata-only
keys and the other eight public records are unchanged. A16 disk is now
`9378b3ad80830908450f1b8a0dc135a933e6292f2aa42395576cf4637c5649e4`;
Server e9aea996…f7ecd and Robot4dc0c78b…92366 remain unchanged, carrying current
26/24 Server, 16/21 Robot, zero debits and all 374 preservation entries.

The [D2-01/02 source association04](../../artifacts/server-final-d2-runtime-association04/association.json)
records current installation reuse and the selected runtime Create/Start FIFO
source boundary, including exact source/patch inputs and build-provenance limits.
Under that frozen original baseline, D2-02 remains OPEN for the pre-Create
broker/enforcement requirement. Source reserves identity/cgroup/attribution and
the broker directory first, then installs the filter/listeners before Start;
the current approved contract below explicitly adopts that gated sequence.
The separately pushed [eight-line ordering proposal](https://github.com/volnlabs/actryn/compare/f321a0d74ccc2f880445aa6e0018e26e4714badb...4f7e3776afc065da6c1560d40c6b6802ab26f959)
was approved by the user and integrated exactly as `025e36e`. The original normative
contract is preserved byte-for-byte in its [snapshot](../../artifacts/server-launch-order-clarification-proposal01/original-contract.md)
for frozen maps; no original evidence or predicate is rewritten.

Review of the original launcher also finds a distinct cleanup gap: binding-verification errors
use the common retirement/cleanup path, but later observer health/socket errors
return directly, leaving the Launcher prepared until finite expiry while Server
publication closes. [The narrow fix plan](../../artifacts/server-prestart-cleanup-fix-plan01/PLAN.md)
requires an actual old-binary regression before implementation, on an isolated
scratch Server because the legacy fixture overwrites global configuration and
ownership. The actual old-binary RED below reproduces that missing-broker path. The isolated
fix now passes the complete corrected GREEN04 fixture below.
Literal D2-05 negative-connect evidence, final cohort qualification, A13/A14,
genuine release signing and the failed A16 comparison remain open.

| Build/source receipt | SHA-256 |
|---|---|
| [One actual compile-only sequence](../../artifacts/a16-bind9-compile-root-review01/result.json) | `0928f8403c6c80429c778cfaa888f18f686b3d3d6474a221827023892d523c59` |
| [Actual native GCC14 build](../../artifacts/a16-bind9-compile01/result.json) | `4e893fabfae4dc1fdd6595d2238157390614607d598993163d7d899788aafb2a` |
| [Independent saved-build audit](../../artifacts/a16-bind9-compile-actual-peer01/review.json) | `9db4422a11001e19c6fde41996bcedc4baf95a6cac801d3bb43c67d78b99faaf` |
| [Unapproved build-only candidate](../../artifacts/a16-bind9-compile-root-review01/diagnostic9-build-candidate.json) | `5f0c1ef21b7fc5158e261afcb739f959a3bbfa314c668f536f959e0438deb390` |
| [Compile-only 46-unit stopped custody](../../artifacts/a16-bind9-compile-final-stopped-custody01/result.json) | `6bf2fc300dd4ecdf704333a6dc838f89c63e17030d0173c36fc2ac9adb51b613` |
| [D2-01/02 source/runtime association](../../artifacts/server-final-d2-runtime-association04/association.json) | `db16b0671f4541393bce57df538f78d70b9bcfe3d815cdf9e0964afa028b89d3` |


## Approved ordering and actual pre-Start regression

The user approves the before-Start proposal `4f7e377`, integrated byte-for-byte
as `025e36e`. The current contract hash is
`315734b43734f9200ebd2e35cd977a60fcf91dedbd9d85c38fb2805100046b0a`.
The original `7bd1738b…43ef1` contract snapshot and frozen maps remain unchanged;
their historical literal-order conclusions are not rewritten. Application entry
must remain gated until verification finishes. Whole D2 is still open.

One private standalone clone of the retained Server boots exact kernel111/f32
at `00ae01fa-4ad9-44fa-b5ab-bcc1304475fa`. The unchanged launcher rejects the
missing-broker Start for attempt `8770cdfc99d804296a1588404a574b9d`, but actual
inspection remains prepared. The immediate state assertion produces raw rc1;
this is the intended old-binary RED, independently reviewed. The fixture's known
finally Stop reaps that attempt with empty stdout/stderr. Later observer and
healthy cases remain NOT_STARTED. All old 26/24 full rows are preserved; only
one Launcher attempt/runtime-evidence entry is added, leaving clone27/24 and
zero debits. A dependency-closure PASS never changes the failed test to PASS.

One acknowledged normal poweroff, original pidfd death and fresh serial shutdown
markers precede the RED stopped custody: all 51 checked host units inactive,
original nine public records, three key metadata records and fixture journals
unchanged. At that RED checkpoint the private clone has SHA256
`7675877bcfc65b13617cf6b03eac051c9028306f17dce9f285290453fd20be0c`.
Original Server26/24, Robot16/21, zero debits/all374 entries and original A16
FAILED79/80 remain unchanged. No installed release component is replaced.

The narrow fix `e6c3fd6` on its isolated branch passes 66 Server package tests and
formatting with pinned Rust1.92, offline/j1. An initial E0277 compile failure is
retained; the corrected mutable async capture passes. One host launcher build
produces the 14139888-byte ELF
`3ead4e49f73954137034910028e49a5fad4b0b34d0eeb36c908581447f2afe30`.
Static checks preserve all 31 allocated sections, match 154 exact retained-target
symbols and retain 22 native inputs. This cached build is not hermetic; target
providers must be checked freshly before execution. The original pre-exit
catalogue pins an empty redirected analyzer stdout; a separate post-exit
association records its exact 328-byte tail and all 50 completed files without
rewriting the original catalogue or rerunning anything. The corrected-binary GREEN04 below passes; final candidate/cohort qualification,
literal D2-05, A13/A14 and genuine release signing remain pending. This regression gives no physical qualification.

| Approval/regression receipt | SHA-256 |
|---|---|
| [Exact approved integration](../../artifacts/server-launch-order-approved-decision01/result.json) | `405620fe0954ea0879da673e13500b51f0f6382f5bb9d55df33e6ee8ea964956` |
| [Actual old-binary RED classification](../../artifacts/server-prestart-cleanup-root-review01/old-red-classification.json) | `32aaf351742f21950b73c3e74bd2dced0ef17e877748a72d7de51aa50b62a8ab` |
| [Independent actual RED audit](../../artifacts/server-prestart-cleanup-actual-red-peer01/review.json) | `c358b9cbd515cd5edfc119fb5331786309891c0a7525a09b70a5038980bfa5de` |
| [Normal scratch poweroff](../../artifacts/server-prestart-cleanup-poweroff01/result.json) | `bd3cb820a424c2396ee209a3990bbd89ee0e9b22176f4b90a7853986a59503ec` |
| [RED 51-unit stopped custody](../../artifacts/server-prestart-cleanup-final-stopped-custody01/result.json) | `9bf9810e8bc690fb2da7066df6bad1f210d25c5ce03a1ec601e1b6a17bd7a8a5` |
| [Independent shutdown/custody audit](../../artifacts/server-prestart-cleanup-stopped-actual-peer01/review.json) | `1abdbe29c269fa2fe7d744d6795f741301c7069fcdcca0ecbfd316f19d786c71` |
| [Isolated signed-off fix commit](../../artifacts/server-start-cleanup-fix-commit01/result.json) | `c431262c77c4c6495a269def80775525c4b8568a65964eb4a183820b4c4c419b` |
| [Actual host build/static provenance](../../artifacts/server-prestart-cleanup-build01/provenance.json) | `2dfc87a362703005dea50b232cead639a950908a4632b4055eafc32005553a23` |
| [Completed catalogue association](../../artifacts/server-prestart-cleanup-build-final-inventory01/result.json) | `a6a6badbe0ed95232fb79957fafa2d6cfa503c082de98459604eb87d1d372705` |

### Numbered GREEN preparation and fixture failures

Green01 boot `4c6f6cde-cc4e-46d0-9976-700859d0d858` uses only the private
regression clone. Setup01 stops before standalone candidate staging, provider
checks, dependency starts, import or Prepare: its directory guard expects991,
but current installed account/directory are987 and the installed tmpfiles rule
matches. The actual boot actor is not independently traced. The persisted
scratch lock/config retain991. Raw rc1/remote uncertainty and the seven-file
partial stage stay unchanged. Read-only reconciliation verifies all seven
27/24 tables unchanged and known host/guest closure, with no state repair.

Numbered setup02 corrects the exact directory guard to UID/GID987/0700 without
chown. Fresh target-provider checks pass before the fixed ELF executes.
Missing-broker attempt `d67f5435d0f16afba462d3245c01c87e` rejects Start, reaps,
confirms original pidfd death/empty output and rejects replay. Observer attempt
`07603b3653a44251d912b5e742e769fe` rejects Start and retains its charged
retiring/cancelled row and binding, then fails the fixture's physical cgroup-path
assertion. Launcher unregister precedes its explicit rmdir; runtime deletion
can precede unregister, but the actual deletion actor is unobserved. Retained
admission identity is the durable non-reaped row, not the transient path.
The original pidfd wait, restore/reap test marker and healthy/admission controls
are NOT_REACHED. Its finally restores the exact socket and known Stop reaps.
Cold29/24 preserves every old row/log, adds only two Launcher attempt/runtime
rows, and has no outstanding Robot debit. Component rc1 remains failed even
though dependency and outer host scopes close successfully. At this failed02 checkpoint the scratch VM remains on. The later full GREEN04
and normal shutdown below supersede that carrier state.

| Numbered failure/reconciliation receipt | SHA-256 |
|---|---|
| [Green01 preparation reconciliation](../../artifacts/server-prestart-cleanup-green-preparation-readback01/result.json) | `5309cfdbbb9cef625e412c0fa82fb968c838b9854804eff6fec5337f04552760` |
| [Independent Green01 reconciliation](../../artifacts/server-prestart-cleanup-green01-readback-peer01/review.json) | `608c86be61d413e0baa05d1e40b063a0b3bc51b81fb54b324d623530f021c1aa` |
| [Green02 failed fixture classification](../../artifacts/server-prestart-cleanup-green-root-review02/green02-classification.json) | `bf9ac4fd9fc9aa63314150056585d32af9b827b374086fec9af7b2836e079240` |
| [Independent Green02 failure review](../../artifacts/server-prestart-cleanup-green02-failure-source-peer01/review.json) | `8e25ef257e2f3c491227bfae1aa485e01b38c95ef7daba6d3ab4bcb5fc492bcb` |

### Full GREEN04 and current stopped custody

On the same private exact111/f32 boot, fresh invocation04 runs launcher3ead from
sourcee6 and fixture106108 from signed-off source8fae. The fixture selects the
already approved50a artifact from actual02's reviewed C build/import. It performs
no fresh agent compile/import/configuration rewrite, preserving registry capacity.
All four source-bound cases pass with harness rc0 and empty stderr: missing-broker
Start cancels/reaps without execution/replay; observer-unreachable Start retains
exact durable retiring identity/binding after original task pidfd death while the
socket is hidden, then reaps after exact restoration; the healthy case executes
only its expected marker and rejects duplicate Start without cancelling; normal
active-capacity refusal preserves the second preparation and first running task.
The assertions and markers establish these cases; separate per-RPC kernel traces
are not claimed.

All four new attempts finish reaped. Their negative/capacity output is empty;
the healthy output is exactly `AGENT_STARTED` plus newline, and all four stderr
logs are empty. Full prior seven-table rows/logs remain unchanged as multisets;
only four Launcher attempt/runtime rows are added. Final clone33/24 has zero
Robot debit; Broker24 is unchanged. The independent saved-byte audit agrees.
The failed01/02/03 and failed read-only probe remain untouched, including their
unknown flags. Before04, separate reconciliation proves unchanged29/24 and two
exclusive consumed intents remove only the exact verified dead socket pathnames.
No database repair, ownership change, retained-artifact deletion or quota change
occurs.

One acknowledged normal poweroff, original QEMU pidfd death and fresh serial
shutdown markers precede current full custody:59 actual host units inactive,
MainPID0/empty cgroups/NRestarts0; original nine public records hash identically
at both bookends, three private keys remain metadata-only, and both fixture
journals are unchanged. Original Server26/24, Robot16/21, zero debits and all374
entries remain carried by their unchanged disks. The separate private clone is
`fa9fd3f4e00e00ce9ed95697f377b5b74d5be0fa1ed18734819529aa346ee89d`.
All VMs and fixtures are off.

The three exact signed-off source commits integrate as `e6120d3`, `71696f2` and
`ecc5a8b`. All85 maintained Server Python tests pass; the source-bound66 Rust tests,
formatting and actual target-provider checks remain separately recorded. This
closes the pre-Start cleanup regression only. Installed f32 remains unchanged;
at that checkpoint final Server package assembly, whole D2/final-cohort qualification, A13/A14,
genuine release signing and the failed A16 comparison remain open. Physical qualification remains
outside this software preview.

| Current GREEN/shutdown receipt | SHA-256 |
|---|---|
| [Full GREEN04 classification](../../artifacts/server-prestart-cleanup-green-root-review04/green04-classification.json) | `a91a8a9ae5b8e0b8ffdd81614769c04d6048bb8b622a94324ec534c3e16c0ece` |
| [Independent actual GREEN04 audit](../../artifacts/server-prestart-cleanup-green04-actual-peer01/review.json) | `c1baf1535f24f3a51ad9071455c3db4af620a32eee03eef4c1f42d3071f3e0ed` |
| [Prior03 preparation reconciliation and cleanup](../../artifacts/server-prestart-cleanup-green03-preparation-reconciliation02/final-result.json) | `ec2a63fbb3435e07d9e28d87362b4f54f03cb0c9cd681e23f65513edd8b4e742` |
| [Independent exact socket-cleanup audit](../../artifacts/server-prestart-cleanup-green03-stale-socket-cleanup-actual-peer01/review.json) | `86618ee4abce4b2e22528bad17eb368845296e121394e5e80e11b1a6c4d844fe` |
| [Normal scratch poweroff04](../../artifacts/server-prestart-cleanup-green-poweroff04/result.json) | `3dbdba3abbfa5a95ce86549a28cb044139a80783df6ea1778a05ac9e2f81ff93` |
| [Current59-unit stopped custody](../../artifacts/server-prestart-cleanup-final-stopped-custody04/result.json) | `9101ddce91a6fd21e580b0f8474c9cbef29dc4c1b574c971838794661b4ecc52` |
| [Independent shutdown/custody audit](../../artifacts/server-prestart-cleanup-green04-stopped-actual-peer01/review.json) | `3de0d536b2d6c5f9bc704686979de8d60230d2c161ceeda7a9148383622d9603` |
| [Exact signed-off integration](../../artifacts/server-start-cleanup-integration01/result.json) | `cbb3921d5f5b90c969467a8437a0eb5eb24b9b234bf8cb7196ed83687f0786bc` |
| [85 maintained Python tests](../../artifacts/server-start-cleanup-integrated-python85/result.json) | `17385566bea57423e5169e922c2e00774858de63f7c2809894a8ee0d0b8e17c2` |

## CREATED-task network namespace proof

Fresh exact111/f32 scratch boot `9691950c-6f38-4062-9fc7-1ded8c4db2e1`
executes staged launcher3ead with the already approved50a artifact. One Prepare
allocates `496415bbfd8adab8f4b2c830b6c61509`; no Start is sent. The trusted verifier
holds the task pidfd and network-namespace FD, checks identical CREATED/PID/start/
cgroup/namespace/empty-output bookends, joins only that network namespace, then
creates a valid AF_INET TCP socket. Its single connect to 203.0.113.1:443 returns
ENETUNREACH (101). Complete link/address/all-table IPv4/IPv6 inventories are
unchanged and contain loopback only. The verifier keeps its own cgroup and six
other namespaces; the agent profile and installed payload are unchanged.

One known Stop cancels/reaps the task with empty logs and no remaining task,
attempt cgroup or broker directory. Cold-copy comparison against GREEN04 proves
all prior seven-table rows and logs unchanged, adding one Launcher attempt/runtime
row only:34/24, all reaped, zero outstanding debit. Registry/configuration checks
also pass. The staged launcher exits on its known SIGTERM, the owned observer
stops and the existing containerd lifetime is preserved. Guest and host owners
exit zero with inactive/PID0/empty scopes. One acknowledged normal poweroff,
original QEMU pidfd death and fresh serial shutdown markers are verified.
Final stopped custody verifies all 64 target/prior-owner units inactive with
PID0, empty cgroups and no restarts; the custody owner separately exits zero and
closes its scope. All nine original public files, three metadata-only keys and
both fixture journals remain unchanged. Private clone SHA256 is
`ea94d7f0ed2ba9cc1fcddffcec83d187904b8edc03ae244bbccf5ebdb23cf278`;
original Server26/24, Robot16/21, zero debits and all374 remain preserved.

Association05 accepts scoped preview network coverage by composing this trusted
namespace negative with the earlier actual agent AF_INET denial, no inherited
sockets and permitted AF_UNIX Broker traffic. These are separate attempts and
launcher versions. No agent-origin external connect, whole D2, final-package
qualification or physical proof is claimed. Frozen map03 and the original failed
native owner remain unchanged. Verifier source723ec39 is integrated as f8f18a9;
11 focused and 96 complete maintained Server Python checks pass. The execution
adapter separately passes ten pure checks.

| Receipt | SHA-256 |
|---|---|
| [Root namespace classification](../../artifacts/server-network-proof-root-review01/execution-classification.json) | `2de60ece0168e341cb14be6e5bad3d5468daab01632d9b5779ebac4cc2fe4db3` |
| [Additive D2-05 association](../../artifacts/server-final-d2-network-association05/association.json) | `4605532a43b465b2169cfdfa22f3f544de872a8c6c47b3a13f2b159d348a908b` |
| [Known normal poweroff](../../artifacts/server-network-proof-poweroff01/result.json) | `4811df32bb2e333aeea0f154ffb7a98ae8b585c170cc721ecdfe3407568ff336` |
| [Poweroff owner closure](../../artifacts/server-network-proof-root-review01/poweroff-owner-closure.json) | `5cdd3addd2f7c670d461066d25a05a0796a2f22d0a20c895c208f0e2e395f908` |
| [96 maintained Python checks](../../artifacts/server-network-namespace-fix-validation01/result.json) | `b38aee249d155f62082d4887a76097bfd2658dd5b36a11d444c35b3eb73b56ca` |
| [Independent actual network audit](../../artifacts/server-network-proof-actual-peer01/review.json) | `072e20f30af40928c56165273313a6deaf5633d476074cb0218afe263e3b1658` |
| [Final stopped custody](../../artifacts/server-network-proof-stopped-custody01/result.json) | `a1b6f4f25e7a0649e9ea012e719bac2256c40eb88d8c9c4de3fc99bdb44d401a` |
| [Custody owner closure](../../artifacts/server-network-proof-root-review01/custody-owner-closure.json) | `24e6ae891374d08a7e749a4150823df773b71af3cc511e36a100c102679488f0` |

## Diagnostic9 boot01 mode guard and cleanup

Boot `5b244b89-d042-48f9-bc45-0d1af3324078` fails the read-only diagnostic
file guard before any workload, gateway or authority action. The guard assumes
`0755`; separate read-only metadata and hash collection finds root-owned mode
`0700`, 74704 bytes and exact SHA045d9bcd…a612. No permissions or binary bytes
were changed. Offline validation of the saved package/provider observation
passes the original baseline; it gives no workload credit.

Unused cleanup completes with one acknowledged normal poweroff, original QEMU
pidfd death, fresh serial shutdown markers and one supported fixture shutdown.
The first local poweroff owner exits1 on a relative input path before input
admission or guest dispatch. Its record remains unchanged; the separately
numbered owner with an absolute path exits0 and closes its scope.

Boot01 stopped custody streams all nine public files and the private clone
with metadata/no-holder bookends, checks key metadata without reading keys,
and verifies 69 prior units inactive/PID0/empty cgroups/no restarts. Its own
owner subsequently exits0 and closes. At that checkpoint, the A16 disk is
`d1b38a1be163be7fb19cee0db238732bece31d51baad23767b698d99bf446691`.
The other eight public files and private clone remain unchanged. Fixture
boot145/2924 bytes preserves the boot144 prefix plus one 20-byte restart;
there are zero diagnostic appends. Server26/24, Robot16/21, zero debits and all
374 preservation entries remain carried by unchanged disks. Historical64-unit
network custody and build disk9378 are prior checkpoints.

The later separately numbered observation02 below uses strict0700 validation.
At boot01, diagnostic execution remained NOT_RUN. The frozen A16 comparison
remains FAILED79/80; no retry, pooling or physical qualification is claimed.

| Receipt | SHA-256 |
| --- | --- |
| [Failed boot](../../artifacts/a16-bind9-boot01/result.json) | `ae121de6c61a75ad1ded02387dd6a33ec0714027380f74f65c20d13f6fe2fe13` |
| [Read-only ELF metadata](../../artifacts/a16-bind9-unused-root-review01/metadata-readonly-once.stdout) | `f001e144a76cfbe2c7a383fefc76830025cd5a0635675e29f695b36f6e43b065` |
| [Saved original-baseline check](../../artifacts/a16-bind9-final-stopped-custody-root-review01/saved-baseline-check.json) | `2c03b166e8197f350cc00943ae2cfc0777cb5f99579304fe09bbd0def11f2f2c` |
| [Normal unused VM poweroff](../../artifacts/a16-bind9-unused-poweroff01/result.json) | `84a92c7eea5695874d8d399879162f532dcf5be17ef73def2e19e39f3b3387c7` |
| [Fixture shutdown](../../artifacts/a16-bind9-unused-fixture-shutdown01/result.json) | `a1a62022b849c53bde03ecfce72aff4807727a6585923712a817fd9bb44c39a1` |
| [Local input-path failure correction](../../artifacts/a16-bind9-unused-root-review01/local-path-correction.json) | `d3c16c2d2a5c2b73d503c9f0f90e019db5992bc7c5d3eb8d6492ea787e3af043` |
| [Boot01 stopped custody](../../artifacts/a16-bind9-final-stopped-custody01/result.json) | `9f98faf6a94416fc048ddb2fe35fa745577cf61d6f836fbedfef18d46710cb24` |
| [Boot01 public byte custody](../../artifacts/a16-bind9-final-stopped-custody01/public-custody.json) | `b4a2d74ef1233d79364481d0c3dc3ad724e7309de40b8cb9a19e0bcbd0ccc1ae` |
| [Known custody owner exit](../../artifacts/a16-bind9-final-stopped-custody-root-review01/custody-owner-once-result.json) | `b6905b668ea636575ac17e64926903119c18fdb9522afdfd1290de2ca8ee7fa4` |
| [Custody owner closure](../../artifacts/a16-bind9-final-stopped-custody-root-review01/custody-owner-closure.json) | `17cc9fc4815b507b3948cf4641b26b453c8cec3636ada393ef0b620dbe0027b5` |

## Diagnostic9 observation02: ten trials

One separately numbered evidence-only userspace diagnostic executes on boot
`99c9462f-8c29-4227-aec2-78874fdc25c5`, exact kernel111 and the original approved
catalog/providers/four-artifact baseline. ELF045d9bcd…a612 is unchanged. The
shared read-only guard now requires exact0700, matching its original native
build under umask077. The old guard fails the new regression; twelve amended
offline checks pass. Boot02 and unused fallback sources pass eight and five
checks respectively; frozen01 sources/failure records remain unchanged.

All ten trials begin, end and pass: normal, cancel, delayed-applied and owner-exit
scenarios use unchanged55/60-second workload bounds and the original490-second
whole window. There are no BIND-failure records. The summary retains62 samples,
60 timely applied and two intentional no-timely-applied outcomes, with zero new
recorded event loss. The784 raw event rows are copied byte-identically to the
Root evidence folder. This diagnostic executes no authority module and collects
no UART dispatch trace; it is not kernel or physical qualification.

Original before/after cohort comparison passes. Both retirement fences close,
workload/gateway/relevant descriptors are absent, one normal poweroff confirms
original QEMU pidfd death and fresh serial markers, and the original fixture
then accepts one supported shutdown. Owner exits and empty scopes are recorded.
Final custody streams all nine public records and the private clone with
metadata/no-holder bookends, checks only private-key metadata, and verifies74
prior units inactive. Its own owner also exits0 and closes. A16 disk is now
`cf7b67ab25401a6cb9afeb604d582f5b52d098e37f44b26796b643afd5f987de`.
Journal boot156/3144 bytes preserves boot145 plus one fixture start and ten
diagnostic appends. The other eight records, clone and keys' metadata are
unchanged; original Server26/24, Robot16/21, zero debits/all374 remain preserved.

The original comparison remains FAILED79/80. No failure reproduced here, so
its historical BIND role, errno and cause remain unobserved. These ten trials
are excluded from that comparison and its two prior pilots. Neither a whole
A16 acceptance pass nor a superiority, WCET or physical claim follows.

| Receipt | SHA-256 |
| --- | --- |
| [Corrected guard checks](../../artifacts/a16-bind9-observation-plan02/verification.json) | `5e18582d98617b1bc966f25cb53f91f4567075518f8c8b8b72084eed1564818c` |
| [Boot02](../../artifacts/a16-bind9-boot02/result.json) | `4f24c1d7398eadc4b085acbc092c27875d483c8d764a92d7ca41879801914ded` |
| [Diagnostic result](../../artifacts/a16-bind9-observation02/result.json) | `aba80814cd38be13edd99b03f18c5cdfe6f1dd91b3bccb69f2f77d4b5d0a7436` |
| [Ten-trial progress](../../artifacts/a16-bind9-observation02/diagnostic-progress.json) | `b6dd8974ddbb35ac987b2a1dcd32b8751ae4434a2fef12f4bd55998b06a35d3c` |
| [Cohort pair](../../artifacts/a16-bind9-observation02/pair-validation.json) | `f93195375e6b2ffe8ce025516ff7d233d588e7e48abc822ca21643b4c1e4f241` |
| [Root classification and raw copy](../../artifacts/a16-bind9-observation-root-review02/classification.json) | `1b3e91a57d3c07502475366a14ad743b5dcd64f5c81a1ee587d867a1b7e73b2f` |
| [Fixture shutdown](../../artifacts/a16-bind9-fixture-shutdown02/result.json) | `e27bb1e582443962113acb7fb4a759f47d9d5aa95e827da8602b4b888ba5c87f` |
| [Final stopped custody](../../artifacts/a16-bind9-final-stopped-custody02/result.json) | `4154a0ac5cbda23f3655a12312df156bf502913802d29edfd1ae5e272864ae31` |
| [Public byte custody](../../artifacts/a16-bind9-final-stopped-custody02/public-custody.json) | `76c58de821699c3d8856a4ec6bbbdc6fc5678f455cc1e984560cd7f7253d9857` |
| [Custody owner closure](../../artifacts/a16-bind9-final-stopped-custody-root-review02/custody-owner-closure.json) | `f9742c1bede4e9ce9421f44297ebc0320e96db78b3cf6ec37203b36fa2d78106` |
| [Independent saved-evidence audit](../../artifacts/a16-bind9-observation-actual-peer02/review.json) | `827e3cf3dcbf3c27150e6e42cfb4527a4d3f60d1f8fa91fd627a2c3eb62b4ab1` |
