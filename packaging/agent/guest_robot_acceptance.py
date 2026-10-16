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
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
PEER = '/etc/actryn/robot-peer.json'
OBSERVATION_FIELDS = ('id', 'acquired_earliest_ns', 'acquired_latest_ns', 'valid_until_ns',
                      'controller_ns', 'left_ticks', 'right_ticks', 'simulated',
                      'context_revision', 'received_ms')


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


def verify_bundle(bundle, attempt):
    require(bundle['attempt_id'] == attempt and bundle['execution_replay_eligible'] is False, 'bundle identity')
    require(len(compact(bundle)) <= 60 * 1024, 'bundle bound')
    names = set()
    for artifact in bundle['artifacts']:
        require(artifact['name'] not in names, 'duplicate artifact')
        names.add(artifact['name'])
        require(artifact['bytes'] == len(compact(artifact['content']))
                and artifact['sha256'] == digest(artifact['content']), 'artifact hash/length')
    return names


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

    def server(self, *arguments, expected=True):
        program = f'''import json,pwd,subprocess
uid={self.operator!r};entry=pwd.getpwuid(uid)
p=subprocess.run({[self.args.guest_cli, 'server', *arguments]!r},capture_output=True,text=True,timeout=20,user=uid,group=entry.pw_gid,extra_groups=[])
print(json.dumps({{'exit':p.returncode,'value':json.loads(p.stdout),'stderr':p.stderr[:4096]}}))'''
        result = json.loads(self.ssh(self.args.server_port, program))
        require((result['exit'] == 0) == expected, result)
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

    def cancel_server(self, label, attempt):
        self.server_mutation(label + '-cancel', 'cancel', '--attempt', attempt)
        self.poll(lambda: self.server('status', '--attempt', attempt),
                  lambda value: value['inspection']['attempt']['state'] == 'reaped')
        require(self.server('result', '--attempt', attempt, '--key', 'preview-1')['value'] is None,
                'cancelled result republished')

    def preflight(self):
        require(re.fullmatch('sha256:[0-9a-f]{64}', self.args.artifact), 'artifact pin format')
        self.save('host-cli-pin.json', {'sha256': hashlib.sha256(self.args.cli.read_bytes()).hexdigest()})
        for port, arch, kernel in [(self.args.server_port, 'x86_64', '6.12.111+deb13-amd64'),
                                   (self.args.robot_port, 'aarch64', '6.12.111+deb13-arm64')]:
            program = "import json,os,pathlib;print(json.dumps({'arch':os.uname().machine,'kernel':os.uname().release,'boot':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()}))"
            identity = json.loads(self.ssh(port, program))
            require(identity['arch'] == arch and identity['kernel'] == kernel, 'guest target mismatch')
            self.save(arch + '-guest.json', identity)
        require(b'linux,dummy-virt' in self.ssh(self.args.robot_port,
                "import pathlib,sys;sys.stdout.buffer.write(pathlib.Path('/proc/device-tree/compatible').read_bytes())"), 'ARM target is not disposable virt')
        program = f'''import json,pathlib,stat,pwd,os,subprocess
subprocess.run(['/usr/bin/actryn-serverd','--check-config'],check=True,capture_output=True,timeout=20)
p=pathlib.Path({PEER!r});m=p.lstat();assert stat.S_ISREG(m.st_mode) and m.st_uid==0 and not m.st_mode&0o022 and m.st_size<=65536
peer=json.loads(p.read_bytes());config=json.loads(pathlib.Path('/etc/actryn/server.json').read_bytes())
root=pathlib.Path(config['artifacts'][{self.args.artifact!r}]['rootfs']);i=json.loads((root/'etc/actryn/input.json').read_bytes())
assert i.get('mode','offline')=='offline' and i['request_key']=='preview-1'
credential=pathlib.Path('/run/credentials/actryn-serverd.service/robot-client-key').stat();assert stat.S_ISREG(credential.st_mode) and not credential.st_mode&0o077
base=pathlib.Path('/var/lib/actryn-test-campaigns');base.mkdir(mode=0o755,exist_ok=True)
m=base.lstat();assert stat.S_ISDIR(m.st_mode) and m.st_uid==0 and not m.st_mode&0o022
out=pathlib.Path({self.remote_output!r});out.mkdir(mode=0o700);uid=config['operator_uid'];os.chown(out,uid,pwd.getpwuid(uid).pw_gid)
print(json.dumps({{'peer':peer,'operator_uid':uid,'input':i}}))'''
        installed = json.loads(self.ssh(self.args.server_port, program))
        require(installed['peer'] == self.peer, 'installed public peer configuration mismatch')
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
        # Only this fixed public configuration is fault-injected, with compare-before-replace.
        program = f'''import json,os,pathlib,stat
p=pathlib.Path({PEER!r});assert json.loads(p.read_bytes())=={expected!r}
m=p.stat();assert m.st_uid==0 and not m.st_mode&0o022
t=p.with_name('robot-peer.acceptance-{self.token}.tmp')
with t.open('xb') as f:f.write({compact(replacement)!r});f.flush();os.fsync(f.fileno())
os.chown(t,m.st_uid,m.st_gid);os.chmod(t,stat.S_IMODE(m.st_mode));os.replace(t,p)
fd=os.open(p.parent,os.O_DIRECTORY);os.fsync(fd);os.close(fd)
print('{{"public_peer_replaced":true}}')'''
        self.ssh(self.args.server_port, program)

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
                self.replace_peer(self.peer, changed)
                self.server_mutation(name + '-bind', 'bind-robot', '--attempt', attempt,
                                     '--namespace', secrets.token_hex(16), expected=False)
                state = self.server('status', '--attempt', attempt)['inspection']
                require(state['attempt']['state'] == 'prepared' and state['robot_binding'] is None
                        and state['robot_requests'] == [], 'rejected binding persisted or launched')
                require(self.logs(attempt) == {'stdout.log': '', 'stderr.log': ''}, 'agent ran before start')
            finally:
                # Restoration also covers a lost acknowledgment of the replacement.
                # It never overwrites an unrelated concurrent administrator change.
                current = json.loads(self.ssh(self.args.server_port,
                    f"import pathlib,sys;sys.stdout.buffer.write(pathlib.Path({PEER!r}).read_bytes())"))
                if current != self.peer:
                    require(current == changed, 'public peer changed concurrently; explicit restoration required')
                    self.replace_peer(changed, self.peer)
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
        for source, target in [('device_identity', 'device'), ('controller_boot', 'boot'),
                               ('controller_session', 'session'), ('runtime_nonce', 'runtime_nonce'),
                               ('grant', 'grant'), ('instance', 'instance'), ('operation', 'operation'), ('stream', 'stream')]:
            require(kernel[source] == operation[target], 'actual kernel identity: ' + source)
        require(not kernel['flags'] & 8 and kernel['left_permille'] == kernel['right_permille'] == 0, 'kernel output remains open')
        self.save('combined-completed.json', completed)
        self.save('combined-kernel-description.json', description)
        self.mark('close publication retire recover and export')
        self.cancel_server('combined', attempt)
        self.local_mutation('combined-retire', 'retire', closure=True)
        self.poll(lambda: self.local('describe'), lambda d: d['runtime']['prepared'] is None, 15)
        self.local_mutation('final-recover', 'recover')
        self.poll(lambda: self.local('describe'), lambda d: d['runtime']['recovery_ready']
                  and not d['runtime']['recovery_pending'] and d['runtime']['kernel']['state'] == 0
                  and not d['runtime']['kernel']['flags'] & 8, 15)
        bundle = self.export_server('combined', attempt)
        require({'robot', 'broker', 'runtime_binding', 'runtime_facts', 'stdout', 'stderr'}
                <= verify_bundle(bundle, attempt), 'delegation/runtime evidence absent')
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
        bundle = {'attempt_id': 'a' * 32, 'execution_replay_eligible': False,
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
