#!/usr/bin/env python3
"""Opt-in, separately labeled A02/A09 actual-manager failure campaigns.

No enrollment, service restart, mutation retry, physical device or production
fault injection. Credentials and exact disposable-guest pins are supplied.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import secrets
import select
import shlex
import subprocess
import threading
import time

from guest import CAMPAIGN, ROOT, Client, phase, wire, write_json
from actryn import OutcomeUnknown, RpcError
from source_gap import Campaign as BaseCampaign, no_effect, require, sha
from reply_gate import ReplyGate
from sqlite_contention import LEASE_NS


def operation_id(status):
    names = {'device': 'device_identity', 'boot': 'controller_boot', 'session': 'controller_session',
             'runtime_nonce': 'runtime_nonce', 'grant': 'grant', 'instance': 'instance',
             'operation': 'operation', 'stream': 'stream'}
    result = {key: status[name] for key, name in names.items()}
    require(all(result[k] > 0 for k in ('boot', 'session', 'grant', 'instance', 'operation', 'stream'))
            and any(result['device']) and any(result['runtime_nonce']), 'nonzero full operation identity')
    return result


def same_operation(status, operation):
    # Retiring a grant clears instance but cannot rename its retained operation.
    return (status['device_identity'] == operation['device']
            and status['controller_boot'] == operation['boot']
            and status['controller_session'] == operation['session']
            and all(status[k] == operation[k] for k in ('runtime_nonce', 'grant', 'operation', 'stream')))


def durable_cancel(snapshot, handle, operation):
    return (snapshot is not None and snapshot['namespace'] == list(handle.namespace)
            and snapshot['key'] == list(handle.key) and snapshot['operation'] == operation
            and snapshot['phase'] == 'CancelledDurable' and snapshot['terminal']
            and snapshot['cancellation_durable'] and not snapshot['persistence_failed']
            and snapshot['revision'] > 0 and snapshot['revision'] == snapshot['durable_revision']
            and snapshot['verdict'] == 'Cancelled' and snapshot['reconciled'])


def pre_send_ready(description, handle):
    runtime = description['runtime']
    kernel, health, prepared = runtime['kernel'], runtime['health'], runtime['prepared']
    require(description['clock_healthy'] and health['healthy'] and not health['inhibited']
            and not health['evidence_issues'] and runtime['event_stream_healthy']
            and runtime['preparation_ready'] and not runtime['retiring']
            and prepared is not None and prepared['binding']['attempt'] == list(handle.attempt)
            and prepared['binding']['namespace'] == list(handle.namespace)
            and kernel['state'] == 2 and kernel['flags'] & 8 and kernel['grant'] > 0
            and kernel['operation_state'] == 0 and kernel['operation'] == kernel['stream'] == 0
            and kernel['left_permille'] == kernel['right_permille'] == 0
            and runtime['operation'] is None, 'pre-existing fault or operation before proposal')


def validate_capture(decoded, handle, prepared, operation, mode, lease=None):
    require(decoded['format'] == 'actryn-failure-capture-1'
            and decoded['attempt'] == list(handle.attempt)
            and decoded['configuration_digest'] == prepared['configuration_digest']
            and decoded['policy'] == 'MetadataOnly', 'capture binding or policy')
    require(not decoded['issues'] and not decoded['raw_remnants'], 'capture recovery issues')
    require(decoded['volatile_tail_unknown'] and not decoded['execution_replay_eligible'],
            'metadata capture must not claim full execution replay')
    require(len(decoded['frontiers']) == len(decoded['sources']) == 2, 'capture producer count')
    for source, frontier in zip(decoded['sources'], decoded['frontiers']):
        require(not source['missing_record_ordinals'] and not source['source_gap_record_ordinals']
                and frontier['gap_count'] == 0 and frontier['durable'] == frontier['read']
                and source['last_record_ordinal'] == source['durable_frontier'],
                'missing or non-durable capture prefix')
    records = decoded['records']
    require(not any(r['kind'] == 'SourceGap' for r in records), 'independent source fault')
    events = [r['value'] for r in records if r['origin'] == 'Kernel' and r['kind'] == 'Transition']
    require(events and all(b['sequence'] == a['sequence'] + 1 for a, b in zip(events, events[1:])),
            'external kernel event discontinuity')
    require(len({e['status']['events_lost'] for e in events}) == 1, 'external event loss changed')
    matching = [e for e in events if same_operation(e['status'], operation)]
    allocated = [e for e in matching if e['kind'] == 0x1000e]
    require(len(allocated) == 1 and allocated[0]['status']['operation_state'] == 6
            and operation_id(allocated[0]['status']) == operation, 'one exact kernel allocation')
    proposals = [r['value'] for r in records if r['origin'] == 'Runtime' and r['kind'] == 'Execution'
                 and isinstance(r['value'], list) and len(r['value']) == 4
                 and r['value'][0] == list(handle.key)]
    require(len(proposals) == 1, 'exactly one accepted proposal for saved key')
    closures = [e for e in matching if e['kind'] == 0x30002 and e['status']['reason'] == 2]
    require(closures and any(e['status']['operation_state'] == 4 for e in matching),
            'durable kernel cancellation and reconciliation receipts')
    starts = [e for e in matching if e['kind'] == 0x10007]
    if mode == 'a02':
        require(len(starts) == 1 and starts[0]['sequence'] < closures[0]['sequence'],
                'A02 requires one START before cancellation')
    else:
        require(lease is not None and lease['released'] and lease['within_lease']
                and 'error' not in lease and not starts
                and lease['locked_ns'] <= allocated[0]['captured_ns']
                < closures[0]['captured_ns'] <= lease['released_ns'],
                'A09 requires allocation and urgent closure inside actual writer lock, without START')
        require(all(e['status']['left_permille'] == e['status']['right_permille'] == 0
                    for e in matching), 'A09 must not publish nonzero output')
    return {'allocation_sequence': allocated[0]['sequence'], 'closure_sequence': closures[0]['sequence'],
            'start_count': len(starts), 'accepted_proposal_records': len(proposals),
            'operation': operation, 'volatile_tail_unknown': True, 'full_execution_replay': False}


class OneProposal:
    """One SDK mutation, one worker; exceptions never cause another send."""
    def __init__(self, rpc, handle, observation):
        self.rpc, self.handle, self.observation = rpc, handle, observation
        self.done = threading.Event()
        self.result = {'calls': 0, 'automatic_retries': 0}
        self.worker = threading.Thread(target=self._run, name='single-proposal', daemon=True)

    def start(self):
        require(self.worker.ident is None, 'proposal cannot be restarted')
        self.worker.start()

    def _run(self):
        self.result['calls'] += 1
        self.result['sent_at_host_ns'] = time.monotonic_ns()
        try:
            self.result['reply'] = self.rpc.propose(self.handle, observation_id=self.observation['id'],
                left_delta_ticks=100, right_delta_ticks=-100, duration_ms=10000, parent_digest=b'\x29' * 32)
        except BaseException as error:
            self.result.update(error=repr(error), outcome_unknown=isinstance(error, OutcomeUnknown))
        finally:
            self.result['finished_at_host_ns'] = time.monotonic_ns()
            self.done.set()

    def finish(self):
        self.worker.join(6)
        require(not self.worker.is_alive(), 'proposal worker deadline exceeded')
        write_json('proposal-result.json', self.result)
        require(self.result['calls'] == 1, 'exactly one proposal invocation')
        return self.result


class RemoteLease:
    def __init__(self, campaign, manager_pid):
        self.campaign, self.manager_pid = campaign, manager_pid
        self.remote = '/var/tmp/actryn-contention-' + secrets.token_hex(8)
        self.sent = False
        self.process = None
        self.result = None

    def __enter__(self):
        helper = Path(__file__).with_name('sqlite_contention.py').read_text()
        command = 'python3 -c ' + shlex.quote(helper) + ' ' + ' '.join(map(shlex.quote,
            [str(self.manager_pid), self.campaign.args.manager_sha256, self.remote]))
        write_json('lease-intent.json', {'path': self.remote, 'lease_ns': LEASE_NS,
                   'manager_pid': self.manager_pid, 'mechanism': 'SQLite BEGIN EXCLUSIVE', 'retry': False})
        self.process = subprocess.Popen(self.campaign.ssh + [command], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline, data = time.monotonic() + 4, bytearray()
            while b'\n' not in data:
                remaining = deadline - time.monotonic()
                require(remaining > 0 and select.select([self.process.stdout], [], [], remaining)[0],
                        'lease readiness timeout')
                chunk = os.read(self.process.stdout.fileno(), 4096 - len(data))
                require(chunk and len(data) + len(chunk) < 4096, 'lease readiness frame')
                data.extend(chunk)
            require(data.count(b'\n') == 1 and data.endswith(b'\n'), 'lease already ended or malformed')
            ready = json.loads(data)
            write_json('lease-ready.json', ready)
            require(ready['phase'] == 'locked' and ready['helper_pidfd_pinned']
                    and ready['manager_pid'] == self.manager_pid
                    and ready['clock'] == 'CLOCK_BOOTTIME', 'lease identity/readiness')
            return self
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.process is None:
            return
        process, self.process = self.process, None
        try:
            self.sent = True
            stdout, stderr = process.communicate(b'release\n', timeout=6)
            write_json('lease-process.json', {'returncode': process.returncode, 'stdout': stdout[:65536].decode(errors='replace'),
                       'stderr': stderr[:65536].decode(errors='replace'), 'release_sends': 1, 'automatic_retry': False})
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=2)
            write_json('lease-process-unknown.json', {'stdout': stdout[:65536].decode(errors='replace'),
                       'stderr': stderr[:65536].decode(errors='replace'), 'automatic_retry': False})
            raise
        finally:
            # Read an immutable diagnostic; never start the helper again.
            try:
                self.result = json.loads(self.campaign.run('cat ' + shlex.quote(self.remote + '/contention.json')))
                write_json('lease-final.json', self.result)
            except BaseException as error:
                write_json('lease-release-unknown.json', {'error': repr(error), 'automatic_retry': False})
        require(process.returncode == 0 and self.result and self.result['released']
                and self.result['within_lease'] and 'error' not in self.result, 'lease failed or release unknown')

    def __exit__(self, *_):
        self.close()


class Campaign(BaseCampaign):
    def __init__(self, args):
        super().__init__(args)
        self.local_calls = 0

    def local(self, method, payload=None, *, label, closure=False):
        require(method in ('describe', 'recover', 'rearm', 'prepare', 'grant', 'activate', 'cancel', 'retire', 'revoke'),
                'failure campaign RPC allowlist')
        require(closure == (method in ('cancel', 'retire', 'revoke')), 'reserved closure routing')
        label = f'local-{self.local_calls:04}-{label}'
        self.local_calls += 1
        request = wire.Request(version=1, request_id=secrets.token_bytes(16), robot_epoch=self.epoch)
        getattr(request, method).CopyFrom(payload or wire.Empty())
        encoded = base64.b64encode(request.SerializeToString(deterministic=True)).decode()
        path = '/run/actryn-robot/' + ('closure.sock' if closure else 'operator.sock')
        write_json(label + '-intent.json', {'method': method, 'request_base64': encoded, 'automatic_retry': False})
        program = f'''import base64,socket,struct,sys
s=socket.socket(socket.AF_UNIX);s.settimeout(8);s.connect({path!r})
assert struct.unpack('3i',s.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))[1]==0
b=base64.b64decode({encoded!r});s.sendall(struct.pack('!I',len(b))+b)
f=s.makefile('rb');h=f.read(4);assert len(h)==4;n=struct.unpack('!I',h)[0];assert 0<n<=65536
b=f.read(n);assert len(b)==n;sys.stdout.buffer.write(b)
'''
        try:
            raw = self.run('python3 -c ' + shlex.quote(program))
            response = wire.Response.FromString(raw)
            response.DiscardUnknownFields()
            require(response.version == 1 and response.request_id == request.request_id
                    and len(response.robot_epoch) == 16 and (not self.epoch or response.robot_epoch == self.epoch)
                    and response.SerializeToString(deterministic=True) == raw, 'local response identity')
            require(response.WhichOneof('result') in ('failure', 'report'), 'local response result')
            if response.HasField('report'):
                result = json.loads(response.report.json)
                require(isinstance(result, dict), 'local report object')
        except BaseException as error:
            write_json(label + '-unknown.json', {'error': repr(error), 'mutation_outcome_unknown': method != 'describe',
                       'automatic_retry': False})
            raise
        self.epoch = response.robot_epoch
        if response.HasField('failure'):
            unknown = response.failure.code == wire.Failure.OUTCOME_UNKNOWN
            write_json(label + ('-unknown.json' if unknown else '-rejected.json'),
                       {'code': response.failure.code, 'message': response.failure.message,
                        'mutation_outcome_unknown': unknown and method != 'describe', 'automatic_retry': False})
            raise (OutcomeUnknown if unknown else RpcError)(response.failure.message)
        write_json(label + '-reply.json', result)
        return result

    def poll_read(self, label, call, predicate, timeout=8):
        deadline, index = time.monotonic() + timeout, 0
        while True:
            value = call()
            write_json(f'{label}-{index:03}.json', value)
            if predicate(value):
                return value
            require(time.monotonic() < deadline, {'poll': label, 'last': value})
            index += 1
            time.sleep(.02)

    def connection(self, port=None):
        a = self.args
        return Client('127.0.0.1', port=port or a.tcp_port, server_name=a.dns, ca=a.ca,
                      certificate=a.cert, key=a.key, paired_fingerprint=a.pin)

    def cancel_once(self, handle):
        require(not self.cancel_attempted, 'reserved cancellation is never retried')
        self.cancel_attempted = True
        self.cancel_at = time.monotonic_ns()
        try:
            return self.local('cancel', handle._wire(), label='reserved-cancel', closure=True)
        except BaseException as error:
            if isinstance(error, RpcError) and not isinstance(error, OutcomeUnknown):
                raise  # A definitive denial is a failed test, not a lost reply.
            # Unknown reply remains recorded. Only read-only checks follow this call.
            write_json('cancel-reply-unknown.json', {'error': repr(error), 'automatic_retry': False})
            return None

    def read_pre_send(self, sender, handle, label):
        description = sender.describe()
        write_json(label + '.json', {'host_monotonic_ns': time.monotonic_ns(), 'description': description,
                                    'proposal_sent': False})
        pre_send_ready(description, handle)

    def start_checked(self, sender, handle, call, arm=lambda: None):
        self.read_pre_send(sender, handle, 'immediate-pre-send')
        arm()
        call.start()

    def run_campaign(self):
        a = self.args
        self.cancel_attempted = False
        phase(a.mode + ' exact existing guest preflight')
        program = '''import hashlib,json,os,pathlib,subprocess
p=int(subprocess.check_output(['systemctl','show','--value','-p','MainPID','actryn-robotd']));assert p>1
print(json.dumps({'machine':os.uname().machine,'kernel':os.uname().release,'pid':p,
'compatible':pathlib.Path('/proc/device-tree/compatible').read_bytes().hex(),
'boot_id':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
'manager_sha256':hashlib.sha256(pathlib.Path(f'/proc/{p}/exe').read_bytes()).hexdigest(),
'module_note_sha256':hashlib.sha256(pathlib.Path('/sys/module/actryn_authority/notes/.note.gnu.build-id').read_bytes()).hexdigest()}))
'''
        actual = json.loads(self.run('python3 -c ' + shlex.quote(program)))
        write_json('guest-pins.json', actual)
        require(actual['machine'] == 'aarch64' and actual['kernel'] == '6.12.111+deb13-arm64'
                and bytes.fromhex(actual['compatible']).startswith(b'linux,dummy-virt\0')
                and actual['manager_sha256'] == a.manager_sha256
                and actual['module_note_sha256'] == a.module_note_sha256, 'guest pins mismatch')
        initial = self.local('describe', label='initial')
        no_effect(initial)
        require(initial['runtime']['prepared'] is None and not initial['live_actuation']
                and not initial['physical_acceptance'], 'requires idle inhibited software fixture')
        self.local('recover', label='initial-recover')
        self.poll('recovered', lambda d: d['runtime']['recovery_ready'] and d['runtime']['prepared'] is None
                  and not d['runtime']['recovery_pending'], 14)
        self.local('rearm', label='rearm')
        self.poll('ready', lambda d: d['runtime']['kernel']['state'] == 1)
        self.cli('pair', '--endpoint', f'127.0.0.1:{a.tcp_port}', '--dns', a.dns, '--pin', a.pin,
                 '--ca', a.ca, '--cert', a.cert, '--key', a.key, '--out', str(a.output / 'pair.json'))
        handle = self.create_handle(secrets.token_bytes(16), secrets.token_bytes(16))
        with self.connection() as authenticated:
            write_json('authenticated.json', authenticated.describe())
            prepared = self.local('prepare', wire.Prepare(attempt=handle.attempt, namespace=handle.namespace,
                                  principal=a.principal), label='prepare')
        self.poll('preparation-ready', lambda d: d['runtime']['preparation_ready'] and d['clock_healthy'])
        self.local('grant', wire.Grant(duration_ms=30000), label='grant')
        completed = False
        try:
            self.local('activate', label='activate')
            self.poll_read('active', lambda: self.local('describe', label='active-read'),
                           lambda d: d['runtime']['kernel']['state'] == 2)
            phase(a.mode + ' exactly one proposal and bounded fault')
            if a.mode == 'a02':
                operation, lease = self.lost_reply(handle), None
            else:
                operation, lease = self.contended_writer(handle, actual['pid'])
            with self.connection() as rpc:
                terminal = self.poll_read('durable-cancel', lambda: rpc.query(handle),
                    lambda v: durable_cancel(v['snapshot'], handle, operation))
                healthy = rpc.describe()
                write_json('pre-retirement.json', healthy)
                require(healthy['clock_healthy'] and healthy['runtime']['health']['healthy']
                        and healthy['runtime']['event_stream_healthy'], 'independent runtime fault')
                kernel = healthy['runtime']['kernel']
                require(same_operation(kernel, operation) and kernel['operation_state'] == 4
                        and kernel['reason'] == 2 and kernel['left_permille'] == kernel['right_permille'] == 0,
                        'cancelled kernel operation not reconciled')
            phase(a.mode + ' retire once, recover once and export retained capture')
            self.local('retire', label='retire', closure=True)
            self.poll_read('retired', lambda: self.local('describe', label='retired-read'),
                           lambda d: d['runtime']['retirement_ready'])
            self.local('recover', label='post-cancel-recover')
            self.poll('recovery-complete', lambda d: d['runtime']['prepared'] is None
                      and d['runtime']['recovery_ready'] and not d['runtime']['recovery_pending'], 14)
            credentials = ['--pair', str(a.output / 'pair.json'), '--cert', a.cert, '--key', a.key]
            self.cli('export', *credentials, '--handle', str(a.output / 'handle.json'),
                     '--out', str(a.output / 'evidence'), timeout=120)
            env = dict(os.environ, ACTRYN_TEST_CAPTURE=str(a.output / 'evidence/capture'),
                       ACTRYN_TEST_CAPTURE_REPORT=str(a.output / 'decoded.json'))
            reader = subprocess.run([str(a.reader), '--exact', 'decode_retired_campaign_capture', '--ignored',
                                     '--nocapture'], env=env, capture_output=True, timeout=30)
            write_json('reader-process.json', {'returncode': reader.returncode,
                'stdout': reader.stdout[:65536].decode(errors='replace'), 'stderr': reader.stderr[:65536].decode(errors='replace')})
            reader.check_returncode()
            decoded = json.loads((a.output / 'decoded.json').read_text())
            proof = validate_capture(decoded, handle, prepared, operation, a.mode, lease)
            write_json('result.json', {'status': 'PASS', 'test': a.mode, 'proof': proof,
                       'terminal': terminal, 'physical_acceptance': False, 'automatic_mutation_retries': 0,
                       'fsync_stall_tested': False, 'full_execution_replay': False})
            completed = True
        finally:
            if not completed:
                # A distinct urgent teardown, never a retry of failed proposal/cancel.
                try:
                    self.local('revoke', label='failure-cleanup-revoke', closure=True)
                except BaseException as error:
                    write_json('cleanup-unknown.json', {'error': repr(error), 'automatic_retry': False})

    def lost_reply(self, handle):
        with ReplyGate(self.args.tcp_port) as gate, self.connection(gate.port) as sender, self.connection() as observer:
            self.read_pre_send(sender, handle, 'gate-authenticated')
            observation = sender.observe(handle.attempt, handle.namespace)
            write_json('observation.json', observation)
            call = OneProposal(sender, handle, observation)
            write_json('proposal-intent.json', {'handle': handle.json(), 'observation': observation,
                       'target': [100, -100, 10000], 'parent_digest': '29' * 32, 'automatic_retry': False})
            self.start_checked(sender, handle, call, gate.arm)
            try:
                accepted = self.poll_read('independent-accepted', lambda: {'query': observer.query(handle),
                    'description': observer.describe(), 'gate': gate.report()}, lambda v:
                    v['query']['snapshot'] is not None and v['query']['snapshot']['operation'] is not None
                    and v['description']['runtime']['kernel']['operation_state'] == 2
                    and v['gate']['withheld_bytes'] > 0, 1.5)
                operation = operation_id(accepted['description']['runtime']['kernel'])
                require(accepted['query']['snapshot']['operation'] == operation and not call.done.is_set(),
                        'caller already received reply or allocation mismatch')
                self.cancel_once(handle)
                require(not call.done.is_set(), 'original caller finished before reserved cancellation returned')
                closed = self.poll_read('cancel-closed', observer.describe, lambda d:
                    same_operation(d['runtime']['kernel'], operation)
                    and d['runtime']['kernel']['operation_state'] in (3, 4)
                    and d['runtime']['kernel']['reason'] == 2, 1)
                write_json('closed-before-reply.json', {'description': closed,
                           'original_call_pending': not call.done.is_set(), 'cancel_at_host_ns': self.cancel_at})
                require(not call.done.is_set(), 'original caller completed before closure observation')
            finally:
                gate.close()
                result = call.finish()
                write_json('reply-gate.json', gate.report())
            require(result.get('outcome_unknown') is True and 'reply' not in result
                    and gate.report()['gated_downstream_forwarded'] == 0 and gate.report()['error'] is None,
                    'lost reply must remain unknown with no replay')
            return operation

    def contended_writer(self, handle, manager_pid):
        with self.connection() as sender, self.connection() as observer:
            self.read_pre_send(sender, handle, 'before-writer-contention')
            # Observe after lock acquisition to avoid spending freshness on SSH setup.
            with RemoteLease(self, manager_pid) as lease:
                observation = sender.observe(handle.attempt, handle.namespace)
                write_json('observation.json', observation)
                call = OneProposal(sender, handle, observation)
                write_json('proposal-intent.json', {'handle': handle.json(), 'observation': observation,
                           'target': [100, -100, 10000], 'parent_digest': '29' * 32, 'automatic_retry': False})
                self.start_checked(sender, handle, call)
                try:
                    allocated = self.poll_read('allocated-under-lock', lambda: {'query': observer.query(handle),
                        'description': observer.describe()}, lambda v: v['query']['snapshot'] is not None
                        and v['description']['runtime']['kernel']['operation_state'] == 6, .8)
                    snapshot = allocated['query']['snapshot']
                    operation = operation_id(allocated['description']['runtime']['kernel'])
                    require(snapshot['phase'] == 'PendingIntent' and snapshot['durable_revision'] == 0
                            and snapshot['operation'] is None and not snapshot['terminal'],
                            'operation must remain unacknowledged while SQLite writer is locked')
                    self.cancel_once(handle)
                    closed = self.poll_read('urgent-closure-under-lock', lambda: {'query': observer.query(handle),
                        'description': observer.describe()}, lambda v:
                        same_operation(v['description']['runtime']['kernel'], operation)
                        and v['description']['runtime']['kernel']['operation_state'] in (3, 4)
                        and v['description']['runtime']['kernel']['reason'] == 2, .8)
                    snapshot = closed['query']['snapshot']
                    require(not snapshot['cancellation_durable'] and snapshot['durable_revision'] == 0
                            and snapshot['operation'] is None and snapshot['terminal'],
                            'urgent closure must precede durable tombstone while writer blocked')
                finally:
                    # Release once before joining any ordinary proposal reply.
                    lease.close()
                    result = call.finish()
                    require('reply' in result or result.get('outcome_unknown'), 'proposal rejected')
            return operation, lease.result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['a02', 'a09'], required=True)
    parser.add_argument('--ssh-port', type=int, default=26221)
    parser.add_argument('--tcp-port', type=int, default=27443)
    for name in ('ssh-key', 'known-hosts', 'ca', 'cert', 'key', 'principal', 'dns', 'pin',
                 'manager-sha256', 'module-note-sha256'):
        parser.add_argument('--' + name, required=True)
    for name in ('output', 'cli', 'reader'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    require(re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', args.principal), 'principal')
    for value in (args.pin, args.manager_sha256, args.module_note_sha256):
        require(re.fullmatch('[0-9a-f]{64}', value), 'SHA256 pin')
    os.umask(0o077)
    args.output.mkdir(parents=True, exist_ok=False)
    args.output = args.output.resolve()
    CAMPAIGN['output'] = args.output
    write_json('campaign.json', {'mode': args.mode, 'source_revision': subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'source_pins': {str(p.relative_to(ROOT)): sha(p) for p in (
            Path(__file__), Path(__file__).with_name('reply_gate.py'), Path(__file__).with_name('sqlite_contention.py'),
            Path(__file__).with_name('failure_capture.rs'), ROOT / 'kernel/include/uapi/linux/actryn_authority.h',
            ROOT / 'kernel/actryn_driver.c', ROOT / 'crates/robot-runtime/src/lib.rs')},
        'cli_sha256': sha(args.cli), 'reader_sha256': sha(args.reader), 'principal': args.principal,
        'manager_sha256': args.manager_sha256, 'module_note_sha256': args.module_note_sha256,
        'physical_acceptance': False, 'automatic_mutation_retries': 0})
    try:
        Campaign(args).run_campaign()
    except BaseException as error:
        write_json('failure.json', {'phase': CAMPAIGN['phase'], 'error': repr(error), 'automatic_retry': False})
        raise
    finally:
        write_json('artifact-hashes.json', {str(p.relative_to(args.output)): sha(p)
                   for p in sorted(args.output.rglob('*')) if p.is_file() and p.name != 'artifact-hashes.json'})


if __name__ == '__main__':
    main()
