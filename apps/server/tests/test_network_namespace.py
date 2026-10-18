"""Pure synthetic/mocked proof tests; never enter a namespace or create a socket."""
import copy
import errno
import json
import unittest
from unittest.mock import Mock, patch
import network_namespace as proof


def raw(value):
    return json.dumps(value, separators=(',', ':'))


def fixture():
    task = dict(pid=88, start_ticks=100, cgroup='/actryn/'+'a'*32,
                executable='/usr/bin/runc', netns=dict(dev=4, ino=99))
    binding = dict(boot_id='11111111-1111-4111-8111-111111111111', cgroup_id=12,
                   ambiguous_create=False, snapshot=dict(pid=88, start_ticks=100, cgroup=task['cgroup']))
    expected = dict(attempt='a'*32, artifact='sha256:'+'b'*64, binding=binding,
                    proof_cgroup='/system.slice/trusted-proof.service')
    book = dict(boot_id=binding['boot_id'], task=task, task_status='CREATED', stdout_bytes=0, stderr_bytes=0)
    other = {name: dict(dev=4, ino=i+10) for i, name in enumerate(proof.OTHER_NS)}
    own = dict(pid=89, start_ticks=101, cgroup=expected['proof_cgroup'], netns=dict(dev=4, ino=80), other=other)
    joined = dict(own, netns=task['netns'])
    topology = dict(links=raw([dict(ifindex=1, ifname='lo', link_type='loopback', flags=['LOOPBACK'])]),
                    addresses=raw([dict(ifindex=1, ifname='lo', addr_info=[dict(family='inet', local='127.0.0.1', prefixlen=8, scope='host')])]),
                    ipv4_routes=raw([]), ipv6_routes=raw([]))
    ip = dict(path='/usr/sbin/ip', sha256='c'*64, metadata=dict(dev=1, ino=2, mode=0o100755, uid=0, gid=0, nlink=1, size=100, mtime_ns=1, ctime_ns=1),
              package=dict(name='iproute2', version='6.15.0-1', architecture='amd64'))
    report = dict(schema=proof.SCHEMA, expected=expected, before=book, after=copy.deepcopy(book), ip_pin=ip,
                  worker=dict(before=own, joined=joined, after=copy.deepcopy(joined),
                              topology_before=topology, topology_after=copy.deepcopy(topology),
                              connect=dict(address='203.0.113.1', port=443, family='AF_INET', type='SOCK_STREAM', result=-1, errno=errno.ENETUNREACH)))
    return report


