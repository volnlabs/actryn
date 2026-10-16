#!/usr/bin/env python3
"""Opt-in installed, non-actuating two-guest offline integration; never enroll or retry mutations."""
import argparse
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import struct
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
PEER = '/etc/actryn/robot-peer.json'
OBSERVATION_FIELDS = ('id', 'acquired_earliest_ns', 'acquired_latest_ns', 'valid_until_ns',
                      'controller_ns', 'left_ticks', 'right_ticks', 'simulated',
                      'context_revision', 'received_ms')
REQUIRED_COVERAGE = ('process.lifecycle', 'syscall.openat', 'syscall.connect', 'syscall.bpf',
                     'syscall.perf_event_open', 'syscall.mount', 'syscall.unshare', 'syscall.setns')
RESOURCE_COUNTERS = ('memory.current', 'memory.peak', 'memory.events', 'cpu.stat', 'io.stat',
                     'pids.current', 'pids.peak', 'pids.events')


def compact(value, sort=True):
    return json.dumps(value, sort_keys=sort, separators=(',', ':'), ensure_ascii=False).encode()


def digest(value, sort=True):
    return 'sha256:' + hashlib.sha256(compact(value, sort)).hexdigest()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def verify_lineage(value, intent, attempt, namespace):
    require(value['origin'] == 'server_attested' and value['attempt_id'] == attempt, 'attestation identity')
    require(value['request_key'] == intent['request_key'] == 'preview-1', 'agent request key')
    require(value['model'] == 'offline-fixture', 'unexpected provider')
    require(value['output'] == {'left_delta_ticks': 10, 'right_delta_ticks': 10, 'duration_ms': 1000}, 'fixed target')
    handle = intent['handle']
    require(handle == value['robot_handle'] and handle['attempt'] == attempt
            and handle['namespace'] == namespace and re.fullmatch('[0-9a-f]{64}', handle['key']), 'remote handle')
    observation = intent['observation']
    require(observation == value['trusted_robot_observation'] and observation['simulated'] is True
            and observation['id'] > 0 and observation['context_revision'] > 0, 'trusted observation')
    require(observation['acquired_earliest_ns'] <= observation['acquired_latest_ns']
            < observation['valid_until_ns']
            <= observation['acquired_earliest_ns'] + 1_000_000_000, 'original freshness bound')
    # Rust serializes this struct in declaration order; lineage Value objects use sorted keys.
    observation_hash = digest({k: observation[k] for k in OBSERVATION_FIELDS}, sort=False)
    require(observation_hash == intent['observation_digest'] == value['observation_digest'], 'observation digest')
    parent = digest({'handle': handle, 'request_digest': intent['request_digest'],
                     'robot_epoch': intent['robot_epoch'], 'observation': observation})
    require(parent == intent['parent_digest'] == value['lineage_digest'], 'parent lineage')
    require(intent['request_digest'] == value['request_digest'], 'input request digest')
    require(value['agent_observation_reference'] == 'offline-preview-reference', 'diagnostic agent input')


def verify_kernel_completion(kernel, operation):
    for source, target in [('device_identity', 'device'), ('controller_boot', 'boot'),
                           ('controller_session', 'session'), ('runtime_nonce', 'runtime_nonce'),
                           ('grant', 'grant'), ('instance', 'instance'), ('operation', 'operation'), ('stream', 'stream')]:
        require(kernel[source] == operation[target], 'actual kernel identity: ' + source)
    # Natural completion keeps the grant reusable; bit 8 is grant authorization.
    require(kernel['operation_state'] == 4 and kernel['left_permille'] == kernel['right_permille'] == 0,
            'kernel operation is not reconciled at zero output')


def verify_bundle(bundle, attempt):
    require(bundle.get('schema') == 'actryn.server.evidence.v1' and bundle['attempt_id'] == attempt
            and bundle['execution_replay_eligible'] is False, 'bundle identity')
    require(len(compact(bundle)) <= 60 * 1024, 'bundle bound')
    names = set()
    for artifact in bundle['artifacts']:
        require(artifact['name'] not in names, 'duplicate artifact')
        names.add(artifact['name'])
        require(artifact['bytes'] == len(compact(artifact['content']))
                and artifact['sha256'] == digest(artifact['content']), 'artifact hash/length')
    return names


def verify_final_bundle(bundle, attempt, binding, completed, logs, boot, artifact_digest):
    required = {'attempt', 'runtime_binding', 'runtime_facts', 'stdout', 'stderr', 'broker', 'robot'}
    require(verify_bundle(bundle, attempt) == required and bundle['omissions'] == [], 'final artifacts incomplete')
    artifacts = {value['name']: value['content'] for value in bundle['artifacts']}
    recorded = artifacts['attempt']
    require(recorded['id'] == attempt and recorded['state'] == 'reaped'
            and recorded['artifact_digest'] == artifact_digest, 'final attempt attribution')
    runtime = artifacts['runtime_binding']
    require(runtime['boot_id'] == boot and runtime['cgroup_id'] > 0 and runtime['ambiguous_create'] is False
            and runtime['snapshot']['cgroup'] == '/actryn/' + attempt
            and runtime['snapshot']['pid'] > 0 and runtime['snapshot']['start_ticks'] > 0,
            'runtime lifetime binding')
    facts = artifacts['runtime_facts']
    require(facts['observer_health_unavailable'] is False and facts['observer'] is not None, 'cleanup observer unavailable')
    first, final = runtime['observer'], facts['observer']
    for observer in (first, final):
        require(observer is not None and observer['ready'] is True and observer['lost'] == 0
                and isinstance(observer['collector_epoch'], str) and observer['collector_epoch']
                and set(REQUIRED_COVERAGE) <= set(observer['coverage']), 'observer evidence incomplete')
    require(final['collector_epoch'] == first['collector_epoch'] and final['sequence'] >= first['sequence'],
            'cleanup observer lifetime/frontier changed')
    resources = facts['resources']
    require(resources['classification'] == 'observed_cgroup_v2_counters'
            and resources['stage'] == 'after_descendants_empty_before_runtime_delete'
            and resources['captured_boottime_ms'] >= 0 and resources['unavailable'] == []
            and set(resources['counters']) == set(RESOURCE_COUNTERS)
            and all(isinstance(value, str) for value in resources['counters'].values()), 'resource evidence incomplete')
    require(resources['counters']['pids.current'].strip() == '0', 'cleanup retained descendants')
    broker = artifacts['broker']
    require(broker['attempt_state'] == 'reaped' and broker['evidence_gaps'] == []
            and broker['policy_denials'] == [] and broker['policy_denials_retained'] == 0
            and len(broker['calls']) == 1, 'final broker evidence/accounting incomplete')
    call = broker['calls'][0]
    require(call['request_key'] == completed['request_key'] and call['state'] == 'settled'
            and call['consumed_tokens'] == 0 and call['publication_closed'] is True, 'final call attribution')
    robot = artifacts['robot']
    require(robot['classification'] == 'trusted_peer_delegation_metadata' and robot['binding'] == binding
            and robot['requests_retained'] == len(robot['requests']) == 1 and robot['outstanding_debits'] == 0,
            'final Robot delegation attribution')
    request = robot['requests'][0]
    for field in ('request_key', 'handle', 'robot_epoch', 'observation_digest', 'proposal_digest'):
        require(request[field] == completed[field], 'final Robot request identity: ' + field)
    require(request['observation_id'] == completed['observation']['id'] and request['phase'] == 'settled'
            and request['outstanding_debit'] is False and request['remote_verdict'] == 'TargetReached'
            and request['reconciled'] is True, 'final Robot debit/reconciliation')
    for name in ('stdout', 'stderr'):
        log = artifacts[name]
        raw = logs[name + '.log'].encode()
        offset = max(0, len(raw) - 2048)
        require(log['classification'] == 'untrusted_agent_output_not_policy_attribution'
                and log['file_complete'] is True and log['source_truncated'] is False
                and log['retained_bytes'] == len(raw)
                and log['retained_sha256'] == 'sha256:' + hashlib.sha256(raw).hexdigest()
                and log['tail_encoding'] == 'hex' and log['tail_omitted_bytes'] == offset
                and log['tail'] == raw[offset:].hex(), 'final log bytes/completeness: ' + name)


