#!/usr/bin/env python3
"""Opt-in A11 production source omission; no grant, activation or physical outputs."""
import argparse
import base64
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

from guest import CAMPAIGN, ROOT, Client, RequestHandle, phase, wire, write_json
from omit_kernel_event import decode_event, no_authority, require, PAUSE_LIMIT_NS


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def no_effect(description):
    kernel = description['runtime']['kernel']
    require(kernel['grant'] == 0 and kernel['operation'] == 0 and kernel['operation_state'] == 0
            and kernel['flags'] & 8 == 0 and kernel['left_permille'] == kernel['right_permille'] == 0,
            'unexpected authority, operation or nonzero output')


def validate_capture(decoded, omitted, attempt, baseline):
    require(decoded['attempt'] == list(attempt) and decoded['policy'] == 'MetadataOnly', 'capture binding/policy')
    require(not decoded['issues'] and not decoded['raw_remnants'], 'unsupported checkpoint/raw remnants')
    require(decoded['volatile_tail_unknown'] is True and decoded['execution_replay_eligible'] is False
            and 'retained external source fault' in decoded['replay_missing'], 'replay eligibility missing fault')
    require(len(decoded['source_faults']) == 1, 'expected exactly one durable source fault')
    record = decoded['source_faults'][0]
    metadata = record['metadata_value']
    fault, observed = metadata['fault'], metadata['event']
    stolen = omitted['event']
    require(record['producer'] == 1 and record['origin'] == 'Kernel' and record['metadata'] is True,
            'fault provenance')
    require(fault['source'] == 'kernel.event' and fault['epoch'] == stolen['status']['runtime_nonce']
            and observed['status']['runtime_nonce'] == fault['epoch'], 'external source epoch')
    require(fault['previous_sequence'] + 1 == stolen['sequence']
            and stolen['sequence'] + 1 == fault['observed_sequence'] == observed['sequence']
            and fault['sequence_discontinuity'] is True, 'exact one-event external sequence omission')
    require(fault['loss_baseline'] == fault['observed_loss'] == observed['status']['events_lost']
            == stolen['status']['events_lost'] == baseline and fault['loss_counter_changed'] is False,
            'omission must not be mislabeled FIFO loss')
    require(record['source_time_ns'] == observed['captured_ns'], 'fault source timestamp')
    no_authority(stolen['status'])
    no_authority(observed['status'])
    previous = record['previous_kernel_record']
    require(previous is not None and previous['metadata_value']['sequence'] == fault['previous_sequence']
            and previous['record_ordinal'] + 1 == record['record_ordinal'],
            'external kernel gap must be distinct from contiguous recorder ordinals')
    source = decoded['sources'][1]
    require(source['producer'] == 1 and source['missing_record_ordinals'] == []
            and source['source_gap_record_ordinals'] == [record['record_ordinal']]
            and source['durable_frontier'] >= record['record_ordinal']
            and decoded['frontiers'][1]['gap_count'] == 1, 'durable per-source gap frontier')
    return record


