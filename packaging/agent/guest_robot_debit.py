#!/usr/bin/env python3
"""Opt-in retained Robot debit campaign; source preparation, no VM orchestration."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import select
import secrets
import stat
import subprocess
import sys
import threading
import time
import uuid

import guest_robot_acceptance as common
from debit_gate import ConnectionGate

require = common.require
NAMES = {'attempt', 'runtime_binding', 'runtime_facts', 'stdout', 'stderr', 'broker', 'robot'}


def read_continuation(fd, deadline):
    raw = bytearray()
    while True:
        left = deadline - time.monotonic()
        require(left > 0 and select.select([fd], [], [], left)[0]
                and time.monotonic() < deadline,
                'root continuation cutoff; no retry/reboot attempted')
        chunk = os.read(fd, 1025 - len(raw))
        require(chunk, 'root continuation EOF before complete frame')
        raw.extend(chunk)
        require(len(raw) <= 1024, 'bounded explicit continuation required')
        if b'\n' in raw:
            require(raw.count(b'\n') == 1 and raw.endswith(b'\n'),
                    'exactly one continuation line required')
            return bytes(raw)
        require(len(raw) < 1024, 'bounded explicit continuation required')


def peer_digest(peer):
    # robot::PeerConfig is a Rust struct, not a sorted serde_json::Value map.
    fields = ('endpoint', 'dns_name', 'robot_leaf_sha256', 'principal',
              'robot_configuration_digest', 'robot_profile_digest', 'ca_pem', 'client_certificate_pem')
    require(set(peer) == set(fields), 'peer configuration fields')
    return common.digest({key: peer[key] for key in fields}, sort=False)


def operation_identity(description, attempt, namespace):
    runtime = description['runtime']; kernel = runtime['kernel']
    prepared = runtime['prepared']
    if prepared is None or bytes(prepared['binding']['attempt']).hex() != attempt \
            or bytes(prepared['binding']['namespace']).hex() != namespace:
        return None
    operation = runtime['operation']
    if kernel['state'] != 2 or kernel['operation_state'] != 2 or not kernel['flags'] & 8 \
            or operation is None or operation['operation'] is None:
        return None
    identity = operation['operation']
    for source, target in [('device_identity', 'device'), ('controller_boot', 'boot'),
                           ('controller_session', 'session'), ('runtime_nonce', 'runtime_nonce'),
                           ('grant', 'grant'), ('instance', 'instance'),
                           ('operation', 'operation'), ('stream', 'stream')]:
        require(identity[target] == kernel[source], 'runtime/kernel full operation mismatch: ' + source)
    return identity


def settled_operation(snapshot, handle, operation):
    # Task success can remain unknown after a durable, reconciled completion.
    # Unknown execution, an absent operation, or incomplete durability cannot settle.
    return (isinstance(snapshot, dict) and operation is not None
            and snapshot.get('namespace') == list(bytes.fromhex(handle['namespace']))
            and snapshot.get('key') == list(bytes.fromhex(handle['key']))
            and snapshot.get('operation') == operation
            and snapshot.get('terminal') is True and snapshot.get('reconciled') is True
            and snapshot.get('persistence_failed') is False
            and type(snapshot.get('revision')) is int and snapshot['revision'] > 0
            and type(snapshot.get('durable_revision')) is int
            and snapshot['durable_revision'] == snapshot['revision']
            and snapshot.get('phase') in ('Completed', 'CancelledDurable')
            and (snapshot.get('verdict') in ('TargetReached', 'TimedOut', 'Cancelled')
                 or (snapshot['phase'] == 'Completed' and snapshot.get('verdict') == 'OutcomeUnknown')))


def verify_partial(bundle, attempt, binding, intent, logs, *, crashed=False, active=False, settled=False):
    require(not (active and (crashed or settled)), 'contradictory evidence state')
    names = common.verify_bundle(bundle, attempt)
    require(names <= NAMES and {'attempt', 'runtime_binding', 'broker', 'robot'} <= names,
            'missing core evidence artifact')
    omissions = bundle['omissions']
    allowed = {('runtime_facts', 'final_resource_snapshot_unavailable'),
               ('runtime_facts', 'log_incomplete'), ('stdout', 'retained_log_unavailable'),
               ('stderr', 'retained_log_unavailable')}
    require(len({(v['artifact'], v['reason']) for v in omissions}) == len(omissions)
            and all((v['artifact'], v['reason']) in allowed and type(v['omitted_records']) is int
                    and v['omitted_records'] == 1 and (v['reason'] == 'log_incomplete'
                    or v['artifact'] not in names) for v in omissions), 'unexpected or malformed omission')
    content = {v['name']: v['content'] for v in bundle['artifacts']}
    record = content['attempt']
    require(record['id'] == attempt and record['state'] == ('running' if active else 'reaped')
            and record['outcome'] == ('pending' if active else 'unknown' if crashed else 'cancelled')
            and record['artifact_digest'] == intent['artifact_digest'], 'partial attempt attribution')
    remote = content['robot']
    require(remote['classification'] == 'trusted_peer_delegation_metadata'
            and remote['binding'] == binding and type(remote['outstanding_debits']) is int
            and remote['outstanding_debits'] == (0 if settled else 1)
            and remote['requests_retained'] == len(remote['requests']) == 1, 'remote debit not retained')
    request = remote['requests'][0]
    for field in ('request_key', 'handle', 'robot_epoch', 'observation_digest', 'proposal_digest'):
        require(request[field] == intent[field], 'immutable remote identity changed: ' + field)
    require(request['outstanding_debit'] is (not settled)
            and request['cancellation_requested'] is (not active)
            and request['phase'] == ('settled' if settled else 'accepted' if active else 'unknown'),
            'remote closure falsely settled')
    if settled:
        proof = intent.get('settlement')
        require(settled_operation(proof, intent['handle'], intent.get('operation'))
                and request['reconciled'] is True and request['remote_verdict'] == proof['verdict'],
                'settlement lacks matching durable completion/reconciliation')
    broker = content['broker']
    require(broker['attempt_state'] == record['state'] and broker['attempt_outcome'] == record['outcome']
            and len(broker['calls']) == 1 and broker['calls'][0]['request_key'] == 'preview-1'
            and broker['calls'][0]['state'] == 'settled' and broker['calls'][0]['consumed_tokens'] == 0
            and broker['calls'][0]['publication_closed'] is (not active)
            and broker['policy_denials'] == [] and broker['policy_denials_retained'] == 0,
            'offline settlement/publication differs from Robot debit')
    require(content['runtime_binding'] == intent['runtime_binding'], 'sandbox binding changed')
    # Launcher omissions own log completeness; broker startup can reap before
    # tick mirrors that separate store's gap. Do not require duplicate evidence.
    allowed_gaps = ([], ['log_incomplete']) if crashed else ([],)
    require(broker['evidence_gaps'] in allowed_gaps, 'unexpected broker evidence gap')
    if crashed:
        require(any(v['artifact'] == 'runtime_facts' and v['reason'] == 'log_incomplete'
                    for v in omissions), 'crash log uncertainty hidden')
    elif not active:
        require(names == NAMES and omissions == [], 'clean local retirement evidence incomplete')
    if 'runtime_facts' in names:
        facts = content['runtime_facts']; resources = facts['resources']; health = facts['observer']
        require(not active and not crashed and facts['observer_health_unavailable'] is False
                and health['ready'] is True and health['lost'] == 0
                and health['collector_epoch'] == content['runtime_binding']['observer']['collector_epoch']
                and set(common.REQUIRED_COVERAGE) <= set(health['coverage'])
                and resources['classification'] == 'observed_cgroup_v2_counters'
                and resources['stage'] == 'after_descendants_empty_before_runtime_delete'
                and set(resources['counters']) == set(common.RESOURCE_COUNTERS)
                and resources['counters']['pids.current'].strip() == '0'
                and resources['unavailable'] == [], 'local cleanup facts incomplete')
    else:
        require((active or crashed) and any(v['artifact'] == 'runtime_facts'
                and v['reason'] == 'final_resource_snapshot_unavailable' for v in omissions),
                'missing final resources not declared')
    for name in ('stdout', 'stderr'):
        raw = logs[name + '.log']
        if name not in names:
            require(crashed and raw is None and any(v['artifact'] == name
                    and v['reason'] == 'retained_log_unavailable' for v in omissions), 'missing raw log')
            continue
        require(raw is not None, 'raw log read unavailable')
        data = raw.encode(); log = content[name]
        require(log['classification'] == 'untrusted_agent_output_not_policy_attribution'
                and log['file_complete'] is (not active and not crashed)
                and log['source_truncated'] is False and log['retained_bytes'] == len(data)
                and log['retained_sha256'] == 'sha256:' + hashlib.sha256(data).hexdigest()
                and log['tail_encoding'] == 'hex' and log['tail'] == data[-2048:].hex()
                and log['tail_omitted_bytes'] == max(0, len(data) - 2048), 'raw partial log mismatch')
    return content


class DebitCampaign(common.Campaign):
    def __init__(self, args, gate):
        super().__init__(args)
        self.gate, self.cases = gate, []
        self.phase_deadline = time.monotonic() + 180

    def mark(self, name, seconds=180):
        require(0 < seconds <= 300, 'phase wall bound')
        self.phase_deadline = time.monotonic() + seconds
        super().mark(name)

    def run(self, argv, timeout=25):
        if getattr(self, 'aborting', False):
            return super().run(argv, min(timeout, 5))
        require(self.gate.report()['error'] is None, self.gate.report())
        left = min(timeout, self.phase_deadline - time.monotonic(),
                   self.gate.deadline - time.monotonic())
        require(left > 0, 'phase/gate wall cutoff; outcome remains unknown')
        return super().run(argv, left)

    def ssh(self, port, program, timeout=25):
        import shlex
        key = self.args.server_ssh_key if port == self.args.server_port else self.args.robot_ssh_key
        require(port in (self.args.server_port, self.args.robot_port), 'unexpected guest route')
        return self.run(['ssh', '-i', str(key), '-p', str(port), '-o', 'IdentitiesOnly=yes',
                         '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
                         '-o', 'StrictHostKeyChecking=yes',
                         '-o', 'UserKnownHostsFile=' + str(self.args.known_hosts),
                         'root@127.0.0.1', 'python3 -c ' + shlex.quote(program)], timeout)

    def direct(self):
        from actryn import Client
        return Client('127.0.0.1', port=self.args.tcp_port, server_name=self.peer['dns_name'],
                      ca=str(self.args.ca), certificate=str(self.args.certificate),
                      key=str(self.args.client_key), paired_fingerprint=self.peer['robot_leaf_sha256'], timeout=1)

    def pre_send_ready(self, description, case):
        from actryn import RequestHandle
        sys.path.insert(0, str(common.ROOT / 'apps/robotd/tests'))
        from failure_paths import pre_send_ready
        pre_send_ready(description, RequestHandle(bytes.fromhex(case['attempt']),
                       bytes.fromhex(case['namespace']), bytes(32)))

    def pin_platforms(self):
        server = f'''import hashlib,json,pathlib,subprocess,os
root=pathlib.Path('/opt/actryn/server/current').resolve()
raw=(root.parent/'manifest.json').read_bytes();assert len(raw)<=262144
assert root.parent.name=={self.args.server_manifest!r} and hashlib.sha256(raw).hexdigest()=={self.args.server_manifest!r}
manifest=json.loads(raw);assert manifest['role']=='server';entries={{x['path']:x for x in manifest['files']}}
pins={{}}
for unit in ['actryn-serverd','actryn-launcher','actryn-observer']:
 pid=int(subprocess.check_output(['systemctl','show','--value','-p','MainPID',unit]));assert pid>1
 path=pathlib.Path('/proc',str(pid),'exe');assert path.resolve()==root/'bin'/unit
 digest=hashlib.sha256(path.read_bytes()).hexdigest();assert digest==entries['bin/'+unit]['sha256'];pins[unit]=digest
assert json.loads(pathlib.Path('/etc/actryn/robot-peer.json').read_bytes())=={self.peer!r}
machine=pathlib.Path('/etc/machine-id').read_text().strip();assert machine=={self.args.server_machine_id!r}
print(json.dumps({{'machine':machine,'pins':pins,'manifest':root.parent.name}}))'''
        server_pins = json.loads(self.ssh(self.args.server_port, server))
        robot = f'''import hashlib,json,pathlib,subprocess
pid=int(subprocess.check_output(['systemctl','show','--value','-p','MainPID','actryn-robotd']));assert pid>1
manager=hashlib.sha256(pathlib.Path('/proc',str(pid),'exe').read_bytes()).hexdigest();assert manager=={self.args.robot_manager_sha256!r}
note=hashlib.sha256(pathlib.Path('/sys/module/actryn_authority/notes/.note.gnu.build-id').read_bytes()).hexdigest();assert note=={self.args.robot_module_note_sha256!r}
machine=pathlib.Path('/etc/machine-id').read_text().strip();assert machine=={self.args.robot_machine_id!r}
print(json.dumps({{'machine':machine,'manager':manager,'module_note':note}}))'''
        robot_pins = json.loads(self.ssh(self.args.robot_port, robot))
        self.server_machine = server_pins['machine']
        self.save('installed-pins-' + str(len(self.cases)) + '.json', {'server': server_pins, 'robot': robot_pins})

    def inventory(self):
        program = '''import contextlib,json,sqlite3
with contextlib.closing(sqlite3.connect('file:/var/lib/actryn-server/broker/state.sqlite?mode=ro',uri=True,timeout=1)) as db:
 rows=db.execute('SELECT attempt_id,request_key,data FROM robot_requests WHERE outstanding=1 ORDER BY rowid').fetchall()
 assert len(rows)<=4
 print(json.dumps([dict(attempt=a,key=k,intent=json.loads(d)) for a,k,d in rows]))'''
        return json.loads(self.ssh(self.args.server_port, program))

    def catalog(self):
        program = '''import contextlib,json,sqlite3,subprocess
result={}
for name,path in [('launcher','/var/lib/actryn-server/launcher.sqlite'),('broker','/var/lib/actryn-server/broker/state.sqlite')]:
 with contextlib.closing(sqlite3.connect('file:'+path+'?mode=ro',uri=True,timeout=1)) as db:
  result[name]=[row[0] for row in db.execute('SELECT id FROM attempts ORDER BY id')]
  result[name+'_unreaped']=[row[0] for row in db.execute("SELECT id FROM attempts WHERE state!='reaped' ORDER BY id")]
result['tasks']=subprocess.check_output(['ctr','--namespace','actryn','tasks','list','--quiet'],timeout=10).decode().splitlines()
print(json.dumps(result))'''
        return json.loads(self.ssh(self.args.server_port, program))

    def snapshot(self, attempt):
        require(re.fullmatch('[0-9a-f]{32}', attempt), 'snapshot identity')
        program = f'''import contextlib,json,sqlite3,pathlib
attempt={attempt!r};result={{}}
for name,path in [('launcher','/var/lib/actryn-server/launcher.sqlite'),('broker','/var/lib/actryn-server/broker/state.sqlite')]:
 with contextlib.closing(sqlite3.connect('file:'+path+'?mode=ro',uri=True,timeout=1)) as db:
  row=db.execute('SELECT state,outcome,binding,artifact_digest FROM attempts WHERE id=?',(attempt,)).fetchone();assert row
  calls=db.execute('SELECT request_key,state,publication_closed,output IS NULL FROM calls WHERE attempt_id=?',(attempt,)).fetchall()
  remote=db.execute('SELECT data FROM robot_requests WHERE attempt_id=?',(attempt,)).fetchall();assert len(remote)<=1
  result[name]={{'state':row[0],'outcome':row[1],'binding':json.loads(row[2]),'artifact':row[3],'calls':calls,'remote':[json.loads(x[0]) for x in remote]}}
result['cgroup_exists']=pathlib.Path('/sys/fs/cgroup/actryn',attempt).exists()
print(json.dumps(result))'''
        return json.loads(self.ssh(self.args.server_port, program))

    def raw_logs(self, attempt):
        program = f'''import json,pathlib
p=pathlib.Path('/var/lib/actryn-server')/{attempt!r};result={{}}
for name in ['stdout.log','stderr.log']:
 try:
  raw=(p/name).read_bytes();assert len(raw)<=8192;result[name]=raw.decode()
 except FileNotFoundError:result[name]=None
print(json.dumps(result))'''
        return json.loads(self.ssh(self.args.server_port, program))

    def setup(self, label):
        from actryn import robot_v1_pb2 as wire
        require(not self.gate.report()['future_connections_blocked'], 'old closure connections not drained')
        attempt, namespace = self.prepare(label), secrets.token_hex(16)
        binding = self.server_mutation(label + '-bind', 'bind-robot', '--attempt', attempt,
                                      '--namespace', namespace)['binding']
        require(binding['peer_digest'] == peer_digest(self.peer), 'stable gate peer digest changed')
        self.local_mutation(label + '-rearm', 'rearm')
        self.poll(lambda: self.local('describe'), lambda d: d['runtime']['kernel']['state'] == 1)
        self.local_mutation(label + '-robot-prepare', 'prepare', wire.Prepare(
            attempt=bytes.fromhex(attempt), namespace=bytes.fromhex(namespace), principal=self.peer['principal']))
        self.poll(lambda: self.local('describe'), lambda d: d['runtime']['preparation_ready'])
        self.local_mutation(label + '-grant', 'grant', wire.Grant(duration_ms=30_000))
        self.local_mutation(label + '-activate', 'activate')
        return {'label': label, 'attempt': attempt, 'namespace': namespace, 'binding': binding}

    def launch_real(self, label):
        case = self.setup(label)
        ready, stop = threading.Event(), threading.Event()
        observed = {'last': []}
        def watch():
            try:
                with self.direct() as client:
                    self.pre_send_ready(client.describe(), case)
                    ready.set()
                    until = time.monotonic() + 3
                    while not stop.is_set() and time.monotonic() < until:
                        description = client.describe()
                        observed['last'] = (observed['last'] + [description])[-16:]
                        identity = operation_identity(description, case['attempt'], case['namespace'])
                        if identity:
                            self.gate.arm(identity)
                            observed.update(identity=identity, description=description)
                            return
                        time.sleep(.01)
            except BaseException as error:
                observed['error'] = repr(error); ready.set()
        worker = threading.Thread(target=watch, daemon=True); worker.start()
        try:
            require(ready.wait(2) and 'error' not in observed, observed)
            self.server_mutation(label + '-launch', 'launch', '--attempt', case['attempt'])
            worker.join(4)
            require(not worker.is_alive() and 'identity' in observed, observed)
        finally:
            stop.set(); worker.join(2)
        case['watched'] = observed
        snap = self.poll(lambda: self.snapshot(case['attempt']), lambda v:
                         v['broker']['remote'] and v['broker']['remote'][0]['phase'] == 'accepted')
        intent = snap['broker']['remote'][0]
        require(intent['outstanding_debit'] is True and not intent['cancellation_requested']
                and intent['proposal_digest'] and intent['observation']
                and bytes(observed['description']['runtime']['operation']['key']).hex() == intent['handle']['key'],
                'accepted actual Robot reservation missing')
        case.update(intent=intent, runtime_binding=snap['launcher']['binding'])
        with self.direct() as client:
            from actryn import RequestHandle
            query = client.query(RequestHandle.from_json(intent['handle']))
        require(query['snapshot']['operation'] == observed['identity'], 'direct Robot full identity mismatch')
        logs = self.poll(lambda: self.raw_logs(case['attempt']), lambda v: bool(v['stdout.log']))
        require(not logs['stderr.log'] and len(logs['stdout.log'].splitlines()) == 1, logs)
        value = json.loads(logs['stdout.log'])['value']
        common.verify_lineage(value, intent, case['attempt'], case['namespace'])
        require(value['output'] == {'left_delta_ticks': 10, 'right_delta_ticks': 10, 'duration_ms': 1000},
                'fixed proposal changed')
        case['original_logs'] = logs
        self.cases.append(case); self.save(label + '-actual-reservation.json', case)
        return case

    def partial(self, case, label, *, crashed=False, active=False, settled=False):
        intent = copy.deepcopy(case['intent'])
        intent.update(artifact_digest=self.args.artifact, runtime_binding=case['runtime_binding'],
                      operation=case['watched']['identity'], settlement=case.get('settlement'))
        logs = self.raw_logs(case['attempt'])
        if not active:
            for name, old in case['original_logs'].items():
                require((crashed and logs[name] is None) or (old.startswith(logs[name]) if crashed
                        else logs[name] == old), 'new agent output after closure/restart')
        bundle = self.export_server(label, case['attempt'])
        verify_partial(bundle, case['attempt'], case['binding'], intent, logs,
                       crashed=crashed, active=active, settled=settled)

    def cancel_retained(self, case):
        label, attempt = case['label'], case['attempt']
        try:
            self.mutation(label + '-cancel', {'attempt': attempt}, lambda:
                          self.server('cancel', '--attempt', attempt, allow_unknown=True))
        except (subprocess.SubprocessError, RuntimeError, ValueError) as error:
            self.save(label + '-cancel-unknown.json', {'error': repr(error), 'automatic_retry': False})
        snap = self.poll(lambda: self.snapshot(attempt), lambda v: all(
            v[name]['state'] == 'reaped' for name in ('broker', 'launcher')) and not v['cgroup_exists'])
        require(snap['broker']['calls'] == [['preview-1', 'settled', 1, 1]]
                and snap['broker']['remote'][0]['outstanding_debit'] is True
                and snap['broker']['remote'][0]['cancellation_requested'] is True, snap)
        require(self.server('result', '--attempt', attempt, '--key', 'preview-1')['value'] is None,
                'closed result republished')
        self.save(label + '-local-reaped-remote-outstanding.json', snap)
        self.partial(case, label + '-unresolved')

    def drain_and_retire(self, case):
        from actryn import RequestHandle
        with self.direct() as client:
            result = self.poll(lambda: client.query(RequestHandle.from_json(case['intent']['handle'])),
                               lambda v: settled_operation(v['snapshot'], case['intent']['handle'],
                                                           case['watched']['identity']), 12)
        require(result['snapshot']['operation'] == case['watched']['identity'], 'retired identity changed')
        label = case['label']
        self.local_mutation(label + '-retire', 'retire', closure=True)
        self.poll(lambda: self.local('describe'), lambda d: d['runtime']['retirement_ready'], 15)
        self.local_mutation(label + '-recover', 'recover')
        self.poll(lambda: self.local('describe'), lambda d: d['runtime']['recovery_ready']
                  and d['runtime']['prepared'] is None, 15)
        self.poll(self.gate.report, lambda d: d['blocked_active'] == 0, 10)
        self.gate.pass_future()

    def handoff(self):
        self.mark('manual server guest crash handoff', 300)
        inventory = self.inventory()
        require(len(inventory) == 2 and {v['attempt'] for v in inventory} ==
                {case['attempt'] for case in self.cases}, 'exact two precrash Robot debits')
        handoff = {'phase': 'BEFORE_SERVER_QEMU_CRASH', 'server_boot_id': self.server_boot,
                   'attempts': self.cases, 'robot_debits': inventory,
                   'peer_config_digest': peer_digest(self.peer), 'gate': self.gate.report(),
                   'catalog': self.catalog(), 'handoff_at_monotonic_ns': time.monotonic_ns(),
                   'crash_by_monotonic_ns': time.monotonic_ns() + 20_000_000_000,
                   'no_vm_command_executed': True, 'continue_cutoff_monotonic': self.phase_deadline,
                   'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        self.save('immutable-handoff.json', handoff)
        print(json.dumps({'phase': 'WAITING_FOR_ROOT_CRASH_REBOOT_EXPLICIT_UNIT_START',
                          'handoff': str(self.output / 'immutable-handoff.json'),
                          'cutoff_monotonic': self.phase_deadline}), flush=True)
        raw = read_continuation(sys.stdin.fileno(), min(self.phase_deadline, self.gate.deadline))
        continuation = json.loads(raw)
        require(set(continuation) == {'continue', 'new_server_boot_id', 'crash_record'}
                and continuation['continue'] == 'AFTER_REVIEWED_SERVER_REBOOT', 'unknown continuation')
        record_path = Path(continuation['crash_record'])
        with os.fdopen(os.open(record_path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW), 'rb') as stream:
            metadata = os.fstat(stream.fileno())
            require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.geteuid()
                    and metadata.st_nlink == 1 and not metadata.st_mode & 0o022,
                    'owned nonwritable coordinator record required')
            record_bytes = stream.read(65537)
        require(len(record_bytes) <= 65536, 'bounded retained root crash record required')
        crash_record = json.loads(record_bytes)
        require(crash_record['action'] == 'SIGKILL_QEMU'
                and crash_record['unit'] == self.args.server_qemu_unit
                and type(crash_record['pid']) is int and crash_record['pid'] > 1
                and crash_record['old_server_boot_id'] == self.server_boot
                and handoff['handoff_at_monotonic_ns'] <= crash_record['at_monotonic_ns']
                <= handoff['crash_by_monotonic_ns'] and crash_record['verified_signal_exit'] is True,
                'crash action/timing not independently retained')
        self.save('root-crash-record.json', {'record': crash_record,
                  'sha256': hashlib.sha256(record_bytes).hexdigest()})
        boot = str(uuid.UUID(continuation['new_server_boot_id']))
        require(boot != self.server_boot, 'server guest did not reboot')
        self.mark('after server boot read-only recovery inspection', 180)
        identity = json.loads(self.ssh(self.args.server_port,
            "import json,pathlib;print(json.dumps({'boot':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'machine':pathlib.Path('/etc/machine-id').read_text().strip()}))"))
        require(identity['boot'] == boot and identity['machine'] == self.server_machine, 'wrong rebooted guest')
        self.pin_platforms()
        for case in self.cases:
            snap = self.poll(lambda: self.snapshot(case['attempt']), lambda v: all(
                v[name]['state'] == 'reaped' for name in ('broker', 'launcher')) and not v['cgroup_exists'])
            require(snap['broker']['calls'] == [['preview-1', 'settled', 1, 1]]
                    and snap['broker']['remote'][0]['outstanding_debit'] is True, snap)
            self.partial(case, case['label'] + '-after-boot', crashed=case['label'] == 'crash')
        inventory = self.inventory()
        require(len(inventory) == 2 and {v['attempt'] for v in inventory} ==
                {case['attempt'] for case in self.cases}, 'restart changed remote reservation set')
        catalog = self.catalog()
        require(catalog['tasks'] == [] and all(catalog[name] == handoff['catalog'][name]
                for name in ('broker', 'launcher')), 'automatic agent execution/allocation after boot')
        self.save('after-boot-inventory.json', {'inventory': inventory, 'catalog': catalog})

    def execute(self):
        self.mark('preflight and exact installed pins')
        require(self.peer['endpoint'] == '10.0.2.2:' + str(self.gate.port), 'stable gate endpoint required')
        self.pin_platforms()
        catalog = self.catalog()
        require(not catalog['tasks'] and not catalog['broker_unreaped']
                and not catalog['launcher_unreaped'] and not self.inventory(),
                'preexisting sandbox work or outstanding Robot debit')
        self.preflight()
        self.mark('actual cancel with retained downstream debit')
        first = self.launch_real('cancel'); self.cancel_retained(first); self.drain_and_retire(first)
        self.mark('actual running attempt and downstream debit before guest crash')
        second = self.launch_real('crash'); self.partial(second, 'crash-before-boot', active=True)
        self.handoff()
        self.drain_and_retire(second)
        if self.args.pressure:
            for label in ('pressure-c', 'pressure-d'):
                self.mark(label)
                case = self.launch_real(label); self.cancel_retained(case); self.drain_and_retire(case)
            pending = self.inventory()
            require(len(pending) == 4 and {row['attempt'] for row in pending} ==
                    {case['attempt'] for case in self.cases}, 'exact four retained Robot debits')
            self.save('four-retained-debits.json', pending)
            self.mark('fifth attempt Robot reservation refusal')
            fifth = self.setup('fifth')
            before = self.local('describe')['runtime']
            self.pre_send_ready(self.local('describe'), fifth)
            self.server_mutation('fifth-launch', 'launch', '--attempt', fifth['attempt'])
            logs = self.poll(lambda: self.raw_logs(fifth['attempt']), lambda v: bool(v['stderr.log']))
            self.save('fifth-refusal-raw-logs.json', logs)
            require(not logs['stdout.log'] and 'robot retained-key/outstanding capacity exhausted'
                    in logs['stderr.log'], 'fifth rejected for wrong cause')
            snap = self.snapshot(fifth['attempt'])
            require(snap['broker']['remote'] == [] and snap['broker']['calls'] ==
                    [['preview-1', 'cancelled', 1, 1]] and self.inventory() == pending,
                    'fifth admitted Robot work or erased a debit')
            after = self.local('describe')['runtime']
            require(after['operation'] is None and after['kernel']['operation_state'] == 0
                    and after['kernel']['operation'] == before['kernel']['operation']
                    and after['kernel']['left_permille'] == after['kernel']['right_permille'] == 0,
                    'fifth refusal created a Robot operation or output')
            self.server_mutation('fifth-cancel', 'cancel', '--attempt', fifth['attempt'])
            self.local_mutation('fifth-retire', 'retire', closure=True)
            self.poll(lambda: self.local('describe'), lambda d: d['runtime']['retirement_ready'], 15)
            self.local_mutation('fifth-recover', 'recover')
            self.poll(lambda: self.local('describe'), lambda d: d['runtime']['recovery_ready'], 15)
            self.save('fifth-refusal.json', {'logs': logs, 'snapshot': snap,
                'agent_task_and_ordinary_broker_reservation_were_admitted': True,
                'robot_observation_or_proposal_were_not_admitted': True})
        self.mark('matching read-only remote settlement', 300)
        for case in self.cases:
            result = self.poll(lambda: self.server('robot-query', '--attempt', case['attempt'],
                              '--key', 'preview-1')['request'], lambda v: not v['outstanding_debit'], 15)
            require(result['phase'] == 'settled' and settled_operation(result['last_remote'],
                    case['intent']['handle'], case['watched']['identity']),
                    'debit cleared without matching downstream reconciliation')
            case['settlement'] = result['last_remote']
            self.save(case['label'] + '-settled.json', result)
            self.partial(case, case['label'] + '-settled-export',
                         crashed=case['label'] == 'crash', settled=True)
        require(not self.inventory(), 'unresolved debits remain')
        if self.args.pressure:
            self.mark('new admission after exact Robot settlement')
            case = self.launch_real('restored-capacity')
            self.cancel_retained(case); self.drain_and_retire(case)
            result = self.poll(lambda: self.server('robot-query', '--attempt', case['attempt'],
                              '--key', 'preview-1')['request'], lambda v: not v['outstanding_debit'], 15)
            require(result['phase'] == 'settled' and settled_operation(result['last_remote'],
                    case['intent']['handle'], case['watched']['identity']),
                    'restored capacity did not retain exact reconciled identity')
            case['settlement'] = result['last_remote']
            self.save('restored-capacity-settled.json', result)
            require(not self.inventory(), 'new reservation did not settle')
            self.partial(case, 'restored-capacity-settled-export', settled=True)
        require(not self.catalog()['tasks'] and all(self.snapshot(attempt)[name]['state'] == 'reaped'
                for attempt in self.attempts for name in ('broker', 'launcher')), 'final local cleanup incomplete')
        return {'scope': 'real Robot debit cancellation/server guest crash'
                  + ('/global-four pressure' if self.args.pressure else ''),
                  'attempts': self.attempts,
                  'provider_pressure_tested': False, 'closure_inventory_exhausted': False,
                  'physical_acceptance': False, 'automatic_proposal_retries': 0,
                  'peer_restoration_tested': False,
                  'next_operator_action': 'stop server units; restore separately retained original peer/credential configuration'}

    def complete(self):
        result = self.execute()
        self.gate.close()  # Reap all workers inside the recorded failure boundary, before PASS.
        final = self.gate.report()
        require(final['error'] is None and final['active'] == final['blocked_active'] == 0
                and final['remaining_s'] > 0 and 0 <= final['connections'] <= 64
                and 0 <= final['bytes_observed'] <= 8 * 1024 * 1024
                and 0 <= final['bytes_forwarded'] + final['blocked_bytes'] <= final['bytes_observed']
                and final['bytes_forwarded'] >= 0 and final['blocked_bytes'] >= 0,
                {'gate_finalization_failed': final})
        self.save('PASS.json', dict(result, gate=final))

    def abort_revoke(self):
        # One distinct, planned urgent closure; no retire/recovery or mutation resend.
        if not hasattr(self, 'server_machine') or not self.epoch:
            return
        self.aborting = True
        try:
            actual = self.ssh(self.args.robot_port,
                "import pathlib;print(pathlib.Path('/etc/machine-id').read_text().strip())").decode().strip()
            require(actual == self.args.robot_machine_id, 'abort route no longer matches reviewed Robot')
            self.local_mutation('abort-revoke', 'revoke', closure=True)
        except BaseException as error:
            self.save('abort-closure-unknown.json', {'error': repr(error), 'automatic_retry': False})


def source_limits():
    source = (common.ROOT / 'apps/server/src/robot.rs').read_text()
    expected = {'PER_ATTEMPT_JOBS': 1, 'GLOBAL_JOBS': 4, 'KEYS_PER_ATTEMPT': 16, 'CLOSURE_CAPACITY': 16}
    for key, number in expected.items():
        require(re.search(r'pub const ' + key + r': usize = ' + str(number) + ';', source),
                'reviewed Robot source limit changed: ' + key)
    store = (common.ROOT / 'apps/server/src/store.rs').read_text()
    require(re.search(r'prepared: 1,\s+active: 1,', store), 'sandbox source limits changed')
    remote_store = (common.ROOT / 'apps/server/src/store/robot.rs').read_text()
    require('WHERE outstanding=1' in remote_store and all(
            comparison in remote_store for comparison in (
                'count < robot::KEYS_PER_ATTEMPT as i64',
                'local < robot::PER_ATTEMPT_JOBS as i64',
                'global < robot::GLOBAL_JOBS as i64')), 'Robot durable capacity checks changed')
    return expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-disposable-guests', action='store_true', required=True)
    for name in ('server-ssh-key', 'robot-ssh-key', 'known-hosts', 'peer-config', 'ca',
                 'certificate', 'client-key', 'cli', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    for name in ('server-port', 'robot-port', 'tcp-port', 'gate-port'):
        parser.add_argument('--' + name, required=True, type=int)
    for name in ('server-manifest', 'robot-manager-sha256', 'robot-module-note-sha256',
                 'server-machine-id', 'robot-machine-id', 'server-qemu-unit', 'artifact'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--guest-cli', default='/usr/bin/actryn')
    parser.add_argument('--pressure', action='store_true')
    args = parser.parse_args()
    require(all(0 < getattr(args, name) <= 65535 for name in
                ('server_port', 'robot_port', 'tcp_port', 'gate_port'))
            and args.server_port != args.robot_port, 'explicit separate guest endpoints')
    require(args.artifact == 'sha256:c3013959f5cca4a2275fa5f26de6f030dcc011241dbbe5961993a406e2e53d45',
            'fixed original credential-free agent required')
    require(all(re.fullmatch('[0-9a-f]{64}', getattr(args, name)) for name in
                ('server_manifest', 'robot_manager_sha256', 'robot_module_note_sha256'))
            and all(re.fullmatch('[0-9a-f]{32}', getattr(args, name)) for name in
                    ('server_machine_id', 'robot_machine_id')), 'immutable target pins')
    require(re.fullmatch(r'actryn-install-server[0-9]*\.service', args.server_qemu_unit),
            'explicit disposable server unit required')
    args.ssh_key = args.server_ssh_key  # Base records arguments; overridden ssh selects each exact key.
    sys.path.insert(0, str(common.ROOT / 'sdk/python'))
    source_limits()
    os.umask(0o077)
    gate = ConnectionGate(args.gate_port, args.tcp_port)
    try:
        campaign = DebitCampaign(args, gate)
    except BaseException:
        gate.close()
        raise
    try:
        gate.__enter__()
        campaign.complete()
    except BaseException as error:
        cleanup_error = None
        try: gate.close()
        except BaseException as failed_cleanup: cleanup_error = repr(failed_cleanup)
        campaign.save('FAILED.json', {'error': repr(error), 'phase': campaign.phase,
                      'attempts': campaign.attempts, 'cases': campaign.cases,
                      'gate': gate.report(), 'gate_cleanup_error': cleanup_error,
                      'automatic_retry': False,
                      'cleanup_or_remote_settlement_unconfirmed': True,
                      'next_action': 'retain peer endpoint/keys/disk; inspect exact handles before explicit closure'})
        campaign.abort_revoke()
        raise


if __name__ == '__main__':
    main()
