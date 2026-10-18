#!/usr/bin/env python3
"""Destructive scratch/clone VM only: overwrites config and changes registry/state ownership.

Never run on the retained qualification Server VM or an operator workstation.
Requires root and real observer/containerd; see START_CLEANUP.md before execution.
"""
import json, os, pathlib, select, shutil, socket, stat, struct, subprocess, sys, time
from guest_artifact import import_fixture


def rpc(request, path='/run/actryn/launcher.sock'):
    data=json.dumps(request).encode()
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(15);client.connect(path);client.sendall(struct.pack('!I',len(data))+data)
        def read(n):
            result=b''
            while len(result)<n:
                part=client.recv(n-len(result))
                assert part, 'unexpected RPC EOF'
                result+=part
            return result
        n=struct.unpack('!I',read(4))[0];assert n<=65536
        return json.loads(read(n))


def socket_ready(path):
    try:
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(.2);client.connect(path)
        return True
    except OSError:
        return False

def wait_for(predicate, timeout=10):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        value=predicate()
        if value:return value
        time.sleep(.05)
    raise AssertionError('deadline expired')


def empty_output(attempt):
    directory=pathlib.Path('/var/lib/actryn-server')/attempt
    assert (directory/'stdout.log').read_bytes()==b'', 'application stdout before Start'
    assert (directory/'stderr.log').read_bytes()==b'', 'application stderr before Start'


def rejected_start(attempt):
    rejected=rpc({'op':'start','attempt_id':attempt})
    assert rejected['result']=='error',rejected
    current=rpc({'op':'inspect','attempt_id':attempt})
    assert current['result']=='ok',current
    empty_output(attempt)
    print(json.dumps({'phase':'prestart-rejected','attempt_id':attempt,
        'reply':rejected,'inspection':current['inspection']}),flush=True)
    return current['inspection']['attempt']


def reaped_without_execution(attempt, taskfd):
    last=None;deadline=time.monotonic()+10
    while True:
        last=rpc({'op':'inspect','attempt_id':attempt})
        assert last['result']=='ok',last
        state=last['inspection']['attempt']['state']
        assert state in ('retiring','reaped'),('failed Start still live/prepared',last)
        empty_output(attempt)
        if state=='reaped':break
        assert time.monotonic()<deadline,('failed Start cleanup did not reap',last)
        time.sleep(.05)
    assert select.select([taskfd],[],[],0)[0], 'prepared task still alive after reap'
    assert not pathlib.Path('/sys/fs/cgroup/actryn',attempt).exists(), 'failed Start cgroup retained'
    assert not pathlib.Path('/run/actryn/brokers',attempt).exists(), 'failed Start broker directory retained'
    replay=rpc({'op':'start','attempt_id':attempt});assert replay['result']=='error',replay
    empty_output(attempt)


