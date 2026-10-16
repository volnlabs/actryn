#!/usr/bin/env python3
"""A10: exact installed gateway dies while a root helper retains its real FDs."""
import json
import os
from pathlib import Path
import secrets
import select
import shlex
import subprocess
import time

from failure_paths import OneProposal, same_operation
from gateway_campaign import GatewayCampaign, main
from gateway_fds import HOLD_NS, validate_roles
from guest import phase, wire, write_json
from actryn import OutcomeUnknown, RpcError
from source_gap import require


def check_retirement(description, operation):
    runtime, kernel = description['runtime'], description['runtime']['kernel']
    require(description['clock_healthy'] and runtime['event_stream_healthy']
        and set(runtime['health']['evidence_issues']).issubset({'WriterStopped'})
        and runtime['health']['registry_fault'] is None and same_operation(kernel, operation)
        and kernel['reason'] == 3 and not kernel['flags'] & 8
        and kernel['operation_state'] == 4 and kernel['left_permille'] == kernel['right_permille'] == 0,
        'gateway revocation not reconciled, or independent health fault')


def helper_command(campaign, mode, remote):
    helper = Path(__file__).with_name('gateway_fds.py').read_text()
    return 'python3 -c ' + shlex.quote(helper) + ' ' + ' '.join(map(shlex.quote,
        [mode, str(campaign.pins['gateway_pid']), campaign.args.gateway_sha256,
         str(campaign.pins['manager_pid']), remote]))


