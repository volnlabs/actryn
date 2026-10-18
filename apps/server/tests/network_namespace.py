"""Opt-in trusted CREATED-task netns proof. Imports are inert; no Start or profile change."""
import errno
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import select
import signal
import socket
import stat
import subprocess
import sys
import time

from guest_observer_gap import process_identity, task_rows

SCHEMA = 'actryn.test.created-network-namespace.v1'
CLONE_NEWNET = 0x40000000
OTHER_NS = ('pid', 'mnt', 'ipc', 'uts', 'user', 'cgroup')
DUMPS = dict(links=['link', 'show'], addresses=['address', 'show'],
             ipv4_routes=['-4', 'route', 'show', 'table', 'all'],
             ipv6_routes=['-6', 'route', 'show', 'table', 'all'])


class ProofFailure(RuntimeError):
    """Failed/unknown proof with bounded evidence for its owner to persist."""
    def __init__(self, evidence):
        super().__init__('network namespace proof failed; preserve evidence, never retry')
        self.evidence = evidence


def _captured(raw, cap):
    raw = raw or b''
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                hex=raw[:cap].hex(), omitted_bytes=max(0, len(raw)-cap))


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            assert key not in result, 'duplicate JSON field'
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def _positive(value):
    return type(value) is int and value > 0


def _namespace(value):
    assert isinstance(value, dict) and set(value) == {'dev', 'ino'}
    assert all(_positive(v) for v in value.values())


def _pin(pin):
    assert isinstance(pin, dict) and set(pin) == {'path', 'sha256', 'metadata', 'package'}, 'Root ip pin required'
    assert pin['path'] in ('/usr/bin/ip', '/usr/sbin/ip'), 'canonical packaged ip path only'
    assert re.fullmatch('[0-9a-f]{64}', pin['sha256'])
    m = pin['metadata']
    assert set(m) == {'dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtime_ns', 'ctime_ns'}
    assert all(type(v) is int and v >= 0 for v in m.values())
    assert stat.S_ISREG(m['mode']) and m['uid'] == 0 and not m['mode'] & 0o022 and m['mode'] & 0o111
    assert 0 < m['size'] <= 32*1024**2 and m['nlink'] > 0
    p = pin['package']
    assert isinstance(p, dict) and set(p) == {'name', 'version', 'architecture'} and p['name'] == 'iproute2'
    assert p['architecture'] == 'amd64' and re.fullmatch(r'[A-Za-z0-9.+:~\-]{1,128}', p['version'])


def _scope(expected):
    assert re.fullmatch('[0-9a-f]{32}', expected['attempt']) and re.fullmatch('sha256:[0-9a-f]{64}', expected['artifact'])
    b = expected['binding']; s = b['snapshot']
    assert b['ambiguous_create'] is False and _positive(b['cgroup_id'])
    assert _positive(s['pid']) and s['pid'] > 1 and _positive(s['start_ticks'])
    assert s['cgroup'] == '/actryn/'+expected['attempt']
    c = expected['proof_cgroup']
    assert isinstance(c, str) and c.startswith('/') and c != '/' and '\n' not in c
    assert c != '/actryn' and not c.startswith('/actryn/'), 'verifier must remain outside attempt cgroups'


def _topology_valid(value):
    assert isinstance(value, dict) and set(value) == set(DUMPS), 'four complete topology dumps required'
    decoded = {}
    for name, raw in value.items():
        assert isinstance(raw, str) and len(raw.encode()) <= 32768
        decoded[name] = _json(raw)
        assert isinstance(decoded[name], list) and len(decoded[name]) <= 256
    links = decoded['links']
    assert len(links) == 1 and links[0]['ifname'] == 'lo' and links[0]['link_type'] == 'loopback'
    assert _positive(links[0]['ifindex']) and isinstance(links[0]['flags'], list) and 'LOOPBACK' in links[0]['flags']
    assert all(isinstance(flag, str) for flag in links[0]['flags'])
    assert not any(k in links[0] for k in ('master', 'link', 'link_netnsid'))
    addresses = decoded['addresses']
    assert len(addresses) == 1 and addresses[0]['ifname'] == 'lo' and type(addresses[0]['ifindex']) is int and addresses[0]['ifindex'] == links[0]['ifindex']
    assert isinstance(addresses[0]['addr_info'], list) and len(addresses[0]['addr_info']) <= 16
    for address in addresses[0]['addr_info']:
        assert address['family'] in ('inet', 'inet6') and address['scope'] == 'host'
        ip = ipaddress.ip_address(address['local'])
        assert ip.is_loopback and ip.version == (4 if address['family'] == 'inet' else 6)
        assert type(address['prefixlen']) is int and address['prefixlen'] == (8 if ip.version == 4 else 128)
    for name, version in (('ipv4_routes', 4), ('ipv6_routes', 6)):
        for route in decoded[name]:
            assert route.get('dev') == 'lo' and route.get('type', 'unicast') in ('unicast', 'local', 'broadcast')
            assert not any(k in route for k in ('gateway', 'via', 'nexthops', 'multipath', 'encap'))
            network = ipaddress.ip_network(route['dst'], strict=False)
            assert network.version == version and network.is_loopback
    return decoded


