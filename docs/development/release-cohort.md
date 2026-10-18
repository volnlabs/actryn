# Release cohort and case evidence

Read-only source/evidence reconciliation, 2026-10-18; preceding verified push
`f321a0d` ([push21](../../artifacts/reconciliation-checkpoint-push21/result.json), zero CI runs; no CI pass).
This additive map closes no whole D2 or A01–A16 row. It records selected bytes,
actual case evidence and the specific work still needed to make a release claim.
The [approved matrix](../superpowers/plans/2026-10-16-actryn-v0.0.1.md#acceptance-matrix),
[D2 contract](../superpowers/specs/architecture.md) and
[platform profile rules](../architecture/platform-release-contract.md) remain authoritative.
All hashes below are SHA-256. Artifact links refer to retained, ignored local
evidence; pushing this document does not back up those files.

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
| Server `8d6e71d` archive `79acc8689f9eef8098be5ca4ba0911e0e5285cfa9e2ac34375f73a4d55732831` → launcher `14afd962` archive `270cda4667aea8206012a35c2395f4f705e9448e86a25f9e230d679f91ce7d03` | Within Server production source, Server Cargo.toml, robot-rpc, Cargo.lock and service units, only `bpf/device_policy.insns`, `src/{device_policy,launcher,lib,policy}.rs` and the launcher unit differ. | The final delta is fixed-filter installation after paused task creation, direct/effective MULTI inventory verification before Start, and loader capability. Host instruction/interpreter and binding regressions plus actual D2 filter evidence cover that delta; they do not re-execute every older sandbox case. |
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
| A12 | Fresh installation/interruption tests; current f32 cold stage/activate/resume and startup02; d77 update/startup/history custody. Unsigned da6b merges the two reviewed documents and preserves the other 15 entries. | New candidate remains uninstalled, unsigned and unqualified. Runtime-only qualification Restart=no drop-ins are recorded test configuration, not the packaged Restart=on-failure policy. |
| A13/A14/A16 | Live-policy/missing-credential controls and observer evidence remain separate. Both excluded pilots pass. The [completed A16 comparison](a16-comparison.md) retains all 80 trials: 79 PASS/1 B3 evidence BIND failure; six cohort pairs and four 78/78 diagnostic correlations pass, with independent audit and stopped custody. | A16 workload acceptance remains FAILED; bind role/errno/cause unobserved. Live-provider provisioning, independent installer, signing custodian and release identity remain unconfirmed. Historical failures/diagnostic8 retain their boundaries; no equal-work, physical, WCET or superiority claim follows. |

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
independent audit `4257e045…ef0865`. Latest A16 stopped custody is B4: 24 inactive
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
D2-05's literal negative-connect test stays **OPEN**: the fixed profile denies
AF_INET socket creation, the prebroker scan finds no inherited socket and topology
has no route, but no external/controller connect syscall is observed. The supported
prevention invariant is recorded without waiving that test or relaxing the profile.
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
D2-02 remains OPEN: the contract puts the broker socket and live enforcement
before Create, while current source reserves identity/cgroup/attribution and the
broker directory first, then installs the filter and listeners before Start.
The separately pushed [eight-line ordering proposal](https://github.com/volnlabs/actryn/compare/f321a0d74ccc2f880445aa6e0018e26e4714badb...4f7e3776afc065da6c1560d40c6b6802ab26f959)
is not integrated and awaits the user's scope decision. The original normative
contract is preserved byte-for-byte in its [snapshot](../../artifacts/server-launch-order-clarification-proposal01/original-contract.md)
for frozen maps; no original evidence or predicate is rewritten.

Source review also finds a distinct cleanup gap: binding-verification errors
use the common retirement/cleanup path, but later observer health/socket errors
return directly, leaving the Launcher prepared until finite expiry while Server
publication closes. [The narrow fix plan](../../artifacts/server-prestart-cleanup-fix-plan01/PLAN.md)
requires an actual old-binary regression before implementation, on an isolated
scratch Server because the legacy fixture overwrites global configuration and
ownership. No target reproduction or fixed production binary exists yet.
Literal D2-05 negative-connect evidence, final cohort qualification, A13/A14,
genuine release signing and the failed A16 comparison remain open.

| Build/source receipt | SHA-256 |
|---|---|
| [One actual compile-only sequence](../../artifacts/a16-bind9-compile-root-review01/result.json) | `0928f8403c6c80429c778cfaa888f18f686b3d3d6474a221827023892d523c59` |
| [Actual native GCC14 build](../../artifacts/a16-bind9-compile01/result.json) | `4e893fabfae4dc1fdd6595d2238157390614607d598993163d7d899788aafb2a` |
| [Independent saved-build audit](../../artifacts/a16-bind9-compile-actual-peer01/review.json) | `9db4422a11001e19c6fde41996bcedc4baf95a6cac801d3bb43c67d78b99faaf` |
| [Unapproved build-only candidate](../../artifacts/a16-bind9-compile-root-review01/diagnostic9-build-candidate.json) | `5f0c1ef21b7fc5158e261afcb739f959a3bbfa314c668f536f959e0438deb390` |
| [Current 46-unit stopped custody](../../artifacts/a16-bind9-compile-final-stopped-custody01/result.json) | `6bf2fc300dd4ecdf704333a6dc838f89c63e17030d0173c36fc2ac9adb51b613` |
| [D2-01/02 source/runtime association](../../artifacts/server-final-d2-runtime-association04/association.json) | `db16b0671f4541393bce57df538f78d70b9bcfe3d815cdf9e0964afa028b89d3` |
