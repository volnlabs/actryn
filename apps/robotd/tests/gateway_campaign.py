"""Shared existing-guest preflight/export for the two independently opt-in A10 tests."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess

from failure_paths import Campaign as FailureCampaign, operation_id, same_operation
from guest import CAMPAIGN, ROOT, RequestHandle, phase, wire, write_json
from source_gap import no_effect, require, sha
from ssh_campaign import SharedSsh


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
    executions = [r['value'] for r in records if r['origin'] == 'Runtime' and r['kind'] == 'Execution']
    require(len(executions) == 1 and isinstance(executions[0], list) and len(executions[0]) == 4
            and executions[0][0] == list(handle.key), 'exactly one accepted execution in whole capture')
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
            'kernel_clock': 'CLOCK_BOOTTIME', 'volatile_tail_unknown': True, 'full_execution_replay': False}


class GatewayCampaign(FailureCampaign):
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