class RemoteRetainer:
    def __init__(self, campaign):
        self.campaign = campaign
        self.remote = '/var/tmp/actryn-gateway-fd-' + secrets.token_hex(8)
        self.process, self.kill_sent, self.result = None, False, None

    def line(self, expected, timeout):
        deadline, data = time.monotonic() + timeout, bytearray()
        while b'\n' not in data:
            remaining = deadline - time.monotonic()
            require(remaining > 0 and select.select([self.process.stdout], [], [], remaining)[0],
                    'retainer response deadline; no command retry')
            chunk = os.read(self.process.stdout.fileno(), 16384 - len(data))
            require(chunk and len(data) + len(chunk) < 16384, 'retainer response EOF/capacity')
            data.extend(chunk)
        require(data.count(b'\n') == 1 and data.endswith(b'\n'), 'unexpected multiple retainer records')
        value = json.loads(data)
        write_json('retainer-' + expected + '.json', value)
        require(value.get('phase') == expected and 'error' not in value, 'retainer phase failed')
        return value

    def __enter__(self):
        write_json('retainer-intent.json', {'remote_output': self.remote, 'lease_ns': HOLD_NS,
            'gateway_pid': self.campaign.pins['gateway_pid'], 'signal_limit': 1, 'automatic_retry': False})
        self.process = subprocess.Popen(self.campaign.ssh + [helper_command(self.campaign, 'retain', self.remote)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            ready = self.line('retained', 1.5)
            validate_roles(ready['roles'])
            require(ready['pidfd_pinned'] and ready['gateway_pid'] == self.campaign.pins['gateway_pid']
                    and ready['manager_pid'] == self.campaign.pins['manager_pid'], 'retainer identity')
            return self
        except BaseException:
            self.close()
            raise

    def kill_once(self):
        require(not self.kill_sent, 'kill command cannot be retried')
        self.kill_sent = True
        write_json('gateway-kill-intent.json', {'gateway_pid': self.campaign.pins['gateway_pid'],
            'pidfd_only': True, 'automatic_retry': False, 'host_monotonic_ns': time.monotonic_ns()})
        self.process.stdin.write(b'kill\n'); self.process.stdin.flush()
        result = self.line('killed', 1)
        require(result['pidfd_dead'] and result['held_after_death'] == 3
                and result['synthetic_heartbeat']['sends'] == 1, 'actual pinned death/retained FDs not established')
        self.killed = result
        return result

    def close(self):
        if self.process is None:
            return
        process, self.process = self.process, None
        try:
            # EOF aborts an unarmed helper. Only the killed helper gets release.
            stdout, stderr = process.communicate(b'release\n' if self.kill_sent else b'', timeout=10)
            write_json('retainer-process.json', {'returncode': process.returncode,
                'stdout': stdout[:32768].decode(errors='replace'), 'stderr': stderr[:32768].decode(errors='replace'),
                'release_commands': int(self.kill_sent), 'automatic_retry': False})
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=2)
            write_json('retainer-process-unknown.json', {'stdout': stdout[:32768].decode(errors='replace'),
                'stderr': stderr[:32768].decode(errors='replace'), 'automatic_retry': False})
            raise
        finally:
            try:
                self.result = json.loads(self.campaign.run('cat ' + shlex.quote(self.remote + '/retained.json')))
                write_json('retainer-final.json', self.result)
            except BaseException as error:
                write_json('retainer-release-unknown.json', {'error': repr(error), 'automatic_retry': False})
        require(self.result and self.result['owned_fds_closed'] and self.result['within_lease'], 'FD cleanup unknown/late')
        if self.kill_sent:
            require(process.returncode == 0 and self.result['released'] and 'error' not in self.result
                    and self.result['signal_attempts'] == 1, 'retained lifetime fault did not complete as specified')

    def __exit__(self, *_):
        self.close()


class LifetimeCampaign(GatewayCampaign):
    def fd_preflight(self, _, initial):
        require(initial['runtime']['kernel']['state'] == 0, 'FD preflight must be inhibited')
        phase('A10 nonmutating pidfd_getfd preflight, before grant')
        remote = '/var/tmp/actryn-gateway-fd-' + secrets.token_hex(8)
        with self.connection() as rpc:
            write_json('fd-preflight-description.json', rpc.describe())
            command = helper_command(self, 'probe', remote)
            write_json('fd-preflight-intent.json', {'remote_output': remote, 'permission_changes': False,
                                                   'signal_limit': 0, 'authority_issued': False})
            result = subprocess.run(self.ssh + [command], capture_output=True, timeout=5)
            write_json('fd-preflight-process.json', {'returncode': result.returncode,
                'stdout': result.stdout[:32768].decode(errors='replace'),
                'stderr': result.stderr[:32768].decode(errors='replace')})
            result.check_returncode()
            report = json.loads(result.stdout)
            write_json('fd-preflight.json', report)
            validate_roles(report['roles'])
            require(report['nonmutating_fd_preflight'] and report['signal_attempts'] == 0
                    and report['released'] and report['owned_fds_closed'] and 'error' not in report,
                    'FD preflight did not close all duplicates')

    def gateway_pid(self):
        return int(self.run('systemctl show --value -p MainPID actryn-gatewayd.service').strip())

    def ready_read(self):
        try:
            with self.connection() as rpc:
                return {'ready': True, 'description': rpc.describe()}
        except (OSError, RpcError) as error:
            return {'ready': False, 'error': repr(error)}

    def service_once(self, action):
        require(action in ('stop', 'start'), 'fixed gateway unit action')
        if not hasattr(self, 'service_actions'):
            self.service_actions = set()
        require(action not in self.service_actions, 'gateway service action cannot be retried')
        self.service_actions.add(action)
        write_json('gateway-' + action + '-intent.json', {'unit': 'actryn-gatewayd.service', 'automatic_retry': False})
        try:
            result = subprocess.run(self.ssh + ['systemctl ' + action + ' actryn-gatewayd.service'],
                                    capture_output=True, timeout=15)
        except BaseException as error:
            write_json('gateway-' + action + '-unknown.json', {'error': repr(error),
                'automatic_retry': False, 'service_action_outcome_unknown': True})
            raise
        write_json('gateway-' + action + '-result.json', {'returncode': result.returncode,
            'stdout': result.stdout[:8192].decode(errors='replace'), 'stderr': result.stderr[:8192].decode(errors='replace')})
        result.check_returncode()

    def run_campaign(self):
        self.setup(self.fd_preflight)
        denied = self.save_other_handle('denied')
        complete, restore_gateway = False, False
        try:
            self.activate()
            phase('A10 one real running operation before gateway lifetime fault')
            with self.connection() as rpc:
                observation = rpc.observe(self.handle.attempt, self.handle.namespace)
                call = OneProposal(rpc, self.handle, observation)
                write_json('proposal-intent.json', {'handle': self.handle.json(), 'observation': observation,
                    'target': [100, -100, 10000], 'automatic_retry': False})
                self.start_checked(rpc, self.handle, call)
                result = call.finish()
                operation = self.confirm_running(rpc, result)
                with RemoteRetainer(self) as retained:
                    killed = retained.kill_once()
                    closed = self.poll_read('gateway-closed', lambda: self.local('describe', label='closure-read'),
                        lambda d: same_operation(d['runtime']['kernel'], operation)
                            and d['runtime']['kernel']['operation_state'] == 4 and d['runtime']['kernel']['reason'] == 3
                            and not d['runtime']['kernel']['flags'] & 8, 3)
                    check_retirement(closed, operation)
                    require(closed['runtime']['kernel']['now_ns'] - killed['signal_ns'] < 3_000_000_000,
                            'gateway closure observation exceeded original liveness bound')
                    replacement = self.poll_read('gateway-replacement', self.gateway_pid,
                        lambda p: p > 1 and p != self.pins['gateway_pid'], 3)
                    self.poll_read('replacement-authentication', self.ready_read, lambda d: d['ready'], 2)
                    with self.connection() as fresh:
                        inspection = fresh.query(self.handle)
                        write_json('replacement-retained-query.json', inspection)
                        require(not inspection['live_authority'], 'new gateway revived old namespace')
                        try:
                            fresh.propose(denied, observation_id=observation['id'], left_delta_ticks=1,
                                right_delta_ticks=1, duration_ms=1000, parent_digest=b'\x31' * 32)
                        except OutcomeUnknown:
                            raise  # An unknown send cannot establish denial; never resend it.
                        except RpcError as error:
                            require('principal mismatch' in str(error), 'denial must identify binding generation mismatch')
                            write_json('old-binding-denied.json', {'error': str(error), 'handle': denied.json(), 'automatic_retry': False})
                        else:
                            raise AssertionError('replacement gateway accepted old namespace')
                        require(fresh.query(denied)['snapshot'] is None, 'old binding negative key was retained')
                    write_json('replacement-while-fds-held.json', {'new_pid': replacement,
                        'old_pid': self.pins['gateway_pid'], 'helper_live': retained.process.poll() is None,
                        'old_pidfd_dead': killed['pidfd_dead'], 'held_count': killed['held_after_death']})
                    require(retained.process.poll() is None, 'duplicates ended before replacement proof')
            interval = {'started_ns': killed['signal_ns'],
                        'finished_ns': min(retained.result['finished_ns'], killed['signal_ns'] + 3_000_000_000)}
            phase('A10 explicit local retirement and recovery with gateway offline')
            restore_gateway = True
            self.service_once('stop')
            require(self.gateway_pid() == 0, 'gateway is not offline')
            recovered = self.retire_recover()
            write_json('offline-recovery.json', recovered)
            restore_gateway = False
            self.service_once('start')
            self.poll_read('restored-gateway', self.ready_read, lambda d: d['ready'], 4)
            self.export(operation, interval)
            complete = True
        finally:
            if not complete:
                try:
                    self.local('revoke', label='failure-cleanup-revoke', closure=True)
                except BaseException as error:
                    write_json('cleanup-unknown.json', {'error': repr(error), 'automatic_retry': False})
            if restore_gateway:
                # A distinct one-shot restoration after stop intent, not a failed action retry.
                self.service_once('start')


if __name__ == '__main__':
    main('lifetime', LifetimeCampaign)