def credential_metadata_safe(metadata, service_uid):
    """Metadata only; match systemd's bounded named-UID ACL or private owner route."""
    try:
        if not (type(service_uid) is int and 0 < service_uid < 2**32 and metadata['regular'] is True
                and metadata['nlink'] == 1 and 0 < metadata['size'] <= 8192):
            return False
        if metadata['uid'] in (0, service_uid) and metadata['mode'] & 0o077 == 0:
            return True
        if metadata['uid'] != 0 or metadata['gid'] != 0 or metadata['mode'] != 0o440:
            return False
        raw = bytes.fromhex(metadata['acl_hex'])
        return (len(raw) == 44 and struct.unpack_from('<I', raw)[0] == 2
                and [struct.unpack_from('<HHI', raw, offset) for offset in range(4, 44, 8)] ==
                [(1, 4, 2**32-1), (2, 4, service_uid), (4, 0, 2**32-1),
                 (16, 4, 2**32-1), (32, 0, 2**32-1)])
    except (KeyError, TypeError, ValueError, struct.error):
        return False


def cleanup_ready(snapshot, inspection):
    return (set(snapshot['stores']) == {'broker', 'launcher'}
            and inspection['attempt']['state'] == 'reaped' and not snapshot['cgroup_exists']
            and snapshot['observer_summary_ready']
            and all(value['state'] == 'reaped' and value['robot_outstanding'] == 0
                    for value in snapshot['stores'].values())
            and all(not value['outstanding_debit'] for value in inspection['robot_requests']))


def verify_cleanup(snapshot, inspection):
    require(cleanup_ready(snapshot, inspection), 'cleanup not converged')
    require(set(snapshot['stores']) == {'broker', 'launcher'} and inspection['evidence_gaps'] == []
            and all(value['gaps'] == [] and value['open_calls'] == value['pending_calls'] == 0
                    for value in snapshot['stores'].values()), 'cleanup accounting/evidence incomplete')
    facts, summary = snapshot['facts'], snapshot['summary']
    require(facts is not None and facts['resources']['unavailable'] == [], 'cleanup resource evidence unavailable')
    health = facts['observer']
    require(facts['observer_health_unavailable'] is False and health is not None
            and health['ready'] is True and health['lost'] == 0
            and health['collector_epoch'] == snapshot['observer_epoch'], 'cleanup observer evidence unavailable')
    status = summary['status']
    require(status['collector_epoch'] == snapshot['observer_epoch'] and status['ready'] is True
            and status['lost'] == 0 and summary['local_lost'] == 0
            and status['sequence'] >= health['sequence']
            and summary['retained_bytes'] == snapshot['log_bytes'] <= 16 * 1024 * 1024,
            'observer unregister durability not established')


def peer_update_program(path, token, original, fault, restore=False, uid=0, lock_timeout=8):
    """One serialized guest operation; a timed-out holder cannot be overtaken by readback."""
    require(re.fullmatch('[0-9a-f]{16}', token) and 0 < lock_timeout <= 8, 'peer maintenance parameters')
    return f'''import fcntl,json,os,pathlib,stat,time
p=pathlib.Path({str(path)!r});parent=p.parent.lstat()
assert stat.S_ISDIR(parent.st_mode) and parent.st_uid=={uid} and not parent.st_mode&0o022
lock=p.with_name('robot-peer.acceptance.lock')
fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_CLOEXEC,0o600)
m=os.fstat(fd);assert stat.S_ISREG(m.st_mode) and m.st_uid=={uid} and m.st_nlink==1 and not m.st_mode&0o077
until=time.monotonic()+{lock_timeout!r}
while True:
 try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);break
 except BlockingIOError:
  if time.monotonic()>=until:raise TimeoutError('peer maintenance lock unavailable; restoration unknown')
  time.sleep(.01)
m=p.lstat();assert stat.S_ISREG(m.st_mode) and m.st_uid=={uid} and m.st_nlink==1 and not m.st_mode&0o022 and m.st_size<=65536
current=json.loads(p.read_bytes());original={original!r};fault={fault!r}
restore={restore!r}
if restore:
 assert current in (original,fault),'peer changed concurrently; restoration unknown'
 replacement=original
else:
 assert current==original,'peer compare failed'
 replacement=fault
if current!=replacement:
 t=p.with_name('robot-peer.acceptance-{token}-'+('restore' if restore else 'fault')+'.tmp')
 with t.open('xb') as f:
  f.write(json.dumps(replacement,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode())
  os.fchown(f.fileno(),m.st_uid,m.st_gid);os.fchmod(f.fileno(),stat.S_IMODE(m.st_mode));f.flush();os.fsync(f.fileno())
 os.replace(t,p)
 directory=os.open(p.parent,os.O_DIRECTORY);os.fsync(directory);os.close(directory)
assert json.loads(p.read_bytes())==replacement
print(json.dumps({{'restoration_confirmed':restore,'public_peer_replaced':not restore}}))
'''