class Campaign:
    def __init__(self, args):
        self.args, self.epoch = args, b''
        self.cli_calls = 0
        self.ssh = ['ssh', '-i', args.ssh_key, '-p', str(args.ssh_port), '-o', 'BatchMode=yes',
                    '-o', 'ConnectTimeout=5', '-o', 'UserKnownHostsFile=' + args.known_hosts,
                    'root@127.0.0.1']

    def run(self, command, timeout=30):
        return subprocess.run(self.ssh + [command], check=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=timeout).stdout

    def local(self, method, payload=None, *, label, closure=False):
        require(method in ('describe', 'recover', 'rearm', 'prepare', 'retire'), 'campaign RPC allowlist')
        request = wire.Request(version=1, request_id=secrets.token_bytes(16), robot_epoch=self.epoch)
        getattr(request, method).CopyFrom(payload or wire.Empty())
        encoded = base64.b64encode(request.SerializeToString(deterministic=True)).decode()
        path = '/run/actryn-robot/' + ('closure.sock' if closure else 'operator.sock')
        write_json(label + '-intent.json', {'method': method, 'request_id': request.request_id.hex(),
                   'robot_epoch': self.epoch.hex(), 'request_base64': encoded, 'retry': False})
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
                    and len(response.robot_epoch) == 16
                    and (not self.epoch or response.robot_epoch == self.epoch)
                    and response.SerializeToString(deterministic=True) == raw, 'local reply identity/encoding')
            require(response.WhichOneof('result') in ('failure', 'report'), 'local reply result')
            if response.HasField('report'):
                value = json.loads(response.report.json)
                require(isinstance(value, dict), 'local report must be an object')
        except BaseException as error:
            write_json(label + '-unknown.json', {'method': method, 'error': repr(error),
                       'mutation_outcome_unknown': method != 'describe', 'automatic_retry': False})
            raise
        self.epoch = response.robot_epoch
        if response.HasField('failure'):
            unknown = response.failure.code == wire.Failure.OUTCOME_UNKNOWN
            write_json(label + ('-unknown.json' if unknown else '-rejected.json'),
                       {'code': response.failure.code, 'message': response.failure.message,
                        'mutation_outcome_unknown': unknown and method != 'describe', 'automatic_retry': False})
            raise RuntimeError(response.failure.message)
        write_json(label + '-reply.json', value)
        return value

    def poll(self, label, predicate, timeout=10):
        deadline, index = time.monotonic() + timeout, 0
        while True:
            value = self.local('describe', label=f'{label}-{index:03}')
            no_effect(value)
            if predicate(value):
                return value
            require(time.monotonic() < deadline, {'poll': label, 'last': value})
            index += 1
            time.sleep(.05)

    def cli(self, *arguments, timeout=30):
        label = f'cli-{self.cli_calls:03}-{arguments[0]}.json'
        self.cli_calls += 1
        command = [str(self.args.cli), 'robot', *arguments]
        try:
            result = subprocess.run(command, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            write_json(label, {'returncode': None, 'timeout': True, 'automatic_retry': False,
                       'stdout': (error.stdout or b'')[:65536].decode(errors='replace'),
                       'stderr': (error.stderr or b'')[:65536].decode(errors='replace')})
            raise
        write_json(label, {'returncode': result.returncode, 'automatic_retry': False,
                   'stdout': result.stdout[:65536].decode(errors='replace'),
                   'stderr': result.stderr[:65536].decode(errors='replace'),
                   'stdout_bytes': len(result.stdout), 'stderr_bytes': len(result.stderr)})
        result.check_returncode()
        return json.loads(result.stdout)

    def create_handle(self, attempt, namespace):
        path = self.args.output / 'handle.json'
        result = self.cli('handle', '--pair', str(self.args.output / 'pair.json'),
                          '--attempt', attempt.hex(), '--namespace', namespace.hex(), '--out', str(path))
        saved = json.loads(path.read_text())
        require(result['result'] == 'handle_saved' and result['authority_issued'] is False
                and result['handle'] == saved and saved['robot_epoch'] == self.epoch.hex()
                and saved['state'] == 'ready' and saved['proposal'] is None
                and saved['attempt'] == attempt.hex() and saved['namespace'] == namespace.hex(),
                'production CLI handle mismatch')
        return RequestHandle(*(bytes.fromhex(saved[name]) for name in ('attempt', 'namespace', 'key')))

    def run_campaign(self):
        args = self.args
        phase('A11 existing guest and binary preflight')
        program = '''import hashlib,json,os,pathlib,subprocess
p=int(subprocess.check_output(['systemctl','show','--value','-p','MainPID','actryn-robotd']))
assert p>1
print(json.dumps({'machine':os.uname().machine,'kernel':os.uname().release,
'compatible':pathlib.Path('/proc/device-tree/compatible').read_bytes().hex(),'pid':p,
'manager_sha256':hashlib.sha256(pathlib.Path(f'/proc/{p}/exe').read_bytes()).hexdigest(),
'module_note_sha256':hashlib.sha256(pathlib.Path('/sys/module/actryn_authority/notes/.note.gnu.build-id').read_bytes()).hexdigest()}))
'''
        actual = json.loads(self.run('python3 -c ' + shlex.quote(program)))
        write_json('guest-pins.json', actual)
        require(actual['machine'] == 'aarch64' and actual['kernel'] == '6.12.111+deb13-arm64'
                and bytes.fromhex(actual['compatible']).startswith(b'linux,dummy-virt\0')
                and actual['manager_sha256'] == args.manager_sha256
                and actual['module_note_sha256'] == args.module_note_sha256, 'guest tuple mismatch')
        initial = self.local('describe', label='initial')
        no_effect(initial)
        require(initial['runtime']['prepared'] is None and not initial['live_actuation']
                and not initial['physical_acceptance'], 'campaign requires no previous preparation')
        phase('A11 explicit recovery and rearm without grant')
        self.local('recover', label='initial-recover')
        self.poll('recovered', lambda d: d['runtime']['recovery_ready']
                  and d['runtime']['prepared'] is None and not d['runtime']['recovery_pending'], 14)
        self.local('rearm', label='rearm')
        self.poll('ready', lambda d: d['runtime']['kernel']['state'] == 1)
        credentials = ['--pair', str(args.output / 'pair.json'), '--cert', args.cert, '--key', args.key]
        write_json('pair-report.json', self.cli('pair', '--endpoint', f'127.0.0.1:{args.tcp_port}',
                   '--dns', args.dns, '--pin', args.pin, '--ca', args.ca, '--cert', args.cert,
                   '--key', args.key, '--out', str(args.output / 'pair.json')))
        attempt, namespace = secrets.token_bytes(16), secrets.token_bytes(16)
        handle = self.create_handle(attempt, namespace)
        with Client('127.0.0.1', port=args.tcp_port, server_name=args.dns, ca=args.ca,
                    certificate=args.cert, key=args.key, paired_fingerprint=args.pin) as rpc:
            write_json('authenticated.json', rpc.describe())
            prepared = self.local('prepare', wire.Prepare(attempt=attempt, namespace=namespace,
                                  principal=args.principal), label='prepare')
            require(prepared['binding']['attempt'] == list(attempt)
                    and prepared['binding']['namespace'] == list(namespace), 'preparation binding mismatch')
            before = self.poll('capture-ready', lambda d: d['runtime']['preparation_ready']
                and d['clock_healthy'] and len(d['runtime']['health']['frontiers']) == 2
                and d['runtime']['health']['frontiers'][1]['durable'] >= 1)
            baseline = before['runtime']['event_loss_baseline']
            require(before['runtime']['health']['healthy']
                    and before['runtime']['kernel']['events_lost'] == baseline, 'unhealthy source baseline')
            write_json('pre-pause.json', before)
            phase('A11 omit exactly one real kernel event under bounded SIGSTOP')
            remote = '/var/tmp/actryn-a11-' + secrets.token_hex(8)
            write_json('omission-intent.json', {'remote_output': remote, 'pid': actual['pid'],
                       'pause_limit_ns': PAUSE_LIMIT_NS, 'read_count': 1, 'automatic_retry': False})
            helper = Path(__file__).with_name('omit_kernel_event.py').read_text()
            command = 'python3 -c ' + shlex.quote(helper) + ' ' + ' '.join(map(shlex.quote,
                      [str(actual['pid']), args.manager_sha256, remote]))
            helper_error = None
            try:
                raw = self.run(command, timeout=8)
                (args.output / 'omission-stdout.json').write_bytes(raw)
            except BaseException as error:
                helper_error = repr(error)
                write_json('omission-unknown.json', {'error': helper_error, 'automatic_retry': False})
            # Reading the same retained artifact never repeats the consuming action.
            omitted = json.loads(self.run('cat ' + shlex.quote(remote + '/omission.json')))
            write_json('omission.json', omitted)
            require(omitted['resumed'], 'manager resume unconfirmed; no further campaign mutations')
            errors = []
            if helper_error:
                errors.append({'omission_transport': helper_error})
            def check(label, action):
                try:
                    return action()
                except BaseException as error:
                    errors.append({'check': label, 'error': repr(error)})
                    write_json('checks-failed.json', errors)
                    return None
            def validate_omission():
                require('error' not in omitted and omitted['stopped_duration_ns'] <= PAUSE_LIMIT_NS,
                        'omission failed or exceeded pause bound')
                raw = bytes.fromhex(omitted['event_hex'])
                require(sha_bytes(raw) == omitted['event_sha256'] and decode_event(raw) == omitted['event'],
                        'stolen raw event mismatch')
                require(omitted['event']['kind'] == 0x2000c, 'expected actual observation event')
                require(omitted['event']['status']['runtime_nonce'] == prepared['runtime_epoch'],
                        'stolen event must belong to the prepared runtime epoch')
                no_authority(omitted['event']['status'])
                (args.output / 'stolen-event.bin').write_bytes(raw)
            check('omission', validate_omission)
            closed = check('source gap closure', lambda: self.poll('gap-closed', lambda d:
                not d['runtime']['event_stream_healthy'] and d['runtime']['health']['inhibited']
                and 'SourceGap' in d['runtime']['health']['evidence_issues']))
            if closed:
                check('no independent clock/pending-age fault', lambda: require(closed['clock_healthy']
                      and 'PendingAge' not in closed['runtime']['health']['evidence_issues'], 'independent fault'))
            phase('A11 retire once, recover once and export retained capture')
            check('retire reply', lambda: self.local('retire', label='retire', closure=True))
            retired = self.poll('retired', lambda d: d['runtime']['retirement_ready'])
            write_json('retired.json', retired)
            check('recover reply', lambda: self.local('recover', label='post-gap-recover'))
            self.poll('post-gap-recovered', lambda d: d['runtime']['prepared'] is None
                      and d['runtime']['recovery_ready'] and not d['runtime']['recovery_pending'], 14)
        write_json('export-report.json', self.cli('export', *credentials, '--handle',
                   str(args.output / 'handle.json'), '--out', str(args.output / 'evidence'), timeout=120))
        decoded = json.loads(subprocess.check_output([str(args.reader), str(args.output / 'evidence/capture')], timeout=30))
        write_json('decoded.json', decoded)
        check('capture configuration', lambda: require(decoded['configuration_digest']
              == prepared['configuration_digest'], 'capture configuration mismatch'))
        check('durable raw source gap', lambda: validate_capture(decoded, omitted, attempt, baseline))
        write_json('result.json', {'status': 'FAIL' if errors else 'PASS', 'test': 'A11-production-source-omission',
                   'attempt': attempt.hex(), 'namespace': namespace.hex(), 'errors': errors,
                   'grant_issued': False, 'activated': False, 'physical_acceptance': False,
                   'fifo_overflow_tested': False, 'automatic_mutation_retries': 0})
        require(not errors, errors)


def sha_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ssh-port', type=int, default=26221)
    parser.add_argument('--tcp-port', type=int, default=27443)
    for name in ('ssh-key', 'known-hosts', 'ca', 'cert', 'key', 'principal', 'dns', 'pin',
                 'manager-sha256', 'module-note-sha256'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cli', type=Path, required=True)
    parser.add_argument('--reader', type=Path, required=True)
    args = parser.parse_args()
    require(re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', args.principal), 'principal')
    for value in (args.pin, args.manager_sha256, args.module_note_sha256):
        require(re.fullmatch('[0-9a-f]{64}', value), 'SHA256 pin')
    os.umask(0o077)
    args.output.mkdir(parents=True, exist_ok=False)
    CAMPAIGN['output'] = args.output
    write_json('campaign.json', {'source_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
               'source_pins':{str(p):sha(ROOT/p) for p in [Path('kernel/actryn_driver.c'),
                  Path('apps/controller-fixture/src/main.rs'), Path('crates/robot-runtime/src/events.rs'),
                  Path('apps/robotd/tests/omit_kernel_event.py'), Path('apps/robotd/tests/source_gap.py')]},
               'cli_sha256':sha(args.cli), 'reader_sha256':sha(args.reader),
               'manager_sha256':args.manager_sha256, 'module_note_sha256':args.module_note_sha256,
               'principal':args.principal, 'pause_limit_ns':PAUSE_LIMIT_NS,
               'grant_issued':False, 'activated':False, 'physical_acceptance':False})
    try:
        Campaign(args).run_campaign()
    except BaseException as error:
        write_json('failure.json', {'phase':CAMPAIGN['phase'], 'error':repr(error), 'automatic_retry':False})
        raise
    finally:
        write_json('artifact-hashes.json', {str(p.relative_to(args.output)):sha(p)
                   for p in sorted(args.output.rglob('*')) if p.is_file()
                   and p.name != 'artifact-hashes.json'})


if __name__ == '__main__':
    main()
