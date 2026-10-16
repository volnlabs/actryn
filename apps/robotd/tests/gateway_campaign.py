"""Shared existing-guest preflight/export for the two independently opt-in A10 tests."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import time

from failure_paths import Campaign as FailureCampaign, operation_id, same_operation
from guest import CAMPAIGN, ROOT, RequestHandle, phase, wire, write_json
from source_gap import no_effect, require, sha
from ssh_campaign import SharedSsh


def acknowledged_running(handle, result, query, description):
    require(result.get('calls') == 1 and result.get('automatic_retries') == 0
            and 'reply' in result and not result.get('outcome_unknown'), 'proposal reply not acknowledged')
    reply, snapshot = result['reply'], query['snapshot']
    require(query['live_authority'] and snapshot is not None, 'original handle unavailable')
    for value in (reply, snapshot):
        require(value['namespace'] == list(handle.namespace) and value['key'] == list(handle.key)
                and value['phase'] in ('PendingIntent', 'IntentDurable', 'Submitted')
                and value['revision'] > 0 and not value['terminal']
                and not value['persistence_failed'] and not value['cancellation_durable'],
                'proposal identity changed or became terminal/unknown')
    runtime = description['runtime']
    require(description['clock_healthy'] and runtime['health']['healthy'] and runtime['event_stream_healthy']
            and runtime['prepared'] is not None
            and runtime['prepared']['binding']['attempt'] == list(handle.attempt)
            and runtime['prepared']['binding']['namespace'] == list(handle.namespace), 'proposal binding/health changed')
    kernel = runtime['kernel']
    require(kernel['state'] == 2 and kernel['flags'] & 8, 'proposal authority closed')
    if snapshot['operation'] is None or kernel['operation_state'] != 2:
        return None
    operation = operation_id(kernel)
    require(snapshot['operation'] == operation
            and (reply['operation'] is None or reply['operation'] == operation), 'acknowledged/running identity mismatch')
    return operation


def execution_counts(records, handle, operation):
    """Runtime Execution is either an accepted proposal tuple or a successful SAMPLE ioctl."""
    def byte_array(value, length):
        return (isinstance(value, list) and len(value) == length
                and all(type(v) is int and 0 <= v <= 255 for v in value))

    proposals, samples = 0, 0
    zero_fields = ('flags', 'role', 'instance', 'transaction', 'acquired_earliest_ns',
                   'acquired_latest_ns', 'valid_until_ns', 'reason', 'reserved0')
    positive_fields = ('grant', 'operation', 'stream', 'sequence', 'deadline_ns', 'observation')
    fields = set(zero_fields + positive_fields + ('version', 'opcode', 'runtime_nonce',
                 'context_revision', 'left_permille', 'right_permille', 'digest', 'reserved'))
    for record in records:
        if record['origin'] != 'Runtime' or record['kind'] != 'Execution':
            continue
        value = record['value']
        if isinstance(value, list):
            require(len(value) == 4 and value[0] == list(handle.key)
                    and byte_array(value[0], 32) and byte_array(value[1], 32)
                    and isinstance(value[2], dict)
                    and set(value[2]) == {'left_ticks', 'right_ticks', 'duration_ms'}
                    and all(type(v) is int for v in value[2].values())
                    and abs(value[2]['left_ticks']) <= 100 and abs(value[2]['right_ticks']) <= 100
                    and 0 < value[2]['duration_ms'] <= 10000
                    and type(value[3]) is int and 0 < value[3] < 2**64,
                    'unrecognized accepted proposal execution')
            proposals += 1
            require(proposals == 1, 'exactly one accepted proposal in whole capture')
        else:
            # SAMPLE does not carry device/boot/session/instance: its canonical
            # identity is nonce/grant/operation/stream; instance must remain zero.
            require(isinstance(value, dict) and set(value) == fields,
                    'unrecognized runtime execution record')
            require(all(type(value[k]) is int and value[k] == 0 for k in zero_fields)
                    and all(type(value[k]) is int and 0 < value[k] < 2**64 for k in positive_fields)
                    and type(value['version']) is int and value['version'] == 1
                    and type(value['opcode']) is int and value['opcode'] == 8
                    and type(value['context_revision']) is int and value['context_revision'] == 1
                    and all(type(value[k]) is int and -200 <= value[k] <= 200
                            for k in ('left_permille', 'right_permille'))
                    and byte_array(value['runtime_nonce'], 16) and byte_array(value['digest'], 32)
                    and byte_array(value['reserved'], 16) and value['reserved'] == [0] * 16,
                    'noncanonical SAMPLE execution')
            require(proposals == 1 and all(value[k] == operation[k] for k in
                    ('runtime_nonce', 'grant', 'operation', 'stream'))
                    and value['sequence'] == samples + 1, 'SAMPLE execution identity/order changed')
            samples += 1
    require(proposals == 1, 'exactly one accepted proposal in whole capture')
    return proposals, samples


def validate_gateway_capture(decoded, handle, prepared, operation, mode, interval):
    require(mode in ('traffic', 'lifetime') and interval['started_ns'] < interval['finished_ns'], 'fault interval')
    require(decoded['format'] == 'actryn-failure-capture-1' and decoded['attempt'] == list(handle.attempt)
            and decoded['configuration_digest'] == prepared['configuration_digest']
            and decoded['policy'] == 'MetadataOnly' and not decoded['issues'] and not decoded['raw_remnants'],
            'capture binding/policy/recovery issues')
    require(decoded['volatile_tail_unknown'] and not decoded['execution_replay_eligible'], 'replay boundary')
    require(len(decoded['frontiers']) == len(decoded['sources']) == 2, 'producer count')
    for source, frontier in zip(decoded['sources'], decoded['frontiers']):
        require(not source['missing_record_ordinals'] and not source['source_gap_record_ordinals']
                and frontier['gap_count'] == 0 and frontier['read'] == frontier['durable']
                and source['last_record_ordinal'] == source['durable_frontier'], 'incomplete capture prefix')
    records = decoded['records']
    require(not any(r['kind'] == 'SourceGap' for r in records), 'independent source fault')
    events = [r['value'] for r in records if r['origin'] == 'Kernel' and r['kind'] == 'Transition']
    require(events and all(b['sequence'] == a['sequence'] + 1 for a, b in zip(events, events[1:]))
            and len({e['status']['events_lost'] for e in events}) == 1, 'external source discontinuity')
    allocations = [e for e in events if e['kind'] == 0x1000e]
    require(len(allocations) == 1 and allocations[0]['status']['operation_state'] == 6
            and operation_id(allocations[0]['status']) == operation, 'exactly one allocation in whole capture')
    proposals, samples = execution_counts(records, handle, operation)
    matching = [e for e in events if same_operation(e['status'], operation)]
    starts = [e for e in matching if e['kind'] == 0x10007]
    reason = 2 if mode == 'traffic' else 3
    closures = [e for e in matching if e['kind'] == (0x30000 | reason) and e['status']['reason'] == reason]
    require(len(starts) == 1 and closures and starts[0]['sequence'] < closures[0]['sequence']
            and interval['started_ns'] <= closures[0]['captured_ns'] <= interval['finished_ns']
            and any(e['status']['operation_state'] == 4 for e in matching),
            'missing START, fault-specific closure inside interval, or reconciliation')
    return {'allocation_sequence': allocations[0]['sequence'], 'start_sequence': starts[0]['sequence'],
            'closure_sequence': closures[0]['sequence'], 'reason': reason, 'operation': operation,
            'accepted_proposal_count': proposals, 'sample_request_count': samples,
            'kernel_clock': 'CLOCK_BOOTTIME', 'volatile_tail_unknown': True, 'full_execution_replay': False}


class GatewayCampaign(FailureCampaign):
    def confirm_running(self, rpc, result):
        deadline, original_timeout, index = time.monotonic() + 1, rpc._timeout, 0
        try:
            while True:
                remaining = deadline - time.monotonic()
                require(remaining > 0, 'original proposal confirmation deadline; no resend')
                rpc._timeout = min(original_timeout, remaining)
                query = rpc.query(self.handle)
                remaining = deadline - time.monotonic()
                require(remaining > 0, 'original proposal confirmation deadline; no resend')
                rpc._timeout = min(original_timeout, remaining)
                description = rpc.describe()
                write_json(f'confirmed-running-{index:03}.json', {'query': query, 'description': description})
                require(time.monotonic() < deadline, 'original proposal confirmation deadline; no resend')
                operation = acknowledged_running(self.handle, result, query, description)
                if operation is not None:
                    return operation
                index += 1
                time.sleep(.01)
        finally:
            rpc._timeout = original_timeout

    def setup(self, preflight=lambda *_: None):
        a = self.args
        self.cancel_attempted = False
        phase('A10 ' + a.mode + ' inhibited guest preflight')
        program = '''import hashlib,json,os,pathlib,subprocess
def pid(unit):
 p=int(subprocess.check_output(['systemctl','show','--value','-p','MainPID',unit]));assert p>1;return p
m,g=pid('actryn-robotd'),pid('actryn-gatewayd')
def digest(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
print(json.dumps({'machine':os.uname().machine,'kernel':os.uname().release,'manager_pid':m,'gateway_pid':g,
'compatible':pathlib.Path('/proc/device-tree/compatible').read_bytes().hex(),
'boot_id':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
'manager_sha256':digest(f'/proc/{m}/exe'),'gateway_sha256':digest(f'/proc/{g}/exe'),
'gateway_uid':pathlib.Path(f'/proc/{g}').stat().st_uid,
'gateway_unit':subprocess.check_output(['systemctl','cat','actryn-gatewayd.service']).decode(),
'module_note_sha256':digest('/sys/module/actryn_authority/notes/.note.gnu.build-id')}))
'''
        self.pins = json.loads(self.run('python3 -c ' + shlex.quote(program)))
        write_json('guest-pins.json', self.pins)
        require(self.pins['machine'] == 'aarch64' and self.pins['kernel'] == '6.12.111+deb13-arm64'
                and bytes.fromhex(self.pins['compatible']).startswith(b'linux,dummy-virt\0')
                and self.pins['manager_sha256'] == a.manager_sha256
                and self.pins['gateway_sha256'] == a.gateway_sha256 and self.pins['gateway_uid'] != 0
                and self.pins['module_note_sha256'] == a.module_note_sha256, 'guest pins mismatch')
        initial = self.local('describe', label='initial')
        no_effect(initial)
        require(initial['runtime']['prepared'] is None and not initial['live_actuation']
                and not initial['physical_acceptance'], 'requires idle inhibited software fixture')
        preflight(self, initial)  # Lifetime FD permission check precedes every authority mutation.
        self.local('recover', label='initial-recover')
        self.poll('recovered', lambda d: d['runtime']['recovery_ready'] and d['runtime']['prepared'] is None
                  and not d['runtime']['recovery_pending'], 14)
        self.local('rearm', label='rearm')
        self.poll('ready', lambda d: d['runtime']['kernel']['state'] == 1)
        self.cli('pair', '--endpoint', f'127.0.0.1:{a.tcp_port}', '--dns', a.dns, '--pin', a.pin,
                 '--ca', a.ca, '--cert', a.cert, '--key', a.key, '--out', str(a.output / 'pair.json'))
        self.handle = self.create_handle(secrets.token_bytes(16), secrets.token_bytes(16))
        with self.connection() as rpc:
            write_json('authenticated.json', rpc.describe())
            self.prepared = self.local('prepare', wire.Prepare(attempt=self.handle.attempt,
                namespace=self.handle.namespace, principal=a.principal), label='prepare')
        self.poll('preparation-ready', lambda d: d['runtime']['preparation_ready'] and d['clock_healthy'])

    def save_other_handle(self, name):
        require(name in ('delayed', 'denied'), 'fixed test handle filename')
        path = self.args.output / (name + '-handle.json')
        result = self.cli('handle', '--pair', str(self.args.output / 'pair.json'), '--attempt',
            self.handle.attempt.hex(), '--namespace', self.handle.namespace.hex(), '--out', str(path))
        saved = json.loads(path.read_text())
        require(result['handle'] == saved and result['authority_issued'] is False and saved['state'] == 'ready'
                and saved['robot_epoch'] == self.epoch.hex() and saved['proposal'] is None
                and saved['attempt'] == self.handle.attempt.hex() and saved['namespace'] == self.handle.namespace.hex(),
                'production saved handle mismatch')
        return RequestHandle(*(bytes.fromhex(saved[k]) for k in ('attempt', 'namespace', 'key')))

    def activate(self):
        self.local('grant', wire.Grant(duration_ms=30000), label='grant')
        self.local('activate', label='activate')
        return self.poll_read('active', lambda: self.local('describe', label='active-read'),
                              lambda d: d['runtime']['kernel']['state'] == 2)

    def retire_recover(self):
        self.local('retire', label='retire', closure=True)
        self.poll_read('retired', lambda: self.local('describe', label='retired-read'),
                       lambda d: d['runtime']['retirement_ready'])
        self.local('recover', label='post-fault-recover')
        return self.poll('recovery-complete', lambda d: d['runtime']['prepared'] is None
            and d['runtime']['recovery_ready'] and not d['runtime']['recovery_pending'], 14)

    def export(self, operation, interval):
        a = self.args
        self.cli('export', '--pair', str(a.output / 'pair.json'), '--cert', a.cert, '--key', a.key,
                 '--handle', str(a.output / 'handle.json'), '--out', str(a.output / 'evidence'), timeout=120)
        env = dict(os.environ, ACTRYN_TEST_CAPTURE=str(a.output / 'evidence/capture'),
                   ACTRYN_TEST_CAPTURE_REPORT=str(a.output / 'decoded.json'))
        reader = subprocess.run([str(a.reader), '--exact', 'decode_retired_campaign_capture', '--ignored',
                                 '--nocapture'], env=env, capture_output=True, timeout=30)
        write_json('reader-process.json', {'returncode': reader.returncode,
            'stdout': reader.stdout[:65536].decode(errors='replace'), 'stderr': reader.stderr[:65536].decode(errors='replace')})
        reader.check_returncode()
        proof = validate_gateway_capture(json.loads((a.output / 'decoded.json').read_text()), self.handle,
                                         self.prepared, operation, a.mode, interval)
        write_json('result.json', {'status': 'PASS', 'test': 'A10-' + a.mode, 'proof': proof,
            'physical_acceptance': False, 'automatic_mutation_retries': 0, 'full_execution_replay': False})


def main(mode, campaign_type):
    parser = argparse.ArgumentParser(description='Opt-in A10 ' + mode + '; exact disposable guest only')
    parser.add_argument('--ssh-port', type=int, default=26221)
    parser.add_argument('--tcp-port', type=int, default=27443)
    for name in ('ssh-key', 'known-hosts', 'ca', 'cert', 'key', 'principal', 'dns', 'pin',
                 'manager-sha256', 'gateway-sha256', 'module-note-sha256'):
        parser.add_argument('--' + name, required=True)
    for name in ('output', 'cli', 'reader'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    args.mode = mode
    require(re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', args.principal), 'principal')
    for value in (args.pin, args.manager_sha256, args.gateway_sha256, args.module_note_sha256):
        require(re.fullmatch('[0-9a-f]{64}', value), 'SHA256 pin')
    os.umask(0o077)
    args.output.mkdir(parents=True, exist_ok=False)
    args.output = args.output.resolve()
    CAMPAIGN['output'] = args.output
    sources = list(Path(__file__).parent.glob('gateway*.py')) + [Path(__file__).with_name(n) for n in
        ('failure_paths.py', 'source_gap.py', 'ssh_campaign.py', 'failure_capture.rs')]
    sources += [ROOT / n for n in ('apps/robotd/src/service.rs', 'apps/gateway/src/main.rs',
        'crates/robot-rpc/src/transport.rs', 'sdk/python/actryn/client.py', 'schemas/robot-v1.proto',
        'kernel/include/uapi/linux/actryn_authority.h', 'kernel/actryn_driver.c')]
    write_json('campaign.json', {'mode': mode, 'source_revision': subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'source_pins': {str(p.relative_to(ROOT)): sha(p) for p in sources},
        'cli_sha256': sha(args.cli), 'reader_sha256': sha(args.reader), 'principal': args.principal,
        'physical_acceptance': False, 'automatic_mutation_retries': 0})
    try:
        campaign = campaign_type(args)
        with SharedSsh(campaign.ssh, args.output) as ssh:
            campaign.ssh = ssh.command
            campaign.run_campaign()
    except BaseException as error:
        write_json('failure.json', {'phase': CAMPAIGN['phase'], 'error': repr(error), 'automatic_retry': False})
        raise
    finally:
        write_json('artifact-hashes.json', {str(p.relative_to(args.output)): sha(p)
            for p in sorted(args.output.rglob('*')) if p.is_file() and p.name != 'artifact-hashes.json'})