def validate(report, expected, ip_pin):
    """Pure, exact-scope validation; never promotes a whole D2 result."""
    _pin(ip_pin); _scope(expected)
    assert report['schema'] == SCHEMA and report['expected'] == expected and report['ip_pin'] == ip_pin
    before, after = report['before'], report['after']
    assert before == after, 'CREATED task identity/output changed'
    b = expected['binding']; task = before['task']
    assert before['boot_id'] == b['boot_id'] and before['task_status'] == 'CREATED'
    assert type(before['stdout_bytes']) is type(before['stderr_bytes']) is int and before['stdout_bytes'] == before['stderr_bytes'] == 0
    assert _positive(task['pid']) and _positive(task['start_ticks'])
    assert (task['pid'], task['start_ticks'], task['cgroup']) == (b['snapshot']['pid'], b['snapshot']['start_ticks'], b['snapshot']['cgroup'])
    _namespace(task['netns'])
    w = report['worker']; initial, joined, final = w['before'], w['joined'], w['after']
    assert final == joined and joined == dict(initial, netns=task['netns']), 'only network namespace may change'
    assert _positive(initial['pid']) and initial['pid'] != task['pid'] and _positive(initial['start_ticks'])
    assert initial['cgroup'] == expected['proof_cgroup'] and initial['netns'] != task['netns']
    _namespace(initial['netns'])
    assert set(initial['other']) == set(OTHER_NS)
    for ns in initial['other'].values(): _namespace(ns)
    a = _topology_valid(w['topology_before']); z = _topology_valid(w['topology_after'])
    assert a == z, 'topology changed during probe'
    c = w['connect']
    assert c == dict(address='203.0.113.1', port=443, family='AF_INET', type='SOCK_STREAM', result=-1, errno=errno.ENETUNREACH)
    assert type(c['result']) is type(c['errno']) is type(c['port']) is int
    return dict(classification='trusted_namespace_functional_negative_not_agent_connect',
                attempt=expected['attempt'], artifact=expected['artifact'], binding=b,
                whole_D2=False, agent_external_connect=False, physical_qualification=False)


def _nsfd(fd):
    assert re.fullmatch(r'net:\[[0-9]+\]', os.readlink('/proc/self/fd/'+str(fd))), 'network namespace FD only'
    s = os.fstat(fd)
    return dict(dev=s.st_dev, ino=s.st_ino)


def _ns(path):
    s = path.stat()
    return dict(dev=s.st_dev, ino=s.st_ino)


def _identity():
    # No other namespace is entered; no PID or cgroup migration.
    own = process_identity(os.getpid()); own.pop('executable')
    assert own['cgroup'].startswith('0::/') and '\n' not in own['cgroup']
    own['cgroup'] = own['cgroup'][3:]
    own['netns'] = _ns(Path('/proc/self/ns/net'))
    own['other'] = {name: _ns(Path('/proc/self/ns')/name) for name in OTHER_NS}
    return own


def _command(argv, deadline, cap=32768):
    left = min(1, deadline-time.monotonic()); assert left > 0, 'finite proof deadline'
    result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=left,
                            env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'})
    assert time.monotonic() < deadline and result.returncode == 0 and not result.stderr
    assert len(result.stdout) <= cap, 'complete command output exceeds finite bound'
    return result.stdout