def main():
    assert os.geteuid()==0
    binary=pathlib.Path(sys.argv[1]).resolve()
    assert pathlib.Path('/run/actryn/observer.sock').exists(),'real observer required'
    assert pathlib.Path('/run/containerd/containerd.sock').exists(),'real containerd required'
    root=pathlib.Path('/var/lib/actryn-test-rootfs')
    (root/'bin').mkdir(parents=True,exist_ok=True)
    subprocess.run(['cc','-O2','-static','-Wall','-Wextra','-Werror','-o',str(root/'bin/agent'),str(pathlib.Path(__file__).with_name('launcher_agent.c'))],check=True)
    device=os.stat('/').st_dev
    block=pathlib.Path(f'/sys/dev/block/{os.major(device)}:{os.minor(device)}').resolve()
    io_device=(block.parent/'dev').read_text().strip() if (block/'partition').exists() else f'{os.major(device)}:{os.minor(device)}'
    config={'server_uid':991,'operator_uid':1000,'io_device':io_device,
        'artifacts':{}}
    pathlib.Path('/etc/actryn').mkdir(exist_ok=True)
    pathlib.Path('/etc/actryn/server.json').write_text(json.dumps(config))
    pathlib.Path('/etc/actryn/server.json').chmod(0o644)
    artifact=import_fixture(root/'bin/agent',*(sys.argv[2:4]))
    log=open('/root/actryn-launcher-test.log','w')
    process=subprocess.Popen([str(binary)],stdout=log,stderr=log)
    active=None;broker=None
    try:
        wait_for(lambda:socket_ready('/run/actryn/launcher.sock') or process.poll() is not None)
        assert process.poll() is None, 'launcher failed; see /root/actryn-launcher-test.log'
        refused=rpc({'op':'prepare','artifact_digest':'sha256:'+'b'*64});assert refused['result']=='error',refused
        prepared=rpc({'op':'prepare','artifact_digest':artifact});assert prepared['result']=='ok',prepared
        active=prepared['inspection']['attempt']['id']
        assert prepared['inspection']['attempt']['state']=='prepared'
        assert not os.path.lexists(f'/run/actryn/brokers/{active}/broker.sock')
        taskfd=os.pidfd_open(json.loads(prepared['inspection']['attempt']['binding'])['snapshot']['pid'])
        try:
            rejected_start(active)
            reaped_without_execution(active,taskfd)
            print(json.dumps({'test':'prestart-missing-broker-reaped','status':'PASS','attempt_id':active}),flush=True)
            active=None
        finally:os.close(taskfd)

        prepared=rpc({'op':'prepare','artifact_digest':artifact});assert prepared['result']=='ok',prepared
        active=prepared['inspection']['attempt']['id']
        assert prepared['inspection']['attempt']['state']=='prepared'
        taskfd=os.pidfd_open(json.loads(prepared['inspection']['attempt']['binding'])['snapshot']['pid'])
        try:
            broker=socket.socket(socket.AF_UNIX);broker.bind(f'/run/actryn/brokers/{active}/broker.sock');broker.listen(1)
            observer=pathlib.Path('/run/actryn/observer.sock')
            hidden=observer.with_name('observer.sock.start-cleanup-test')
            before=observer.lstat()
            def same_socket(path):
                value=path.lstat()
                return (value.st_dev,value.st_ino,value.st_mode,value.st_uid,value.st_gid,value.st_nlink)
            original=same_socket(observer)
            parent=observer.parent.lstat()
            assert observer.parent.resolve(strict=True)==observer.parent
            assert stat.S_ISDIR(parent.st_mode) and parent.st_uid==0 and not parent.st_mode&0o022
            assert stat.S_ISSOCK(before.st_mode) and before.st_uid==0 and not os.path.lexists(hidden)
            observer.rename(hidden)
            try:
                assert not os.path.lexists(observer) and same_socket(hidden)==original
                failed=rejected_start(active)
                assert failed['state']=='retiring' and failed['binding'] is not None,('failed observer must retain cleanup charge',failed)
                assert pathlib.Path('/sys/fs/cgroup/actryn',active).is_dir(), 'unconfirmed observer closure freed cgroup identity'
                wait_for(lambda:select.select([taskfd],[],[],0)[0])
                empty_output(active)
            finally:
                # Restore only the same original socket, never overwrite a replacement.
                assert not os.path.lexists(observer) and same_socket(hidden)==original
                hidden.rename(observer)
                assert same_socket(observer)==original and not os.path.lexists(hidden)
            reaped_without_execution(active,taskfd)
            print(json.dumps({'test':'prestart-unreachable-observer-retained-then-reaped','status':'PASS','attempt_id':active}),flush=True)
            active=None
        finally:
            os.close(taskfd)
            if broker:broker.close();broker=None

        # Fresh preparation preserves the original healthy positive control.
        prepared=rpc({'op':'prepare','artifact_digest':artifact});assert prepared['result']=='ok',prepared
        active=prepared['inspection']['attempt']['id']
        assert prepared['inspection']['attempt']['state']=='prepared'
        output=pathlib.Path('/var/lib/actryn-server')/active/'stdout.log'
        assert output.read_bytes()==b'', 'application executed before start'
        broker=socket.socket(socket.AF_UNIX);broker.bind(f'/run/actryn/brokers/{active}/broker.sock');broker.listen(1)
        started=rpc({'op':'start','attempt_id':active});assert started['result']=='ok',started
        wait_for(lambda:b'AGENT_STARTED' in output.read_bytes())
        running=rpc({'op':'inspect','attempt_id':active})['inspection']['attempt']
        identity=json.loads(running['binding'])['snapshot']
        runningfd=os.pidfd_open(identity['pid'])
        capacity=None;capacity_broker=None
        try:
            duplicate=rpc({'op':'start','attempt_id':active});assert duplicate['result']=='error',duplicate
            assert rpc({'op':'inspect','attempt_id':active})['inspection']['attempt']==running, 'duplicate Start changed running attempt'
            prepared=rpc({'op':'prepare','artifact_digest':artifact});assert prepared['result']=='ok',prepared
            capacity=prepared['inspection']['attempt']['id']
            expected=prepared['inspection']['attempt'];assert expected['state']=='prepared'
            capacity_broker=socket.socket(socket.AF_UNIX)
            capacity_broker.bind(f'/run/actryn/brokers/{capacity}/broker.sock');capacity_broker.listen(1)
            denied=rpc({'op':'start','attempt_id':capacity})
            assert denied=={'result':'error','message':'active capacity exhausted'},denied
            assert rpc({'op':'inspect','attempt_id':capacity})['inspection']['attempt']==expected, 'capacity refusal changed preparation'
            empty_output(capacity)
            assert not select.select([runningfd],[],[],0)[0], 'capacity refusal killed running task'
            assert rpc({'op':'inspect','attempt_id':active})['inspection']['attempt']==running, 'capacity refusal changed running identity'
            retiring=capacity;capacity=None  # Consume before Stop; never retry an uncertain reply.
            stopped=rpc({'op':'stop','attempt_id':retiring});assert stopped['result']=='ok',stopped
            assert stopped['inspection']['attempt']['state']=='reaped',stopped
            assert not select.select([runningfd],[],[],0)[0], 'staged cleanup killed running task'
            print(json.dumps({'test':'active-capacity-refusal-preserves-preparation-and-running-task','status':'PASS','attempt_id':retiring,'running_attempt_id':active}),flush=True)
        finally:
            if capacity:
                try:print('cleanup:',rpc({'op':'stop','attempt_id':capacity}))
                except Exception as error:print('cleanup pending:',error)
            if capacity_broker:capacity_broker.close()
            os.close(runningfd)
        stopped=rpc({'op':'stop','attempt_id':active});assert stopped['result']=='ok',stopped
        assert stopped['inspection']['attempt']['state']=='reaped',stopped
        assert not pathlib.Path('/sys/fs/cgroup/actryn',active).exists(),'descendant cgroup retained'
        replay=rpc({'op':'start','attempt_id':active});assert replay['result']=='error',replay
        print(json.dumps({'test':'actual-containerd-prepare-start-stop','status':'PASS','attempt_id':active,
            'evidence':'/root/actryn-launcher-test.log','stdout':str(output)}))
        active=None
    finally:
        if active:
            try: print('cleanup:',rpc({'op':'stop','attempt_id':active}))
            except Exception as error: print('cleanup pending:',error)
        if broker:broker.close()
        process.terminate()
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:process.kill();process.wait()
        log.close()

if __name__=='__main__':main()
