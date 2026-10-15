#!/usr/bin/env python3
"""Run only as root in the disposable server VM with real containerd + observer."""
import json,os,pathlib,shutil,subprocess,sys,time
from guest_launcher import rpc,wait_for,socket_ready
from guest_artifact import import_fixture

assert os.geteuid()==0
install=pathlib.Path('/usr/local/libexec/actryn-test')
install.mkdir(parents=True,exist_ok=True)
binary=install/'actryn-launcher';server_binary=install/'actryn-serverd'
for source,destination in [(sys.argv[1],binary),(sys.argv[2],server_binary)]:
    if pathlib.Path(source).resolve()!=destination:
        shutil.copyfile(source,destination)
    destination.chmod(0o755)
root=pathlib.Path('/var/lib/actryn-broker-test-rootfs')
for name in ['bin','tmp','dev','proc','run/actryn-broker']:(root/name).mkdir(parents=True,exist_ok=True)
source=pathlib.Path(__file__).with_name('broker_agent.c')
subprocess.run(['cc','-O2','-static','-Wall','-Wextra','-Werror','-o',str(root/'bin/agent'),str(source)],check=True)
device=os.stat('/').st_dev
block=pathlib.Path(f'/sys/dev/block/{os.major(device)}:{os.minor(device)}').resolve()
io_device=(block.parent/'dev').read_text().strip() if (block/'partition').exists() else f'{os.major(device)}:{os.minor(device)}'
config={'server_uid':991,'operator_uid':1000,'io_device':io_device,'artifacts':{}}
pathlib.Path('/etc/actryn').mkdir(exist_ok=True)
pathlib.Path('/etc/actryn/server.json').write_text(json.dumps(config))
pathlib.Path('/etc/actryn/server.json').chmod(0o644)
artifact=import_fixture(root/'bin/agent',*(sys.argv[3:5]))
logs=[open('/root/actryn-broker-launcher.log','w'),open('/root/actryn-broker-server.log','w')]
launcher=subprocess.Popen([str(binary)],stdout=logs[0],stderr=logs[0]);server=None;active=None
try:
    wait_for(lambda:socket_ready('/run/actryn/launcher.sock') or launcher.poll() is not None)
    assert launcher.poll() is None,'launcher failed; inspect /root/actryn-broker-launcher.log'
    server=subprocess.Popen([str(server_binary)],stdout=logs[1],stderr=logs[1],user=991,group=991,extra_groups=[])
    wait_for(lambda:socket_ready('/run/actryn-server/server.sock') or server.poll() is not None)
    assert server.poll() is None,'server failed; inspect /root/actryn-broker-server.log'
    endpoint='/run/actryn-server/server.sock'
    for denied_endpoint,uid in [('/run/actryn/launcher.sock',1000),(endpoint,65534)]:
        denial="""import socket,struct,json,sys
s=socket.socket(socket.AF_UNIX); s.settimeout(2); s.connect(sys.argv[1])
b=json.dumps({'op':'inspect','attempt_id':'0'*32}).encode()
try:
    s.sendall(struct.pack('!I',len(b))+b)
    assert s.recv(4)==b''
except (ConnectionResetError,BrokenPipeError):
    pass
"""
        subprocess.run(['python3','-c',denial,denied_endpoint],user=uid,group=uid,extra_groups=[],check=True)
    response=rpc({'op':'prepare','artifact_digest':artifact},endpoint);assert response['result']=='ok',response
    active=response['inspection']['attempt']['id']
    response=rpc({'op':'start','attempt_id':active},endpoint);assert response['result']=='ok',response
    output=pathlib.Path('/var/lib/actryn-server')/active/'stdout.log'
    wait_for(lambda:b'BROKER_ACCEPTANCE_PASS' in output.read_bytes(),15)
    inspection=rpc({'op':'inspect','attempt_id':active},endpoint)['inspection']
    assert len(inspection['denials'])==1,inspection
    assert inspection['calls'][0]['state']=='settled',inspection
    result=rpc({'op':'result','attempt_id':active,'request_key':'offline-1'},endpoint)
    assert result['result']=='call_result' and result['value']['origin']=='server_attested',result
    assert result['value']['output']['left_delta_ticks']==10,result
    stopped=rpc({'op':'stop','attempt_id':active},endpoint);assert stopped['result']=='ok',stopped
    assert stopped['inspection']['attempt']['state']=='reaped',stopped
    result=rpc({'op':'result','attempt_id':active,'request_key':'offline-1'},endpoint)
    assert result['result']=='call_result' and result['value'] is None,result
    assert not pathlib.Path('/sys/fs/cgroup/actryn',active).exists()
    print(json.dumps({'test':'actual-native-sandbox-broker','status':'PASS','attempt_id':active,'stdout':str(output)}));active=None
finally:
    if active:
        try:print('cleanup:',rpc({'op':'stop','attempt_id':active},'/run/actryn-server/server.sock'))
        except Exception as error:print('cleanup pending:',error)
    for process in [server,launcher]:
        if process:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()
    for log in logs:log.close()