class Campaign:
    def __init__(self, args):
        self.args, self.epoch = args, b''
        self.phase, self.last_poll, self.attempts, self.mutations = 'preflight', None, [], set()
        self.output = args.output.resolve()
        self.output.mkdir(mode=0o700, parents=False, exist_ok=False)
        self.token = secrets.token_hex(8)
        self.remote_output = '/var/lib/actryn-test-campaigns/' + self.token
        self.peer = json.loads(args.peer_config.read_bytes())
        self.operator = None
        self.save('campaign.json', {'physical_acceptance': False, 'live_provider_calls': False,
                  'artifact_digest': args.artifact, 'peer_config_digest': digest(self.peer),
                  'principal': self.peer['principal'], 'server_port': args.server_port,
                  'robot_port': args.robot_port, 'token': self.token})

    def save(self, name, value):
        with (self.output / name).open('xb') as stream:
            stream.write(json.dumps(value, indent=2, ensure_ascii=False).encode() + b'\n')
            stream.flush()
            os.fsync(stream.fileno())

    def mark(self, name):
        self.phase = name
        print(json.dumps({'phase': name}), flush=True)

    def run(self, argv, timeout=25):
        result = subprocess.run(argv, capture_output=True, timeout=timeout)
        require(len(result.stdout) <= 2 * 1024 * 1024 and len(result.stderr) <= 65536, 'command output bound')
        if result.returncode:
            raise RuntimeError({'phase': self.phase, 'exit': result.returncode,
                                'stderr': result.stderr.decode(errors='replace')[:4096]})
        return result.stdout

    def ssh(self, port, program, timeout=25):
        return self.run(['ssh', '-i', str(self.args.ssh_key), '-p', str(port),
                         '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
                         '-o', 'StrictHostKeyChecking=yes',
                         '-o', 'UserKnownHostsFile=' + str(self.args.known_hosts), 'root@127.0.0.1',
                         'python3 -c ' + shlex.quote(program)], timeout)

    def mutation(self, label, details, function):
        require(label not in self.mutations, 'mutation retry prohibited')
        self.mutations.add(label)
        self.save(label + '-intent.json', {'phase': self.phase, 'details': details, 'automatic_retry': False})
        value = function()
        self.save(label + '-reply.json', value)
        return value

    def server(self, *arguments, expected=True, allow_unknown=False):
        program = f'''import json,pwd,subprocess
uid={self.operator!r};entry=pwd.getpwuid(uid)
p=subprocess.run({[self.args.guest_cli, 'server', *arguments]!r},capture_output=True,text=True,timeout=20,user=uid,group=entry.pw_gid,extra_groups=[])
print(json.dumps({{'exit':p.returncode,'value':json.loads(p.stdout),'stderr':p.stderr[:4096]}}))'''
        result = json.loads(self.ssh(self.args.server_port, program))
        uncertain = result['value'].get('outcome_unknown') is True and result['value'].get('automatic_retry') is False
        require((result['exit'] == 0) == expected or (allow_unknown and uncertain), result)
        return result['value']

    def server_mutation(self, label, *arguments, expected=True):
        return self.mutation(label, {'server': list(arguments)}, lambda: self.server(*arguments, expected=expected))

    def local(self, method, payload=None, closure=False):
        from actryn import robot_v1_pb2 as wire
        request = wire.Request(version=1, request_id=secrets.token_bytes(16), robot_epoch=self.epoch)
        getattr(request, method).CopyFrom(payload or wire.Empty())
        encoded = base64.b64encode(request.SerializeToString(deterministic=True)).decode()
        path = '/run/actryn-robot/' + ('closure.sock' if closure else 'operator.sock')
        program = f'''import base64,socket,struct,sys
s=socket.socket(socket.AF_UNIX);s.settimeout(8);s.connect({path!r})
assert struct.unpack('3i',s.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))[1]==0
b=base64.b64decode({encoded!r});s.sendall(struct.pack('!I',len(b))+b)
f=s.makefile('rb');h=f.read(4);assert len(h)==4;n=struct.unpack('!I',h)[0];assert 0<n<=65536
b=f.read(n);assert len(b)==n;sys.stdout.buffer.write(b)'''
        response = wire.Response.FromString(self.ssh(self.args.robot_port, program))
        require(response.version == 1 and response.request_id == request.request_id
                and len(response.robot_epoch) == 16, 'Robot reply identity')
        require(method == 'describe' or response.robot_epoch == request.robot_epoch, 'Robot epoch changed')
        if response.HasField('failure'):
            raise RuntimeError({'method': method, 'code': response.failure.code,
                                'message': response.failure.message, 'outcome_unknown': method != 'describe'})
        require(response.HasField('report'), 'Robot report missing')
        self.epoch = response.robot_epoch
        return json.loads(response.report.json)

    def local_mutation(self, label, method, payload=None, closure=False):
        return self.mutation(label, {'robot': method, 'epoch': self.epoch.hex()},
                             lambda: self.local(method, payload, closure))

    def poll(self, function, ready, timeout=12):
        deadline = time.monotonic() + timeout
        while True:
            self.last_poll = function()
            if ready(self.last_poll):
                return self.last_poll
            require(time.monotonic() < deadline, {'phase': self.phase, 'last_poll': self.last_poll})
            time.sleep(.1)

    def host_cli(self, *arguments, timeout=30):
        return json.loads(self.run([str(self.args.cli), 'robot', *arguments], timeout))

    def logs(self, attempt):
        require(re.fullmatch('[0-9a-f]{32}', attempt), 'attempt format')
        program = f'''import json,pathlib
p=pathlib.Path('/var/lib/actryn-server')/{attempt!r}
v={{n:(p/n).read_bytes() for n in ('stdout.log','stderr.log')}}
assert all(len(b)<=8192 for b in v.values())
print(json.dumps({{n:b.decode() for n,b in v.items()}}))'''
        return json.loads(self.ssh(self.args.server_port, program))

    def prepare(self, label):
        result = self.server_mutation(label + '-prepare', 'prepare', '--artifact', self.args.artifact)
        attempt = result['inspection']['attempt']['id']
        require(re.fullmatch('[0-9a-f]{32}', attempt), 'generated attempt identity')
        require(attempt not in self.attempts, 'attempt reused')
        self.attempts.append(attempt)
        return attempt

    def export_server(self, label, attempt):
        remote = self.remote_output + '/' + label + '.json'
        report = self.server('export', '--attempt', attempt, '--out', remote)
        self.save(label + '-server-export.json', report)
        raw = self.ssh(self.args.server_port, f"import pathlib,sys;p=pathlib.Path({remote!r});assert p.stat().st_size<=61440;sys.stdout.buffer.write(p.read_bytes())")
        bundle = json.loads(raw)
        verify_bundle(bundle, attempt)
        self.save(label + '-server-evidence.json', bundle)
        return bundle

    def cleanup_snapshot(self, attempt):
        require(re.fullmatch('[0-9a-f]{32}', attempt), 'cleanup attempt identity')
        program = f'''import contextlib,json,pathlib,sqlite3,stat,uuid
attempt={attempt!r};stores={{}};facts=None;binding=None
for name,path in [('launcher','/var/lib/actryn-server/launcher.sqlite'),('broker','/var/lib/actryn-server/broker/state.sqlite')]:
 with contextlib.closing(sqlite3.connect('file:'+path+'?mode=ro',uri=True,timeout=1)) as db:
  row=db.execute('SELECT state,binding FROM attempts WHERE id=?',(attempt,)).fetchone();assert row is not None
  gaps=db.execute('SELECT reason FROM gaps WHERE attempt_id=?',(attempt,)).fetchall()
  opened=db.execute('SELECT count(*) FROM calls WHERE attempt_id=? AND publication_closed=0',(attempt,)).fetchone()[0]
  pending=db.execute("SELECT count(*) FROM calls WHERE attempt_id=? AND state IN ('reserved','dispatched','unknown')",(attempt,)).fetchone()[0]
  remote=db.execute('SELECT count(*) FROM robot_requests WHERE attempt_id=? AND outstanding=1',(attempt,)).fetchone()[0]
  stores[name]={{'state':row[0],'gaps':gaps,'open_calls':opened,'pending_calls':pending,'robot_outstanding':remote}}
  if name=='launcher':
   binding=json.loads(row[1]);record=db.execute('SELECT data FROM runtime_evidence WHERE attempt_id=?',(attempt,)).fetchone()
   if record is not None:facts=json.loads(record[0])
epoch=binding['observer']['collector_epoch'];assert str(uuid.UUID(epoch))==epoch
log=pathlib.Path('/var/lib/actryn-observer')/epoch/(attempt+'.jsonl');summary_path=log.with_suffix('.summary.json')
ready=summary_path.exists() and log.exists();summary=None;size=None
if ready:
 m=summary_path.lstat();assert stat.S_ISREG(m.st_mode) and m.st_size<=4096
 summary=json.loads(summary_path.read_bytes());m=log.lstat();assert stat.S_ISREG(m.st_mode);size=m.st_size
print(json.dumps({{'stores':stores,'facts':facts,'observer_epoch':epoch,'summary':summary,'log_bytes':size,
'observer_summary_ready':ready,'cgroup_exists':pathlib.Path('/sys/fs/cgroup/actryn',attempt).exists()}}))
'''
        return json.loads(self.ssh(self.args.server_port, program))

    def cancel_server(self, label, attempt):
        # One cancellation, including an uncertain reply, never becomes a resend.
        try:
            reply = self.mutation(label + '-cancel', {'server': ['cancel', '--attempt', attempt]},
                lambda: self.server('cancel', '--attempt', attempt, allow_unknown=True))
            unknown = reply.get('outcome_unknown') is True
            original = {'reply': reply}
        except (subprocess.SubprocessError, TimeoutError, RuntimeError, ValueError) as error:
            unknown, original = True, {'transport_error': repr(error)}
        self.save(label + '-cleanup-ack.json', {**original, 'cancel_reply_unknown': unknown, 'mutation_retried': False})
        def inspect():
            return {'inspection': self.server('status', '--attempt', attempt)['inspection'],
                    'snapshot': self.cleanup_snapshot(attempt)}
        observed = self.poll(inspect, lambda value: cleanup_ready(value['snapshot'], value['inspection']), 12)
        self.save(label + '-cleanup-observed.json', observed)
        verify_cleanup(observed['snapshot'], observed['inspection'])
        calls = observed['inspection']['calls']
        if any(call['request_key'] == 'preview-1' for call in calls):
            require(self.server('result', '--attempt', attempt, '--key', 'preview-1')['value'] is None,
                    'cancelled result republished')
        else:
            # Prepared negative cases never allocated this key; Result correctly
            # rejects an absent row rather than returning a fabricated null call.
            require(calls == [], 'unexpected request identity after pre-start cancellation')

    def preflight(self):
        require(re.fullmatch('sha256:[0-9a-f]{64}', self.args.artifact), 'artifact pin format')
        self.save('host-cli-pin.json', {'sha256': hashlib.sha256(self.args.cli.read_bytes()).hexdigest()})
        for port, arch, kernel in [(self.args.server_port, 'x86_64', '6.12.111+deb13-amd64'),
                                   (self.args.robot_port, 'aarch64', '6.12.111+deb13-arm64')]:
            program = "import json,os,pathlib;print(json.dumps({'arch':os.uname().machine,'kernel':os.uname().release,'boot':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()}))"
            identity = json.loads(self.ssh(port, program))
            require(identity['arch'] == arch and identity['kernel'] == kernel, 'guest target mismatch')
            self.save(arch + '-guest.json', identity)
            if arch == 'x86_64': self.server_boot = identity['boot']
        require(b'linux,dummy-virt' in self.ssh(self.args.robot_port,
                "import pathlib,sys;sys.stdout.buffer.write(pathlib.Path('/proc/device-tree/compatible').read_bytes())"), 'ARM target is not disposable virt')
        program = f'''import errno,json,pathlib,stat,pwd,os,subprocess
subprocess.run(['/usr/bin/actryn-serverd','--check-config'],check=True,capture_output=True,timeout=20)
p=pathlib.Path({PEER!r});m=p.lstat();assert stat.S_ISREG(m.st_mode) and m.st_uid==0 and not m.st_mode&0o022 and m.st_size<=65536
peer=json.loads(p.read_bytes());config=json.loads(pathlib.Path('/etc/actryn/server.json').read_bytes())
root=pathlib.Path(config['artifacts'][{self.args.artifact!r}]['rootfs']);i=json.loads((root/'etc/actryn/input.json').read_bytes())
assert i.get('mode','offline')=='offline' and i['request_key']=='preview-1'
credential_path=pathlib.Path('/run/credentials/actryn-serverd.service/robot-client-key')
for parent in credential_path.parents:
 m=parent.lstat();assert stat.S_ISDIR(m.st_mode) and m.st_uid==0 and not m.st_mode&0o022
credential=credential_path.lstat()
try:acl=os.getxattr(credential_path,'system.posix_acl_access',follow_symlinks=False).hex()
except OSError as error:
 if error.errno not in (errno.ENODATA,errno.ENOTSUP):raise
 acl=None
credential_metadata={{'regular':stat.S_ISREG(credential.st_mode),'uid':credential.st_uid,'gid':credential.st_gid,
'mode':stat.S_IMODE(credential.st_mode),'nlink':credential.st_nlink,'size':credential.st_size,'acl_hex':acl}}
base=pathlib.Path('/var/lib/actryn-test-campaigns');base.mkdir(mode=0o755,exist_ok=True)
m=base.lstat();assert stat.S_ISDIR(m.st_mode) and m.st_uid==0 and not m.st_mode&0o022
out=pathlib.Path({self.remote_output!r});out.mkdir(mode=0o700);uid=config['operator_uid'];os.chown(out,uid,pwd.getpwuid(uid).pw_gid)
print(json.dumps({{'peer':peer,'operator_uid':uid,'input':i,'server_uid':config['server_uid'],'credential_metadata':credential_metadata}}))'''
        installed = json.loads(self.ssh(self.args.server_port, program))
        require(installed['peer'] == self.peer, 'installed public peer configuration mismatch')
        self.save('server-credential-metadata.json', installed['credential_metadata'])
        require(credential_metadata_safe(installed['credential_metadata'], installed['server_uid']),
                'systemd credential metadata/ACL differs from configured service identity')
        self.operator = installed['operator_uid']
        self.agent_input = installed['input']
        require(self.args.ca.read_text().strip() == self.peer['ca_pem'].strip()
                and self.args.certificate.read_text().strip() == self.peer['client_certificate_pem'].strip(), 'supplied public workload differs from installed peer')
        description = self.local('describe')
        require(description['live_actuation'] is False, 'live actuation must remain inhibited')
        require(description['runtime']['prepared'] is None
                and not description['runtime']['kernel']['flags'] & 8,
                'existing prepared namespace/output must be closed before this campaign')
        require(description['identity']['device_certificate_sha256'] == self.peer['robot_leaf_sha256']
                and bytes(description['configuration_digest']).hex() == self.peer['robot_configuration_digest']
                and bytes(description['profile_sha256']).hex() == self.peer['robot_profile_digest'], 'installed Robot identity/profile mismatch')
        self.save('initial-robot.json', description)
        pair = self.host_cli('pair', '--endpoint', '127.0.0.1:' + str(self.args.tcp_port),
                             '--dns', self.peer['dns_name'], '--pin', self.peer['robot_leaf_sha256'],
                             '--ca', str(self.args.ca), '--cert', str(self.args.certificate),
                             '--key', str(self.args.client_key), '--out', str(self.output / 'pair.json'))
        require(pair['authority_issued'] is False, 'pairing issued authority')
        self.save('pairing-report.json', pair)
        self.mark('explicit initial Robot recovery readiness')
        self.local_mutation('initial-recover', 'recover')
        self.poll(lambda: self.local('describe'), lambda d: d['runtime']['recovery_ready']
                  and not d['runtime']['recovery_pending'] and d['runtime']['kernel']['state'] == 0
                  and d['runtime']['kernel']['flags'] & 1, 15)

    def replace_peer(self, expected, replacement):
        program = peer_update_program(PEER, self.token, expected, replacement)
        report = json.loads(self.ssh(self.args.server_port, program))
        require(report.get('public_peer_replaced') is True, 'peer fault publication not confirmed')
        return report

    def restore_peer(self, label, changed):
        # Readback and restoration hold the same lock as the original publication.
        # SSH timeout is not proof that the remote root process was terminated.
        try:
            report = self.mutation(label + '-peer-restore', {'restoration': True}, lambda: json.loads(
                self.ssh(self.args.server_port, peer_update_program(PEER, self.token, self.peer, changed, restore=True))))
            require(report.get('restoration_confirmed') is True, 'restoration reply missing')
            return report
        except Exception as error:
            self.save(label + '-restoration-unknown.json', {'restoration_unknown': True,
                      'error': repr(error), 'automatic_retry': False,
                      'next_action': 'inspect/reap outstanding remote maintenance holder before explicit restoration'})
            raise RuntimeError('public peer restoration unknown; campaign stopped') from error

    def retire_and_recover(self):
        self.local_mutation('combined-retire', 'retire', closure=True)
        self.poll(lambda: self.local('describe'), lambda d: d['runtime']['retirement_ready'], 15)
        # All writers are finished; this one call can release the slot and begin recovery.
        self.local_mutation('final-recover', 'recover')
        self.poll(lambda: self.local('describe'), lambda d: d['runtime']['prepared'] is None
                  and d['runtime']['recovery_ready'] and not d['runtime']['recovery_pending']
                  and d['runtime']['kernel']['state'] == 0 and d['runtime']['kernel']['flags'] & 1
                  and not d['runtime']['kernel']['flags'] & 8, 15)

    def negative_bindings(self):
        for name, field, value in [('peer', 'endpoint', '127.0.0.1:1'),
                                   ('pin', 'robot_leaf_sha256', '0' * 64),
                                   ('configuration', 'robot_configuration_digest', '0' * 64)]:
            self.mark('pre-start rejected ' + name)
            attempt = self.prepare(name)
            changed = dict(self.peer, **{field: value})
            self.save(name + '-public-peer-fault.json', {'field': field,
                      'original_digest': digest(self.peer), 'temporary_digest': digest(changed)})
            try:
                self.mutation(name + '-peer-fault', {'field': field}, lambda: self.replace_peer(self.peer, changed))
                self.server_mutation(name + '-bind', 'bind-robot', '--attempt', attempt,
                                     '--namespace', secrets.token_hex(16), expected=False)
                state = self.server('status', '--attempt', attempt)['inspection']
                require(state['attempt']['state'] == 'prepared' and state['robot_binding'] is None
                        and state['robot_requests'] == [], 'rejected binding persisted or launched')
                require(self.logs(attempt) == {'stdout.log': '', 'stderr.log': ''}, 'agent ran before start')
            finally:
                self.restore_peer(name, changed)
            self.cancel_server(name, attempt)
            self.export_server(name, attempt)

    def independent_server(self):
        self.mark('independent unbound server and late-binding rejection')
        attempt = self.prepare('unbound')
        self.server_mutation('unbound-launch', 'launch', '--attempt', attempt)
        logs = self.poll(lambda: self.logs(attempt), lambda value: value['stdout.log'] or value['stderr.log'])
        require(not logs['stderr.log'], logs)
        event = json.loads(logs['stdout.log'])
        require(event['event'] == 'preview_proposal' and event['value']['trusted_robot_observation'] is None
                and event['value']['robot_handle'] is None, 'unbound attempt claimed Robot authority')
        self.server_mutation('unbound-late-bind', 'bind-robot', '--attempt', attempt,
                             '--namespace', secrets.token_hex(16), expected=False)
        state = self.server('status', '--attempt', attempt)['inspection']
        require(state['robot_binding'] is None and state['robot_requests'] == [], 'late binding succeeded')
        self.save('unbound-agent.json', event)
        self.cancel_server('unbound', attempt)
        self.export_server('unbound', attempt)

    def combined(self):
        from actryn import robot_v1_pb2 as wire
        self.mark('prepared server binding after explicit recovery')
        attempt, namespace = self.prepare('combined'), secrets.token_hex(16)
        binding = self.server_mutation('combined-bind', 'bind-robot', '--attempt', attempt,
                                      '--namespace', namespace)['binding']
        require(binding['robot_epoch'] == self.epoch.hex() and binding['principal'] == self.peer['principal'], 'binding session')
        self.mark('explicit local rearm prepare grant activate')
        self.local_mutation('combined-rearm', 'rearm')
        self.poll(lambda: self.local('describe'), lambda d: d['runtime']['kernel']['state'] == 1)
        self.local_mutation('combined-robot-prepare', 'prepare', wire.Prepare(
            attempt=bytes.fromhex(attempt), namespace=bytes.fromhex(namespace), principal=self.peer['principal']))
        ready = self.poll(lambda: self.local('describe'), lambda d: d['runtime']['preparation_ready'])
        require(bytes(ready['runtime']['prepared']['binding']['attempt']).hex() == attempt, 'prepared attempt')
        self.local_mutation('combined-grant', 'grant', wire.Grant(duration_ms=30_000))
        self.local_mutation('combined-activate', 'activate')
        self.mark('isolated agent actual observation and kernel operation')
        self.server_mutation('combined-launch', 'launch', '--attempt', attempt)
        logs = self.poll(lambda: self.logs(attempt), lambda value: value['stdout.log'] or value['stderr.log'])
        self.save('combined-agent-logs.json', logs)
        require(not logs['stderr.log'], logs)
        event = json.loads(logs['stdout.log'])
        require(event['event'] == 'preview_proposal' and event['authority_issued'] is False, 'agent result')
        result = self.server('result', '--attempt', attempt, '--key', 'preview-1')
        require(result['value'] == event['value'], 'stored result differs from original agent reply')
        inspection = self.server('status', '--attempt', attempt)['inspection']
        require(inspection['evidence_gaps'] == [] and len(inspection['calls']) == 1
                and inspection['calls'][0]['state'] == 'settled'
                and inspection['calls'][0]['consumed_tokens'] == 0, 'offline accounting/evidence incomplete')
        self.local_mutation('combined-reconcile', 'reconcile')
        completed = self.poll(lambda: self.server('robot-query', '--attempt', attempt, '--key', 'preview-1'),
                              lambda r: not r['request']['outstanding_debit'], 12)['request']
        verify_lineage(result['value'], completed, attempt, namespace)
        require(completed['request_digest'] == digest({'method': 'model.offline', 'input': {
            'goal': self.agent_input['goal'], 'observation_id': self.agent_input['observation_id']}}),
            'request digest differs from installed immutable agent input')
        snapshot = completed['last_remote']
        require(snapshot['terminal'] and snapshot['reconciled'] and snapshot['verdict'] == 'TargetReached'
                and snapshot['revision'] == snapshot['durable_revision'] > 0, 'durable natural reconciliation')
        description = self.local('describe')
        require(description['runtime']['operation']['operation'] == snapshot['operation'], 'Robot runtime operation differs')
        kernel, operation = description['runtime']['kernel'], snapshot['operation']
        verify_kernel_completion(kernel, operation)
        self.save('combined-completed.json', completed)
        self.save('combined-kernel-description.json', description)
        self.mark('close publication retire recover and export')
        self.cancel_server('combined', attempt)
        self.retire_and_recover()
        final_logs = self.logs(attempt)
        require(final_logs == logs, 'agent logs changed during final cleanup')
        self.save('combined-final-agent-logs.json', final_logs)
        bundle = self.export_server('combined', attempt)
        verify_final_bundle(bundle, attempt, binding, completed, final_logs, self.server_boot, self.args.artifact)
        handle = dict(completed['handle'], robot_epoch=completed['robot_epoch'], state='cancel_requested', proposal=None)
        self.save('retained-handle.json', handle)
        report = self.host_cli('export', '--pair', str(self.output / 'pair.json'),
                               '--cert', str(self.args.certificate), '--key', str(self.args.client_key),
                               '--handle', str(self.output / 'retained-handle.json'),
                               '--out', str(self.output / 'robot-evidence'), timeout=120)
        require(report['execution_replay_eligible'] is False and report['volatile_tail_unknown'] is True, 'Robot evidence boundary')
        self.save('robot-export-report.json', report)
        self.save('result.json', {'status': 'PASS', 'test': 'isolated-offline-agent-trusted-robot',
                  'attempt_id': attempt, 'namespace': namespace, 'operation': operation,
                  'artifact_digest': self.args.artifact, 'physical_acceptance': False,
                  'live_provider_calls': False, 'two_operations_under_one_grant_tested_here': False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-disposable-guests', action='store_true', required=True)
    parser.add_argument('--ssh-key', type=Path, required=True)
    parser.add_argument('--known-hosts', type=Path, required=True)
    parser.add_argument('--server-port', type=int, default=26220)
    parser.add_argument('--robot-port', type=int, default=26221)
    parser.add_argument('--tcp-port', type=int, default=27443)
    parser.add_argument('--cli', type=Path, default=ROOT / 'target/debug/actryn')
    parser.add_argument('--guest-cli', default='/usr/local/bin/actryn')
    parser.add_argument('--artifact', required=True)
    parser.add_argument('--peer-config', type=Path, required=True)
    parser.add_argument('--ca', type=Path, required=True)
    parser.add_argument('--certificate', type=Path, required=True)
    parser.add_argument('--client-key', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    sys.path.insert(0, str(ROOT / 'sdk/python'))
    campaign = Campaign(args)
    try:
        campaign.preflight()
        campaign.negative_bindings()
        campaign.independent_server()
        campaign.combined()
        print(json.dumps({'status': 'PASS', 'output': str(campaign.output)}), flush=True)
    except Exception as error:
        campaign.save('failure.json', {'phase': campaign.phase, 'error': repr(error),
                      'last_poll': campaign.last_poll, 'attempts': campaign.attempts,
                      'automatic_mutation_retry': False, 'outcomes_may_be_unknown': True,
                      'next_action': 'inspect retained identities; explicitly cancel/recover before a fresh campaign'})
        raise


class VerificationTests(unittest.TestCase):
    def test_natural_reconciliation_preserves_grant_but_requires_zero_output(self):
        operation = {'device': [1]*16, 'boot': 1, 'session': 2, 'runtime_nonce': [3]*16,
                     'grant': 4, 'instance': 5, 'operation': 6, 'stream': 7}
        kernel = {'device_identity': [1]*16, 'controller_boot': 1, 'controller_session': 2,
                  'runtime_nonce': [3]*16, 'grant': 4, 'instance': 5, 'operation': 6,
                  'stream': 7, 'flags': 9, 'operation_state': 4, 'left_permille': 0, 'right_permille': 0}
        verify_kernel_completion(kernel, operation)
        for field, value in [('operation_state', 2), ('left_permille', 10), ('operation', 8)]:
            with self.assertRaises(AssertionError):
                verify_kernel_completion(dict(kernel, **{field: value}), operation)

    def test_retirement_waits_for_workers_then_recovers_once(self):
        campaign = object.__new__(Campaign)
        events = []
        campaign.local_mutation = lambda label, method, *a, **k: events.append(method)
        campaign.local = lambda method: None
        def poll(function, ready, timeout=12):
            if events == ['retire']:
                self.assertFalse(ready({'runtime': {'prepared': {'instance': 1}, 'retirement_ready': False}}))
                self.assertTrue(ready({'runtime': {'prepared': {'instance': 1}, 'retirement_ready': True}}))
            else:
                self.assertEqual(events, ['retire', 'recover'])
                self.assertFalse(ready({'runtime': {'prepared': {'instance': 1}, 'recovery_ready': False, 'recovery_pending': False,
                                                  'kernel': {'state': 0, 'flags': 1}}}))
                self.assertTrue(ready({'runtime': {'prepared': None, 'recovery_ready': True, 'recovery_pending': False,
                                                 'kernel': {'state': 0, 'flags': 1}}}))
        campaign.poll = poll
        campaign.retire_and_recover()
        self.assertEqual(events, ['retire', 'recover'])

    def test_restore_timeout_is_explicitly_unknown_and_never_reported_confirmed(self):
        campaign = object.__new__(Campaign)
        campaign.peer, campaign.token, campaign.mutations = {'endpoint': 'original'}, 'a' * 16, set()
        campaign.phase = 'test'
        campaign.args = type('Args', (), {'server_port': 1})()
        campaign.ssh = lambda *a, **k: (_ for _ in ()).throw(TimeoutError('remote process not reaped'))
        records = []
        campaign.save = lambda name, value: records.append((name, value))
        with self.assertRaises(RuntimeError): campaign.restore_peer('case', {'endpoint': 'fault'})
        self.assertTrue(any(value.get('restoration_unknown') is True for _, value in records))
        self.assertFalse(any(value.get('restoration_confirmed') is True for _, value in records))

    def test_restore_cannot_observe_original_while_fault_writer_holds_lock(self):
        import fcntl
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'robot-peer.json'
            path.write_bytes(compact({'endpoint': 'original'})); path.chmod(0o600)
            lock = path.with_name('robot-peer.acceptance.lock')
            with lock.open('w') as held:
                os.chmod(lock, 0o600); fcntl.flock(held, fcntl.LOCK_EX)
                script = peer_update_program(path, 'a' * 16, {'endpoint': 'original'}, {'endpoint': 'fault'},
                                             restore=True, uid=os.geteuid(), lock_timeout=.05)
                result = subprocess.run([sys.executable, '-c', script], capture_output=True, timeout=3)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(b'restoration_confirmed', result.stdout)
                path.write_bytes(compact({'endpoint': 'fault'}))
            result = subprocess.run([sys.executable, '-c', script], capture_output=True, timeout=3)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)['restoration_confirmed'])
            self.assertEqual(json.loads(path.read_bytes()), {'endpoint': 'original'})

    def test_final_evidence_rejects_cleanup_loss_and_wrong_attribution_even_with_valid_hashes(self):
        attempt, binding = 'a' * 32, {'attempt_id': 'a' * 32, 'namespace': 'b' * 32}
        handle = {'attempt': attempt, 'namespace': 'b' * 32, 'key': 'c' * 64}
        completed = {'request_key': 'preview-1', 'handle': handle, 'robot_epoch': 'd' * 32,
                     'observation': {'id': 1}, 'observation_digest': 'sha256:' + 'e' * 64,
                     'proposal_digest': 'sha256:' + 'f' * 64}
        observer = {'ready': True, 'collector_epoch': 'observer-1', 'coverage': list(REQUIRED_COVERAGE), 'sequence': 10, 'lost': 0}
        logs = {'stdout.log': 'actual agent reply\n', 'stderr.log': ''}
        content = {
            'attempt': {'id': attempt, 'state': 'reaped', 'artifact_digest': 'sha256:' + '1' * 64},
            'runtime_binding': {'boot_id': 'boot-1', 'cgroup_id': 42, 'ambiguous_create': False,
                                'observer': observer, 'snapshot': {'cgroup': '/actryn/' + attempt, 'pid': 2, 'start_ticks': 3}},
            'runtime_facts': {'observer_health_unavailable': False, 'observer': dict(observer, sequence=12),
                              'resources': {'classification': 'observed_cgroup_v2_counters', 'captured_boottime_ms': 123,
                                            'stage': 'after_descendants_empty_before_runtime_delete',
                                            'counters': {name: '0\n' for name in RESOURCE_COUNTERS}, 'unavailable': []}},
            'broker': {'attempt_state': 'reaped', 'calls': [{'request_key': 'preview-1', 'state': 'settled',
                       'consumed_tokens': 0, 'publication_closed': True}], 'evidence_gaps': [],
                       'policy_denials': [], 'policy_denials_retained': 0},
            'robot': {'classification': 'trusted_peer_delegation_metadata', 'binding': binding, 'requests_retained': 1,
                      'outstanding_debits': 0, 'requests': [{'request_key': 'preview-1', 'handle': handle, 'robot_epoch': 'd' * 32,
                      'phase': 'settled', 'outstanding_debit': False, 'remote_verdict': 'TargetReached', 'reconciled': True,
                      'observation_id': 1, 'observation_digest': completed['observation_digest'], 'proposal_digest': completed['proposal_digest']}]}}
        for name in ('stdout', 'stderr'):
            raw = logs[name + '.log'].encode()
            content[name] = {'classification': 'untrusted_agent_output_not_policy_attribution', 'retained_bytes': len(raw),
                             'retained_sha256': 'sha256:' + hashlib.sha256(raw).hexdigest(), 'source_truncated': False,
                             'file_complete': True, 'tail_omitted_bytes': 0, 'tail_encoding': 'hex', 'tail': raw.hex()}
        def bundle(values, omissions=None):
            return {'schema': 'actryn.server.evidence.v1', 'attempt_id': attempt, 'execution_replay_eligible': False,
                    'omissions': omissions or [], 'artifacts': [{'name': name, 'content': value,
                    'bytes': len(compact(value)), 'sha256': digest(value)} for name, value in values.items()]}
        check = lambda value: verify_final_bundle(value, attempt, binding, completed, logs, 'boot-1', 'sha256:' + '1' * 64)
        check(bundle(content))
        with self.assertRaises(AssertionError): check(bundle(content, [{'artifact': 'runtime_facts', 'reason': 'observer_unavailable'}]))
        faults = [('runtime_facts', 'observer_health_unavailable', True), ('runtime_facts', 'observer', None),
                  ('broker', 'evidence_gaps', ['log_incomplete']), ('runtime_binding', 'boot_id', 'wrong-boot'),
                  ('robot', 'binding', dict(binding, namespace='wrong')), ('robot', 'outstanding_debits', 1),
                  ('stdout', 'file_complete', False), ('stdout', 'source_truncated', True),
                  ('stdout', 'retained_sha256', 'sha256:' + '0' * 64)]
        for name, field, value in faults:
            changed = copy.deepcopy(content); changed[name][field] = value
            with self.assertRaises(AssertionError, msg=(name, field)): check(bundle(changed))
        for field, value in [('lost', 1), ('ready', False), ('collector_epoch', 'other'), ('coverage', [])]:
            changed = copy.deepcopy(content); changed['runtime_facts']['observer'][field] = value
            with self.assertRaises(AssertionError, msg=field): check(bundle(changed))
        for field, value in [('unavailable', ['cpu.stat']), ('counters', {})]:
            changed = copy.deepcopy(content); changed['runtime_facts']['resources'][field] = value
            with self.assertRaises(AssertionError, msg=field): check(bundle(changed))
        changed = copy.deepcopy(content); changed['runtime_facts']['observer']['sequence'] = 9
        with self.assertRaises(AssertionError): check(bundle(changed))
        changed = copy.deepcopy(content); changed['robot']['requests'][0]['handle']['key'] = '0' * 64
        with self.assertRaises(AssertionError): check(bundle(changed))
        changed = copy.deepcopy(content); changed['stdout']['tail'] = '00'
        with self.assertRaises(AssertionError): check(bundle(changed))

    def test_cancel_lost_reply_polls_read_only_convergence_without_resend(self):
        for reply in ({'result': 'error', 'outcome_unknown': True, 'automatic_retry': False}, TimeoutError('lost SSH reply')):
            campaign = object.__new__(Campaign)
            campaign.phase, campaign.mutations = 'test', set()
            events, records = [], []
            campaign.save = lambda name, value: records.append((name, value))
            inspection = {'attempt': {'state': 'reaped'}, 'evidence_gaps': [], 'robot_requests': [], 'calls': []}
            snapshot = {'stores': {name: {'state': 'reaped', 'gaps': [], 'open_calls': 0, 'pending_calls': 0,
                        'robot_outstanding': 0} for name in ('broker', 'launcher')}, 'cgroup_exists': False,
                        'observer_summary_ready': True, 'facts': {'resources': {'unavailable': []}, 'observer_health_unavailable': False,
                        'observer': {'ready': True, 'lost': 0, 'sequence': 3, 'collector_epoch': 'observer'}},
                        'observer_epoch': 'observer', 'log_bytes': 10, 'summary': {'local_lost': 0,
                        'retained_bytes': 10, 'status': {'ready': True, 'lost': 0, 'sequence': 4, 'collector_epoch': 'observer'}}}
            def server(*args, **kwargs):
                events.append(args[0])
                if args[0] == 'cancel':
                    if isinstance(reply, Exception): raise reply
                    return reply
                return {'inspection': inspection} if args[0] == 'status' else {'value': None}
            campaign.server = server
            campaign.cleanup_snapshot = lambda attempt: copy.deepcopy(snapshot)
            campaign.poll = lambda function, ready, timeout=12: (lambda value: value if ready(value) else self.fail('not ready'))(function())
            campaign.cancel_server('case', 'a' * 32)
            self.assertEqual(events.count('cancel'), 1)
            self.assertNotIn('result', events, 'absent pre-start request must not be queried as a retained call')
            self.assertTrue(any(value.get('cancel_reply_unknown') is True for _, value in records))
            broken = copy.deepcopy(snapshot); broken['summary']['local_lost'] = 1
            with self.assertRaises(AssertionError): verify_cleanup(broken, inspection)
            broken = copy.deepcopy(snapshot); broken['stores']['broker']['robot_outstanding'] = 1
            self.assertFalse(cleanup_ready(broken, inspection))
            broken = copy.deepcopy(snapshot); broken['cgroup_exists'] = True
            self.assertFalse(cleanup_ready(broken, inspection))

    def test_server_cancel_accepts_only_explicit_unknown_or_success(self):
        campaign = object.__new__(Campaign)
        campaign.operator = 1000
        campaign.args = type('Args', (), {'server_port': 1, 'guest_cli': '/usr/local/bin/actryn'})()
        for value, allowed in [({'outcome_unknown': True, 'automatic_retry': False}, True),
                               ({'outcome_unknown': False, 'automatic_retry': False}, False)]:
            campaign.ssh = lambda *a, value=value, **k: compact({'exit': 1, 'value': value, 'stderr': ''})
            if allowed:
                self.assertEqual(campaign.server('cancel', '--attempt', 'a' * 32, allow_unknown=True), value)
            else:
                with self.assertRaises(AssertionError): campaign.server('cancel', '--attempt', 'a' * 32, allow_unknown=True)
        programs = []
        campaign.ssh = lambda port, program: programs.append(program) or b'{}'
        campaign.cleanup_snapshot('a' * 32)
        compile(programs[0], '<read-only-guest-cleanup-inspection>', 'exec')

    def test_systemd_credential_acl_is_exact_and_bound_to_configured_service_uid(self):
        metadata = {'regular': True, 'uid': 0, 'gid': 0, 'mode': 0o440, 'nlink': 1, 'size': 1704,
                    'acl_hex': '0200000001000400ffffffff02000400db03000004000000ffffffff10000400ffffffff20000000ffffffff'}
        self.assertTrue(credential_metadata_safe(metadata, 987))
        self.assertFalse(credential_metadata_safe(metadata, 986))
        for field, value in [('uid', 987), ('gid', 987), ('mode', 0o444), ('nlink', 2), ('regular', False),
                             ('size', 8193), ('acl_hex', None), ('acl_hex', metadata['acl_hex'] + '00')]:
            self.assertFalse(credential_metadata_safe(dict(metadata, **{field: value}), 987), field)
        for index in (0, 6, 14, 22, 30, 38):
            encoded = bytearray.fromhex(metadata['acl_hex']); encoded[index] ^= 1
            self.assertFalse(credential_metadata_safe(dict(metadata, acl_hex=encoded.hex()), 987))
        for uid in (0, 987):
            self.assertTrue(credential_metadata_safe(dict(metadata, uid=uid, mode=0o600, acl_hex=None), 987))
        self.assertFalse(credential_metadata_safe(dict(metadata, uid=986, mode=0o600, acl_hex=None), 987))

    def test_failed_mutation_is_not_repeated(self):
        campaign = object.__new__(Campaign)
        campaign.phase, campaign.mutations = 'test', set()
        records, calls = [], []
        campaign.save = lambda name, value: records.append((name, value))
        def uncertain():
            calls.append(1)
            raise TimeoutError('reply lost')
        with self.assertRaises(TimeoutError): campaign.mutation('one', {}, uncertain)
        with self.assertRaises(AssertionError): campaign.mutation('one', {}, uncertain)
        self.assertEqual(calls, [1])
        self.assertEqual(records[0][0], 'one-intent.json')

    def test_bundle_hashes_and_identity_are_checked(self):
        content = {'counter': 1}
        bundle = {'schema': 'actryn.server.evidence.v1', 'attempt_id': 'a' * 32, 'execution_replay_eligible': False,
                  'artifacts': [{'name': 'robot', 'content': content, 'bytes': len(compact(content)), 'sha256': digest(content)}]}
        self.assertEqual(verify_bundle(bundle, 'a' * 32), {'robot'})
        broken = copy.deepcopy(bundle); broken['artifacts'][0]['content']['counter'] = 2
        with self.assertRaises(AssertionError): verify_bundle(broken, 'a' * 32)
        with self.assertRaises(AssertionError): verify_bundle(bundle, 'b' * 32)

    def test_lineage_requires_same_actual_observation_and_remote_handle(self):
        observation = dict(zip(OBSERVATION_FIELDS, [7, 1, 2, 1_000_000_001, 3, 4, 5, True, 1, 100]))
        handle = {'attempt': 'a' * 32, 'namespace': 'b' * 32, 'key': 'c' * 64}
        intent = {'request_key': 'preview-1', 'request_digest': 'sha256:' + 'd' * 64,
                  'robot_epoch': 'e' * 32, 'handle': handle, 'observation': observation,
                  'observation_digest': digest(observation, sort=False)}
        intent['parent_digest'] = digest({k: intent[k] for k in ('handle', 'request_digest', 'robot_epoch', 'observation')})
        value = {'origin': 'server_attested', 'attempt_id': handle['attempt'], 'request_key': 'preview-1',
                 'model': 'offline-fixture', 'output': {'left_delta_ticks': 10, 'right_delta_ticks': 10, 'duration_ms': 1000},
                 'robot_handle': handle, 'trusted_robot_observation': observation,
                 'observation_digest': intent['observation_digest'], 'lineage_digest': intent['parent_digest'],
                 'request_digest': intent['request_digest'], 'agent_observation_reference': 'offline-preview-reference'}
        verify_lineage(value, intent, handle['attempt'], handle['namespace'])
        for field, replacement in [('trusted_robot_observation', {'id': 'offline-preview-reference'}),
                                   ('robot_handle', dict(handle, key='f' * 64)), ('observation_digest', 'sha256:' + '0' * 64)]:
            broken = dict(value, **{field: replacement})
            with self.assertRaises(AssertionError): verify_lineage(broken, intent, handle['attempt'], handle['namespace'])


if __name__ == '__main__':
    if sys.argv[1:] == ['--self-test']:
        unittest.main(argv=[sys.argv[0]])
    else:
        main()