def _topology(ip):
    deadline = time.monotonic()+4
    return {name: _command([ip['path'], '-j', '-details', *args], deadline).decode('utf-8') for name, args in DUMPS.items()}


def _probe(netfd, ip_pin, proof_cgroup):
    """Child only. One namespace join followed by one socket/connect; no retry."""
    before = _identity(); target = _nsfd(netfd)
    assert before['cgroup'] == proof_cgroup and proof_cgroup != '/actryn' and not proof_cgroup.startswith('/actryn/')
    assert target != before['netns']
    os.setns(netfd, CLONE_NEWNET)
    joined = _identity(); assert joined == dict(before, netns=target)
    topology_before = _topology(ip_pin); _topology_valid(topology_before)
    # Creating after setns matters: a pre-existing socket keeps its original netns.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as stream:
        stream.settimeout(1)
        result, error = 0, 0
        try: stream.connect(('203.0.113.1', 443))
        except OSError as failure: result, error = -1, failure.errno
    topology_after = _topology(ip_pin)
    return dict(before=before, joined=joined, after=_identity(), topology_before=topology_before,
                topology_after=topology_after, connect=dict(address='203.0.113.1', port=443,
                family='AF_INET', type='SOCK_STREAM', result=result, errno=error))


def _metadata(s):
    return {k: getattr(s, 'st_'+k) for k in ('dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtime_ns', 'ctime_ns')}


def _checked_ip(pin, deadline):
    _pin(pin); path = Path(pin['path'])
    assert str(path.resolve(strict=True)) == pin['path']
    for p in (path.parent, *path.parent.parents):
        m = p.lstat(); assert stat.S_ISDIR(m.st_mode) and m.st_uid == 0 and not m.st_mode & 0o022
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd, 'rb') as stream:
        assert _metadata(os.fstat(stream.fileno())) == pin['metadata']
        raw = stream.read(pin['metadata']['size']+1)
        assert len(raw) == pin['metadata']['size'] and hashlib.sha256(raw).hexdigest() == pin['sha256'] and _metadata(os.fstat(stream.fileno())) == pin['metadata'] == _metadata(path.lstat())
    p = pin['package']
    raw = _command(['/usr/bin/dpkg-query', '-W', '-f=${Package}\t${Version}\t${Architecture}\n', 'iproute2'], deadline)
    assert raw.decode() == '\t'.join(p[k] for k in ('name', 'version', 'architecture'))+'\n'
    assert pin['path'] in _command(['/usr/bin/dpkg-query', '-L', 'iproute2'], deadline).decode().splitlines()


