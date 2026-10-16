#!/usr/bin/env python3
"""Opt-in ARM module + systemd manager/gateway + SDK lifecycle integration.

Uses only a caller-supplied disposable, non-actuating guest. Every campaign has
fresh output/principal/request identities. Mutating calls are never retried after
failure. Pending recovery is inspected read-only, not silently resubmitted.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import shlex
import ssl
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'sdk/python'))
from actryn import Client, RequestHandle, RpcError
from actryn import robot_v1_pb2 as wire

CAMPAIGN = {'phase': 'arguments', 'started': time.monotonic()}


def write_json(name, value):
    output = CAMPAIGN.get('output')
    if output:
        (output / name).write_text(json.dumps(value, indent=2, default=repr))


def phase(name):
    CAMPAIGN['phase'] = name
    event = {'phase': name, 'elapsed_s': round(time.monotonic() - CAMPAIGN['started'], 3)}
    print(json.dumps(event), flush=True)
    if CAMPAIGN.get('output'):
        with (CAMPAIGN['output'] / 'phases.jsonl').open('a') as stream:
            stream.write(json.dumps(event) + '\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ssh-port', type=int, default=26221)
    parser.add_argument('--tcp-port', type=int, default=27443)
    parser.add_argument('--key', required=True)
    parser.add_argument('--known-hosts', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cli', type=Path, default=ROOT / 'target/debug/actryn')
    args = parser.parse_args()
    os.umask(0o077)
    args.output.mkdir(parents=True, exist_ok=False)
    CAMPAIGN['output'] = args.output
    ssh = ['ssh', '-i', args.key, '-p', str(args.ssh_port), '-o', 'BatchMode=yes',
           '-o', 'ConnectTimeout=5', '-o', 'UserKnownHostsFile=' + args.known_hosts,
           'root@127.0.0.1']

    def run(command):
        return subprocess.check_output(ssh + [command], timeout=30)

    phase('guest identity preflight')
    assert run('uname -m').strip() == b'aarch64'
    assert run('uname -r').strip() == b'6.12.111+deb13-arm64'
    assert b'linux,dummy-virt' in run('cat /proc/device-tree/compatible')
    epoch = b''
    principal = 'preview-' + secrets.token_hex(6)
    write_json('campaign.json', {'principal': principal, 'physical_acceptance': False})

    def local(method, payload=None, closure=False):
        nonlocal epoch
        request = wire.Request(version=1, request_id=secrets.token_bytes(16), robot_epoch=epoch)
        getattr(request, method).CopyFrom(payload or wire.Empty())
        encoded = base64.b64encode(request.SerializeToString(deterministic=True)).decode()
        path = '/run/actryn-robot/' + ('closure.sock' if closure else 'operator.sock')
        program = f'''import base64,socket,struct,sys
s=socket.socket(socket.AF_UNIX);s.settimeout(8);s.connect({path!r})
b=base64.b64decode({encoded!r});s.sendall(struct.pack('!I',len(b))+b)
f=s.makefile('rb');h=f.read(4);assert len(h)==4;n=struct.unpack('!I',h)[0];assert 0<n<=65536
b=f.read(n);assert len(b)==n;sys.stdout.buffer.write(b)
'''
        response = wire.Response.FromString(run('python3 -c ' + shlex.quote(program)))
        assert response.request_id == request.request_id and response.version == 1
        assert len(response.robot_epoch) == 16
        epoch = response.robot_epoch
        if response.HasField('failure'):
            failure = {'phase': CAMPAIGN['phase'], 'method': method,
                       'code': response.failure.code, 'message': response.failure.message}
            write_json('last-local-failure.json', failure)
            raise RuntimeError(f'{method}: {response.failure.message}')
        value = json.loads(response.report.json)
        if method == 'describe':
            CAMPAIGN['last_description'] = value
        return value

    def poll(function, ready, timeout=8):
        end = time.monotonic() + timeout
        while True:
            value = function()
            CAMPAIGN['last_poll'] = value
            if ready(value):
                return value
            if time.monotonic() >= end:
                raise AssertionError({'phase': CAMPAIGN['phase'], 'timeout_s': timeout, 'last': value})
            time.sleep(.05)

    def recover_once(label):
        phase(label)
        if local('describe')['runtime']['prepared'] is not None:
            local('retire', closure=True)
            poll(lambda: local('describe'), lambda d: d['runtime']['retirement_ready'])
        write_json(label.replace(' ', '-') + '.json', local('recover'))
        return poll(lambda: local('describe'), lambda d: d['runtime']['recovery_ready']
                    and d['runtime']['prepared'] is None
                    and not d['runtime']['recovery_pending']
                    and d['runtime']['kernel']['state'] == 0
                    and d['runtime']['kernel']['flags'] & 1, 14)

    def openssl(*arguments):
        return subprocess.check_output(['openssl', *arguments], stderr=subprocess.DEVNULL, timeout=15)

    def path(name):
        return str(args.output / name)

    def cli(*arguments):
        timeout = 120 if arguments[0] == 'export' else 30
        return json.loads(subprocess.check_output([str(args.cli), 'robot', *arguments], timeout=timeout))

    def cli_pair(prefix, pin):
        result = cli('pair', '--endpoint', f'127.0.0.1:{args.tcp_port}', '--dns', 'robot.test',
                     '--pin', pin, '--ca', path(prefix + 'ca.pem'), '--cert', path(prefix + 'client.pem'),
                     '--key', path(prefix + 'client.key'), '--out', path(prefix + 'pair.json'))
        assert result['result'] == 'paired' and result['authority_issued'] is False
        return ['--pair', path(prefix + 'pair.json'), '--cert', path(prefix + 'client.pem'),
                '--key', path(prefix + 'client.key')]

    def issue_ca(prefix):
        openssl('req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes',
                '-keyout', path(prefix + 'ca.key'), '-out', path(prefix + 'ca.pem'),
                '-subj', '/CN=Actryn disposable test CA ' + prefix, '-days', '1',
                '-addext', 'basicConstraints=critical,CA:TRUE',
                '-addext', 'keyUsage=critical,keyCertSign,cRLSign')

    def issue_device(prefix, csr):
        (args.output / (prefix + 'robot.csr')).write_text(csr)
        extension = args.output / (prefix + 'server.ext')
        extension.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\n'
                             'extendedKeyUsage=serverAuth\nsubjectAltName=DNS:robot.test\n')
        openssl('x509', '-req', '-in', path(prefix + 'robot.csr'), '-CA', path(prefix + 'ca.pem'),
                '-CAkey', path(prefix + 'ca.key'), '-CAcreateserial', '-out', path(prefix + 'robot.pem'),
                '-days', '1', '-extfile', str(extension))
        return hashlib.sha256(openssl('x509', '-in', path(prefix + 'robot.pem'), '-outform', 'DER')).hexdigest()

    def issue_client(prefix):
        openssl('req', '-new', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes',
                '-keyout', path(prefix + 'client.key'), '-out', path(prefix + 'client.csr'),
                '-subj', '/CN=preview-workload-' + principal)
        extension = args.output / (prefix + 'client.ext')
        extension.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\n'
                             'extendedKeyUsage=clientAuth\n')
        openssl('x509', '-req', '-in', path(prefix + 'client.csr'), '-CA', path(prefix + 'ca.pem'),
                '-CAkey', path(prefix + 'ca.key'), '-CAcreateserial', '-out', path(prefix + 'client.pem'),
                '-days', '1', '-extfile', str(extension))
        return hashlib.sha256(openssl('x509', '-in', path(prefix + 'client.pem'), '-outform', 'DER')).hexdigest()

    def connection(prefix, pin):
        return Client('127.0.0.1', port=args.tcp_port, server_name='robot.test', ca=path(prefix + 'ca.pem'),
                      certificate=path(prefix + 'client.pem'), key=path(prefix + 'client.key'),
                      paired_fingerprint=pin)

    write_json('initial.json', local('describe'))
    recover_once('initial recovery')
    phase('initial local enrollment')
    enrollment = local('enroll_request', wire.EnrollmentRequest(dns_name='robot.test'))
    # Explicit duplicate-success test, not retry after an uncertain failure.
    assert local('enroll_request', wire.EnrollmentRequest(dns_name='robot.test')) == enrollment
    issue_ca('')
    server_pin = issue_device('', enrollment['csr_pem'])
    installed = local('enroll_install', wire.EnrollmentInstall(
        certificate_pem=(args.output / 'robot.pem').read_bytes(), ca_pem=(args.output / 'ca.pem').read_bytes()))
    assert installed['device_certificate_sha256'] == server_pin and not installed['rearmed']
    client_pin = issue_client('')
    local('install_principal', wire.PrincipalInstall(principal=principal, certificate_sha256=client_pin, can_propose=True))
    phase('mTLS pairing and authentication')
    try:
        connection('', '0' * 64)
        raise AssertionError('wrong pairing pin accepted')
    except RpcError:
        pass
    with connection('', server_pin) as authenticated:
        assert authenticated.describe()['live_actuation'] is False
    phase('CLI pinned pairing')
    cli_credentials = cli_pair('', server_pin)
    recover_once('prepared attempt recovery')
    phase('explicit rearm prepare grant activate')
    local('rearm')
    poll(lambda: local('describe'), lambda d: d['runtime']['kernel']['state'] == 1)
    attempt, namespace = secrets.token_bytes(16), secrets.token_bytes(16)
    prepared = local('prepare', wire.Prepare(attempt=attempt, namespace=namespace, principal=principal))
    assert bytes(prepared['binding']['attempt']) == attempt
    poll(lambda: local('describe'), lambda d: d['runtime']['preparation_ready'])
    local('grant', wire.Grant(duration_ms=30_000))
    local('activate')
    handles = []
    for number in range(2):
        phase(f'natural completion {number}')
        handle = RequestHandle.create(attempt, namespace)
        handles.append(handle)
        write_json(f'handle-{number}.json', handle.json())
        with connection('', server_pin) as rpc:
            observation = rpc.observe(attempt, namespace)
            rpc.propose(handle, observation_id=observation['id'], left_delta_ticks=5,
                        right_delta_ticks=-5, duration_ms=5000, parent_digest=b'\x06' * 32)
            completed = poll(lambda: rpc.query(handle), lambda r: r['snapshot'] and r['snapshot']['reconciled'], 5)
            assert completed['snapshot']['verdict'] == 'TargetReached', completed
        write_json(f'operation-{number}.json', completed)
    phase('absent key durable cancellation')
    absent = RequestHandle.create(attempt, namespace)
    write_json('cancelled-handle.json', absent.json())
    with connection('', server_pin) as rpc:
        cancelled = rpc.cancel(absent)
        assert cancelled['operation'] is None
        poll(lambda: rpc.query(absent), lambda r: r['snapshot']['cancellation_durable'])
    phase('CLI cancellation from durable pre-send handle')
    cli_handle = path('cli-cancelled-handle.json')
    saved = cli('handle', '--pair', path('pair.json'), '--attempt', attempt.hex(),
                '--namespace', namespace.hex(), '--out', cli_handle)
    assert saved['authority_issued'] is False
    cancelled = cli('cancel', *cli_credentials, '--handle', cli_handle)
    assert cancelled['handle_state'] == 'cancel_requested' and cancelled['report']['operation'] is None
    poll(lambda: cli('query', *cli_credentials, '--handle', cli_handle),
         lambda r: r['report']['snapshot']['cancellation_durable'])

    phase('gateway death while kernel operation RUNNING')
    old_pid = int(run('systemctl show --property=MainPID --value actryn-gatewayd.service').strip())
    interrupted = RequestHandle.create(attempt, namespace)
    write_json('gateway-interrupted-handle.json', interrupted.json())
    with connection('', server_pin) as rpc:
        observation = rpc.observe(attempt, namespace)
        rpc.propose(interrupted, observation_id=observation['id'], left_delta_ticks=100,
                    right_delta_ticks=-100, duration_ms=10000, parent_digest=b'\x07' * 32)
        running = poll(lambda: rpc.describe(), lambda d: d['runtime']['kernel']['state'] == 2
                       and d['runtime']['kernel']['operation_state'] == 2
                       and d['runtime']['kernel']['flags'] & 8
                       and d['runtime']['operation']['key'] == list(interrupted.key), 3)
        write_json('gateway-before-kill.json', running)
        trigger = time.monotonic()
        # Deliberately no explicit revoke before this signal. RUNNING is observed;
        # nonzero output and the exact state at signal delivery are not asserted.
        run('systemctl kill --kill-whom=main --signal=SIGKILL actryn-gatewayd.service')
    closed = poll(lambda: local('describe'), lambda d: d['runtime']['health']['inhibited']
                  and not d['runtime']['kernel']['flags'] & 8, 4)
    assert closed['runtime']['kernel']['reason'] == 3, closed  # GRANT_REVOKED, not evidence/expiry fault
    write_json('gateway-closure.json', {'observed_running_before_signal': True,
               'nonzero_output_asserted': False, 'exact_signal_state_independently_measured': False,
               'elapsed_after_signal_s': time.monotonic() - trigger, 'description': closed})
    poll(lambda: int(run('systemctl show --property=MainPID --value actryn-gatewayd.service').strip()),
         lambda pid: pid > 0 and pid != old_pid, 5)

    def gateway_ready():
        # Reconnection/Describe is read-only. Only this readiness probe tolerates
        # startup connection errors; mutating calls never use this loop.
        try:
            with connection('', server_pin) as rpc:
                return {'ready': True, 'description': rpc.describe()}
        except (RpcError, OSError) as error:
            return {'ready': False, 'error': repr(error)}

    poll(gateway_ready, lambda value: value['ready'], 5)
    with connection('', server_pin) as rpc:
        retained = rpc.query(absent)
        assert retained['snapshot']['cancellation_durable'] and not retained['live_authority']
        denied = RequestHandle.create(attempt, namespace)
        try:
            rpc.propose(denied, observation_id=observation['id'], left_delta_ticks=1,
                        right_delta_ticks=1, duration_ms=1000, parent_digest=b'\x08' * 32)
            raise AssertionError('old namespace admitted after gateway death')
        except RpcError:
            pass
        assert rpc.query(denied)['snapshot'] is None
    try:
        local('activate')
        raise AssertionError('gateway-revoked binding reactivated')
    except RuntimeError:
        pass
    phase('explicit local revoke remains available')
    local('revoke', closure=True)

    recover_once('manager crash preparation recovery')
    phase('fresh local authority for manager crash test')
    local('rearm')
    poll(lambda: local('describe'), lambda d: d['runtime']['kernel']['state'] == 1)
    crash_attempt, crash_namespace = secrets.token_bytes(16), secrets.token_bytes(16)
    local('prepare', wire.Prepare(attempt=crash_attempt, namespace=crash_namespace, principal=principal))
    poll(lambda: local('describe'), lambda d: d['runtime']['preparation_ready'])
    local('grant', wire.Grant(duration_ms=30_000))
    local('activate')
    crashed = RequestHandle.create(crash_attempt, crash_namespace)
    write_json('manager-interrupted-handle.json', crashed.json())
    manager_pid = int(run('systemctl show --property=MainPID --value actryn-robotd.service').strip())
    previous_epoch = epoch
    phase('manager death while kernel operation RUNNING')
    with connection('', server_pin) as rpc:
        observation = rpc.observe(crash_attempt, crash_namespace)
        rpc.propose(crashed, observation_id=observation['id'], left_delta_ticks=100,
                    right_delta_ticks=-100, duration_ms=10000, parent_digest=b'\x09' * 32)
        durable = poll(lambda: rpc.query(crashed), lambda r: r['snapshot'] is not None
                       and r['snapshot']['operation'] is not None, 3)
        running = poll(lambda: rpc.describe(), lambda d: d['runtime']['kernel']['state'] == 2
                       and d['runtime']['kernel']['operation_state'] == 2
                       and d['runtime']['kernel']['flags'] & 8
                       and d['runtime']['operation']['key'] == list(crashed.key), 3)
        write_json('manager-before-kill.json', {'description': running, 'durable': durable})
        run('systemctl kill --kill-whom=main --signal=SIGKILL actryn-robotd.service')
    poll(lambda: int(run('systemctl show --property=MainPID --value actryn-robotd.service').strip()),
         lambda pid: pid > 0 and pid != manager_pid, 8)
    epoch = b''  # Describe discovers the replacement before inspecting retained identities.

    def manager_ready():
        try:
            return {'ready': True, 'description': local('describe')}
        except (subprocess.SubprocessError, OSError, RuntimeError) as error:
            return {'ready': False, 'error': repr(error)}

    recovered = poll(manager_ready, lambda value: value['ready'], 8)['description']
    assert epoch != previous_epoch
    assert recovered['runtime']['health']['inhibited']
    assert recovered['runtime']['prepared'] is None
    assert not recovered['runtime']['kernel']['flags'] & 8
    write_json('manager-restarted.json', recovered)
    # Restart the relay explicitly if systemd stopped the dependent unit.
    run('systemctl start actryn-gatewayd.service')
    poll(gateway_ready, lambda value: value['ready'], 5)
    with connection('', server_pin) as rpc:
        retained = rpc.query(crashed)
        snapshot = retained['snapshot']
        assert not retained['live_authority'] and snapshot['terminal']
        assert snapshot['phase'] == 'OutcomeUnknown' and snapshot['verdict'] == 'OutcomeUnknown'
        assert not snapshot['reconciled'] and not snapshot['cancellation_durable']
        assert snapshot['operation'] == durable['snapshot']['operation']
        write_json('manager-retained-unknown.json', retained)
        for _ in range(3):
            state = rpc.describe()['runtime']
            assert state['prepared'] is None and state['health']['inhibited']
            assert not state['kernel']['flags'] & 8
            time.sleep(.1)
        try:
            rpc.propose(crashed, observation_id=observation['id'], left_delta_ticks=100,
                        right_delta_ticks=-100, duration_ms=10000, parent_digest=b'\x09' * 32)
            raise AssertionError('old prepared namespace regained authority after manager restart')
        except RpcError:
            pass
        assert rpc.query(crashed) == retained
    phase('CLI retained query through original pairing after manager restart')
    historical = cli('query', *cli_credentials, '--handle', cli_handle)
    assert not historical['report']['live_authority']
    assert historical['report']['snapshot']['cancellation_durable']
    assert json.loads(Path(path('pair.json')).read_text())['robot_epoch'] == previous_epoch.hex()
    write_json('cli-retained-after-manager-restart.json', historical)

    recover_once('identity rotation inhibited recovery')
    phase('prepare replacement identity material')
    rotation = local('enroll_request', wire.EnrollmentRequest(dns_name='robot.test'))
    issue_ca('rotated-')
    new_pin = issue_device('rotated-', rotation['csr_pem'])
    new_client_pin = issue_client('rotated-')
    # Same stable principal under the replacement issuer makes this a generation
    # test, not a test that happens to reject an unrelated principal.
    local('install_principal', wire.PrincipalInstall(principal=principal, certificate_sha256=new_client_pin, can_propose=True))
    phase('identity rotation retires established TLS')
    old_rpc = connection('', server_pin)
    assert old_rpc.describe()['identity']['device_certificate_sha256'] == server_pin
    stop = threading.Event()
    ready = threading.Event()
    keepalive = {}

    def old_session():
        while not stop.is_set():
            try:
                old_rpc.describe()
                keepalive['last_success'] = time.monotonic()
                keepalive['successes'] = keepalive.get('successes', 0) + 1
                ready.set()
            except RpcError as error:
                keepalive['rejected_at'] = time.monotonic()
                keepalive['error'] = repr(error)
                ready.set()
                return
            stop.wait(.1)  # Keep the established socket below the 2 s idle limit.

    worker = threading.Thread(target=old_session, daemon=True)
    worker.start()
    try:
        assert ready.wait(2) and 'last_success' in keepalive, keepalive
        installation_started = time.monotonic()
        rotated = local('enroll_install', wire.EnrollmentInstall(
            certificate_pem=(args.output / 'rotated-robot.pem').read_bytes(),
            ca_pem=(args.output / 'rotated-ca.pem').read_bytes()))
        assert rotated['device_certificate_sha256'] == new_pin and not rotated['rearmed']
        worker.join(3)
        assert not worker.is_alive(), 'established old TLS session remained usable after identity rotation'
        assert 'rejected_at' in keepalive and keepalive['rejected_at'] >= installation_started, keepalive
        assert keepalive['rejected_at'] - keepalive['last_success'] < 2, 'idle timeout could explain old TLS closure'
        write_json('rotation-old-session.json', keepalive)
    finally:
        stop.set()
        old_rpc.close()
        worker.join(6)
    with connection('rotated-', new_pin) as rpc:
        healthy = rpc.describe()
        assert healthy['identity']['device_certificate_sha256'] == new_pin
        assert healthy['runtime']['kernel']['state'] == 0
        assert not healthy['runtime']['kernel']['flags'] & 8
    try:
        connection('', server_pin)
        raise AssertionError('removed issuer still authenticates a new TLS connection')
    except (RpcError, ssl.SSLError, ConnectionError):
        pass
    phase('SDK retired capture listing chunks and hashes')
    capture_output = args.output / 'retired-capture'
    capture_output.mkdir()
    with connection('rotated-', new_pin) as rpc:
        retained = rpc.query(absent)
        assert retained['snapshot']['cancellation_durable'] and not retained['live_authority']
        manifest = rpc.evidence_read(absent)
        inspection = manifest['inspection']
        assert not inspection['live_authority']
        assert bytes(inspection['prepared']['binding']['attempt']) == attempt
        assert bytes(inspection['prepared']['binding']['namespace']) == namespace
        assert manifest['volatile_tail_unknown'] is True
        assert manifest['execution_replay_eligible'] is False
        count, total = manifest['file_count'], manifest['total_bytes']
        assert type(count) is int and 1 <= count <= 8192
        assert type(total) is int and 0 <= total <= 64 * 1024 * 1024
        entries, page = [], manifest
        for _ in range(257):
            assert page['file_count'] == count and page['total_bytes'] == total
            assert 1 <= len(page['files']) <= 32
            entries.extend(page['files'])
            assert len(entries) <= count
            next_offset = page['next_offset']
            if next_offset is None:
                break
            assert type(next_offset) is int and next_offset == len(entries) < count
            page = rpc.evidence_read(absent, offset=next_offset)
        else:
            raise AssertionError('capture pagination exceeded finite capacity')
        assert len(entries) == count and sum(e['size'] for e in entries) == total
        assert len({e['file'] for e in entries}) == count
        assert any(e['file'] == 'checkpoints.sqlite' for e in entries)
        assert any(e['file'].endswith('.mcap') for e in entries)
        for entry in entries:
            name, size = entry['file'], entry['size']
            assert name in ('checkpoints.sqlite', 'checkpoints.sqlite-journal') or (
                len(name) == 31 and name.startswith('batch-') and name.endswith('.mcap')
                and name[6:26].isascii() and name[6:26].isdigit())
            assert type(size) is int and 0 <= size <= total
            digest, offset = hashlib.sha256(), 0
            with (capture_output / name).open('xb') as stream:
                while offset < size:
                    chunk = rpc.evidence_read(absent, file=name, offset=offset)
                    assert chunk['file'] == name and chunk['offset'] == offset and chunk['size'] == size
                    data = bytes.fromhex(chunk['data_hex'])
                    assert data.hex() == chunk['data_hex'] and 1 <= len(data) <= 16384
                    assert offset + len(data) <= size and chunk['next_offset'] == offset + len(data)
                    stream.write(data)
                    digest.update(data)
                    offset += len(data)
            assert digest.hexdigest() == entry['sha256'], entry
        # These are read-only negative checks. Rejection does not retry any mutation.
        wrong_attempt = RequestHandle(secrets.token_bytes(16), namespace, absent.key)
        for bad_handle, name in [(wrong_attempt, ''), (absent, 'identity.key')]:
            try:
                rpc.evidence_read(bad_handle, file=name)
                raise AssertionError('capture boundary accepted mismatched identity or unsupported file')
            except RpcError:
                pass
        manifest['files'] = entries
        manifest['next_offset'] = None
        write_json('retired-capture-manifest.json', manifest)
        write_json('retired-capture-verification.json', {'files': count, 'bytes': total,
                   'all_sha256_verified': True, 'retained_principal_after_rotation': principal,
                   'execution_replay_eligible': False, 'physical_acceptance': False})
    phase('CLI retired capture export under explicitly replaced pairing')
    rotated_credentials = cli_pair('rotated-', new_pin)
    cli_export = cli('export', *rotated_credentials, '--handle', cli_handle, '--out', path('cli-capture'))
    assert cli_export['result'] == 'exported' and cli_export['execution_replay_eligible'] is False
    assert not (args.output / 'cli-capture/INCOMPLETE.json').exists()
    exported = json.loads((args.output / 'cli-capture/manifest.json').read_text())
    assert len(exported['files']) == count and exported['total_bytes'] == total
    for entry in exported['files']:
        raw = (args.output / 'cli-capture/capture' / entry['file']).read_bytes()
        assert len(raw) == entry['size'] and hashlib.sha256(raw).hexdigest() == entry['sha256']
    write_json('cli-export-verification.json', cli_export)
    phase('principal revocation under replacement identity')
    local('revoke_principal', wire.PrincipalRevoke(principal=principal), closure=True)
    try:
        connection('rotated-', new_pin)
        raise AssertionError('locally revoked principal accepted')
    except RpcError:
        pass
    write_json('final.json', local('describe'))
    phase('complete')
    print(json.dumps({'test': 'robotd-real-module-mtls-sdk', 'status': 'PASS',
                      'physical_acceptance': False, 'operations': [h.json() for h in handles],
                      'gateway_interrupted_operation': interrupted.json(),
                      'manager_interrupted_operation': crashed.json(),
                      'manager_restart_retained_unknown_without_resend': True,
                      'rotation_established_session_retired': True, 'retired_capture_hashes_verified': True}), flush=True)


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        write_json('failure.json', {'phase': CAMPAIGN['phase'], 'error_type': type(error).__name__,
                   'error': str(error), 'elapsed_s': time.monotonic() - CAMPAIGN['started'],
                   'last_poll': CAMPAIGN.get('last_poll'), 'last_description': CAMPAIGN.get('last_description')})
        print(f"FAILED phase={CAMPAIGN['phase']} retained={CAMPAIGN.get('output')}", file=sys.stderr, flush=True)
        raise
