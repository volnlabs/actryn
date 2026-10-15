"""Build/import the test binary through the same verified artifact path as release assets."""
import json,os,pathlib,subprocess,tempfile

def import_fixture(binary,importer='/usr/bin/actryn-artifact',builder='/usr/share/actryn/agent/build_oci.py'):
    for path in ['/var/lib/actryn-server','/var/lib/actryn-server/broker']:pathlib.Path(path).mkdir(exist_ok=True)
    config=json.loads(pathlib.Path('/etc/actryn/server.json').read_text())
    parent=pathlib.Path(tempfile.mkdtemp(prefix='actryn-fixture-import-',dir='/root'))
    result=json.loads(subprocess.check_output(['python3',builder,'--agent',str(binary),'--out',str(parent/'oci')]))
    imported=json.loads(subprocess.check_output([importer,'import','--layout',str(parent/'oci'),'--digest',result['artifact_digest']]))
    assert imported['artifact_digest']==result['artifact_digest']
    return result['artifact_digest']