def _bookend(expected, pidfd, deadline):
    assert not select.select([pidfd], [], [], 0)[0], 'original task died'
    b = expected['binding']; pid = b['snapshot']['pid']
    tasks = task_rows(_command(['/usr/bin/ctr', '--namespace', 'actryn', 'tasks', 'list'], deadline))
    assert tasks.get(expected['attempt']) == dict(pid=pid, status='CREATED')
    task = process_identity(pid); assert task['cgroup'] == '0::'+b['snapshot']['cgroup']
    task['cgroup'] = b['snapshot']['cgroup']; task['netns'] = _ns(Path('/proc')/str(pid)/'ns/net')
    assert task['start_ticks'] == b['snapshot']['start_ticks']
    assert Path('/sys/fs/cgroup'+task['cgroup']).stat().st_ino == b['cgroup_id']
    logs = Path('/var/lib/actryn-server')/expected['attempt']
    sizes = {}
    for name in ('stdout', 'stderr'):
        fd = os.open(logs/(name+'.log'), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(fd, 'rb') as stream:
            m = _metadata(os.fstat(stream.fileno()))
            assert stat.S_ISREG(m['mode']) and m['nlink'] == 1 and m['size'] == 0
            assert not stream.read(1) and _metadata(os.fstat(stream.fileno())) == m
            sizes[name+'_bytes'] = 0
    assert sizes == dict(stdout_bytes=0, stderr_bytes=0)
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip(); assert boot == b['boot_id']
    assert not select.select([pidfd], [], [], 0)[0] and time.monotonic() < deadline
    return dict(boot_id=boot, task=task, task_status='CREATED', **sizes)


def collect(prepared_reply, expected, ip_pin):
    """Root-owned guest call only. No Prepare/Launch/Cancel, SQL or private reads.

    Caller owns the prepared attempt and durable recording/cleanup of any failure.
    ip_pin is mandatory: there is deliberately no configured/default guest pin.
    """
    _pin(ip_pin); _scope(expected)
    assert os.geteuid() == 0 and hasattr(os, 'setns'), 'qualified root Linux Python required'
    inspection = prepared_reply['inspection']; attempt = inspection['attempt']
    assert prepared_reply['result'] == 'ok' and attempt['id'] == expected['attempt'] and attempt['artifact_digest'] == expected['artifact']
    assert attempt['state'] == 'prepared' and attempt['outcome'] == 'pending' and _json(attempt['binding']) == expected['binding']
    assert inspection['robot_binding'] is None and inspection['robot_requests'] == []
    deadline = time.monotonic()+30
    _checked_ip(ip_pin, deadline)
    parent = _identity(); assert parent['cgroup'] == expected['proof_cgroup']
    pidfd = os.pidfd_open(expected['binding']['snapshot']['pid']); netfd = None
    child = worker_timeout = None
    report = dict(schema=SCHEMA, expected=expected, ip_pin=ip_pin)
    try:
        before = _bookend(expected, pidfd, deadline)
        report['before'] = before
        netfd = os.open('/proc/'+str(before['task']['pid'])+'/ns/net', os.O_RDONLY | os.O_CLOEXEC)
        assert _nsfd(netfd) == before['task']['netns']
        assert _bookend(expected, pidfd, deadline) == before
        payload = json.dumps(dict(ip_pin=ip_pin, proof_cgroup=expected['proof_cgroup'])).encode()
        try:
            child = subprocess.run(['/usr/bin/python3', '-B', '-E', '-s', str(Path(__file__).resolve()), '--child', str(netfd)],
                                   input=payload, capture_output=True, close_fds=True, pass_fds=(netfd,),
                                   timeout=min(15, deadline-time.monotonic()),
                                   env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'})
        except subprocess.TimeoutExpired as timeout:
            worker_timeout = timeout
            raise
        assert child.returncode == 0 and not child.stderr and len(child.stdout) <= 512*1024, 'worker failure/unknown; never retry'
        report['worker'] = _json(child.stdout)
        report['after'] = _bookend(expected, pidfd, deadline)
        _checked_ip(ip_pin, deadline)
        assert _identity() == parent and not select.select([pidfd], [], [], 0)[0] and time.monotonic() < deadline
        validate(report, expected, ip_pin)
        return report
    except Exception as failure:
        output = worker_timeout if worker_timeout is not None else child
        evidence = dict(report=report, failure_type=type(failure).__name__,
                        failure=str(failure)[:4096], worker_output=None)
        if output is not None:
            evidence['worker_output'] = dict(returncode=getattr(output, 'returncode', None),
                stdout=_captured(output.stdout, 512*1024), stderr=_captured(output.stderr, 64*1024))
        if isinstance(failure, subprocess.TimeoutExpired) and failure is not worker_timeout:
            evidence['control_timeout_output'] = dict(stdout=_captured(failure.stdout, 32768),
                stderr=_captured(failure.stderr, 32768))
        raise ProofFailure(evidence) from failure
    finally:
        if netfd is not None: os.close(netfd)
        os.close(pidfd)


def _child():
    assert len(sys.argv) == 3 and sys.argv[1] == '--child' and os.geteuid() == 0
    def expired(*_): raise TimeoutError('namespace child12s; unknown never retries')
    signal.signal(signal.SIGALRM, expired); signal.alarm(12)
    raw = sys.stdin.buffer.read(16385); assert len(raw) <= 16384
    value = _json(raw); _pin(value['ip_pin'])
    result = _probe(int(sys.argv[2]), value['ip_pin'], value['proof_cgroup'])
    encoded = json.dumps(result, separators=(',', ':')).encode(); assert len(encoded) <= 512*1024
    sys.stdout.buffer.write(encoded+b'\n'); sys.stdout.buffer.flush()


if __name__ == '__main__':
    _child()
