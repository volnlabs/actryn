#!/usr/bin/env python3
"""Destructive only inside the disposable Debian server VM; requires root and real observer/containerd."""
import json, os, pathlib, shutil, socket, struct, subprocess, sys, time


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


def main():
    assert os.geteuid()==0
    binary=pathlib.Path(sys.argv[1]).resolve()
    assert pathlib.Path('/run/actryn/observer.sock').exists(),'real observer required'
    assert pathlib.Path('/run/containerd/containerd.sock').exists(),'real containerd required'
    root=pathlib.Path('/var/lib/actryn-test-rootfs')
    for name in ['bin','tmp','dev','proc','run/actryn-broker']:(root/name).mkdir(parents=True,exist_ok=True)
    shutil.copyfile('/usr/bin/busybox',root/'bin/busybox');(root/'bin/busybox').chmod(0o755)
    (root/'bin/sh').symlink_to('busybox') if not (root/'bin/sh').exists() else None
    artifact='sha256:'+'a'*64
    device=os.stat('/').st_dev
    block=pathlib.Path(f'/sys/dev/block/{os.major(device)}:{os.minor(device)}').resolve()
    io_device=(block.parent/'dev').read_text().strip() if (block/'partition').exists() else f'{os.major(device)}:{os.minor(device)}'
    config={'server_uid':991,'operator_uid':1000,'io_device':io_device,
        'artifacts':{artifact:{'rootfs':str(root),'argv':['/bin/busybox','sh','-c','echo AGENT_STARTED; /bin/busybox cat /proc/self/status; /bin/busybox sleep 30']}}}
    pathlib.Path('/etc/actryn').mkdir(exist_ok=True)
    pathlib.Path('/etc/actryn/server.json').write_text(json.dumps(config))
    pathlib.Path('/etc/actryn/server.json').chmod(0o644)
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
        output=pathlib.Path('/var/lib/actryn-server')/active/'stdout.log'
        assert output.read_bytes()==b'', 'application executed before start'
        broker=socket.socket(socket.AF_UNIX);broker.bind(f'/run/actryn/brokers/{active}/broker.sock');broker.listen(1)
        started=rpc({'op':'start','attempt_id':active});assert started['result']=='ok',started
        wait_for(lambda:b'AGENT_STARTED' in output.read_bytes())
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