class Evidence(unittest.TestCase):
    def test_complete_distinct_namespace_proof(self):
        value=fixture()
        result=proof.validate(value, value['expected'], value['ip_pin'])
        self.assertEqual(result['classification'], 'trusted_namespace_functional_negative_not_agent_connect')
        self.assertFalse(result['whole_D2'])

    def test_fail_closed_record_mutations(self):
        for label in ('wrong_attempt', 'wrong_binding', 'running', 'output', 'dead_identity', 'wrong_namespace',
                      'helper_in_attempt', 'other_namespace_changed', 'success', 'eperm', 'timeout', 'bool_result', 'wrong_destination'):
            with self.subTest(label=label):
                value=fixture(); expected=copy.deepcopy(value['expected'])
                if label=='wrong_attempt':value['expected']['attempt']='d'*32
                elif label=='wrong_binding':value['expected']['binding']['cgroup_id']=13
                elif label=='running':value['after']['task_status']='RUNNING'
                elif label=='output':value['after']['stdout_bytes']=1
                elif label=='dead_identity':value['after']['task']['start_ticks']+=1
                elif label=='wrong_namespace':value['worker']['joined']['netns']=dict(dev=4, ino=70)
                elif label=='helper_in_attempt':value['worker']['before']['cgroup']=value['before']['task']['cgroup']
                elif label=='other_namespace_changed':value['worker']['after']['other']['mnt']['ino']+=1
                elif label=='success':value['worker']['connect'].update(result=0, errno=0)
                elif label=='eperm':value['worker']['connect']['errno']=1
                elif label=='timeout':value['worker']['connect']['errno']=110
                elif label=='bool_result':value['worker']['connect']['result']=True
                elif label=='wrong_destination':value['worker']['connect']['address']='127.0.0.1'
                with self.assertRaises(AssertionError):proof.validate(value,expected,fixture()['ip_pin'])

    def test_topology_scope_complete_and_unchanged(self):
        for label in ('interface', 'address', 'default', 'gateway', 'unknown_family', 'duplicate_json', 'changed_after', 'missing_dump'):
            with self.subTest(label=label):
                value=fixture(); t=value['worker']['topology_before']
                if label=='interface':t['links']=raw([dict(ifindex=2,ifname='eth0',link_type='ether',flags=[])])
                elif label=='address':t['addresses']=raw([dict(ifindex=1,ifname='lo',addr_info=[dict(family='inet',local='203.0.113.1',prefixlen=32,scope='host')])])
                elif label=='default':t['ipv4_routes']=raw([dict(dst='default',dev='lo')])
                elif label=='gateway':t['ipv4_routes']=raw([dict(dst='127.0.0.0/8',dev='lo',gateway='1.2.3.4')])
                elif label=='unknown_family':t['addresses']=raw([dict(ifindex=1,ifname='lo',addr_info=[dict(family='other',local='127.0.0.1',prefixlen=8,scope='host')])])
                elif label=='duplicate_json':t['links']='[{"ifname":"eth0","ifname":"lo"}]'
                elif label=='missing_dump':del t['ipv6_routes']
                elif label=='changed_after':value['worker']['topology_after']['ipv6_routes']=raw([dict(dst='::1',dev='lo',type='local')])
                if label!='changed_after':value['worker']['topology_after']=copy.deepcopy(t)
                with self.assertRaises((AssertionError,ValueError)):proof.validate(value,value['expected'],value['ip_pin'])

    def test_loopback_routes_are_retained_and_allowed(self):
        value=fixture()
        for stage in ('topology_before','topology_after'):
            value['worker'][stage]['ipv4_routes']=raw([dict(dst='127.0.0.0/8',dev='lo',type='local',table='local')])
            value['worker'][stage]['ipv6_routes']=raw([dict(dst='::1',dev='lo',type='local',table='local')])
        proof.validate(value,value['expected'],value['ip_pin'])

    def test_missing_or_different_ip_pin_rejected(self):
        value=fixture()
        for pin in (None, {}, dict(value['ip_pin'],sha256='d'*64),dict(value['ip_pin'],package=None)):
            with self.assertRaises(AssertionError):proof.validate(value,value['expected'],pin)
        with patch.object(proof.os,'pidfd_open') as action:
            with self.assertRaises(AssertionError):proof.collect({}, {}, None)
            action.assert_not_called()

    def test_child_joins_before_socket_once_and_changes_only_netns(self):
        value=fixture(); w=value['worker']; events=[]; stream=Mock()
        stream.__enter__=Mock(return_value=stream);stream.__exit__=Mock(return_value=False)
        stream.connect.side_effect=OSError(errno.ENETUNREACH,'synthetic')
        def joined(fd,kind):events.append(('setns',fd,kind))
        def socket(*args):events.append(('socket',*args));return stream
        with patch.object(proof,'_identity',side_effect=[w['before'],w['joined'],w['after']]), patch.object(proof,'_nsfd',return_value=w['joined']['netns']), patch.object(proof.os,'setns',side_effect=joined,create=True), patch.object(proof.socket,'socket',side_effect=socket), patch.object(proof,'_topology',side_effect=[w['topology_before'],w['topology_after']]):
            actual=proof._probe(7,value['ip_pin'],value['expected']['proof_cgroup'])
        self.assertEqual(events,[('setns',7,proof.CLONE_NEWNET),('socket',proof.socket.AF_INET,proof.socket.SOCK_STREAM)])
        stream.connect.assert_called_once_with(('203.0.113.1',443))
        self.assertEqual(actual['connect']['errno'],errno.ENETUNREACH)

    def test_collect_inherits_only_netfd_and_retains_bookends(self):
        value=fixture(); expected=value['expected']
        prepared=dict(result='ok',inspection=dict(attempt=dict(id=expected['attempt'],artifact_digest=expected['artifact'],state='prepared',outcome='pending',binding=raw(expected['binding'])),robot_binding=None,robot_requests=[]))
        child=Mock(returncode=0,stderr=b'',stdout=raw(value['worker']).encode())
        with patch.object(proof.os,'geteuid',return_value=0), patch.object(proof.os,'setns',create=True), patch.object(proof.os,'pidfd_open',return_value=8), patch.object(proof.os,'open',return_value=9), patch.object(proof.os,'close') as close, patch.object(proof,'_checked_ip') as pin, patch.object(proof,'_identity',return_value=value['worker']['before']), patch.object(proof,'_bookend',return_value=value['before']) as book, patch.object(proof,'_nsfd',return_value=value['before']['task']['netns']), patch.object(proof.select,'select',return_value=([],[],[])), patch.object(proof.subprocess,'run',return_value=child) as run:
            report=proof.collect(prepared,expected,value['ip_pin'])
        self.assertEqual(report['before'],report['after']);self.assertEqual(book.call_count,3)
        self.assertEqual(pin.call_count,2);run.assert_called_once()
        self.assertEqual(run.call_args.kwargs['pass_fds'],(9,));self.assertTrue(run.call_args.kwargs['close_fds'])
        self.assertEqual(close.call_args_list,[unittest.mock.call(9),unittest.mock.call(8)])

    def test_dead_task_or_running_task_cannot_reach_child(self):
        value=fixture()
        with patch.object(proof.select,'select',return_value=([7],[],[])),patch.object(proof,'_command') as command:
            with self.assertRaises(AssertionError):proof._bookend(value['expected'],7,10**20)
            command.assert_not_called()
        table=('TASK PID STATUS\n'+value['expected']['attempt']+' 88 RUNNING\n').encode()
        with patch.object(proof.select,'select',return_value=([],[],[])),patch.object(proof,'_command',return_value=table),patch.object(proof,'process_identity') as identity:
            with self.assertRaises(AssertionError):proof._bookend(value['expected'],7,10**20)
            identity.assert_not_called()

    def test_nonloopback_topology_rejected_before_socket(self):
        value=fixture();t=copy.deepcopy(value['worker']['topology_before']);t['ipv4_routes']=raw([dict(dst='default',dev='eth0')])
        with patch.object(proof,'_identity',side_effect=[value['worker']['before'],value['worker']['joined']]), patch.object(proof,'_nsfd',return_value=value['worker']['joined']['netns']), patch.object(proof.os,'setns',create=True), patch.object(proof,'_topology',return_value=t),patch.object(proof.socket,'socket') as socket:
            with self.assertRaises(AssertionError):proof._probe(7,value['ip_pin'],value['expected']['proof_cgroup'])
            socket.assert_not_called()

if __name__=='__main__':unittest.main()
