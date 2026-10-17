#!/usr/bin/env python3
"""Fixed, test-only launcher interposition; never an installed release component."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time

import guest_capacity as common

require=common.require
CONTROL=Path('/run/actryn/a08-pressure')
LIBRARY=Path('/opt/actryn-a08-pressure/fault.so')
LEGACY_LIBRARY=CONTROL/'fault.so'
DROPIN=Path('/run/systemd/system/actryn-launcher.service.d/90-a08-pressure.conf')
OVERRIDE=b'''# TEST ONLY: instrumented A08 production-path evidence, not release qualification.
[Service]
ExecStart=
ExecStart=/usr/bin/env LD_PRELOAD=/opt/actryn-a08-pressure/fault.so /usr/bin/actryn-launcher
'''
PROPERTIES=('ExecStart','ExecStartPre','ExecStopPost','Type','NotifyAccess','TimeoutStartUSec',
    'TimeoutStopUSec','Restart','RestartUSec','User','Group','UMask','NoNewPrivileges',
    'CapabilityBoundingSet','AmbientCapabilities','ProtectSystem','ProtectHome','ProtectKernelModules',
    'ProtectKernelTunables','ProtectKernelLogs','ReadWritePaths','InaccessiblePaths','PrivateTmp',
    'PrivateDevices','RestrictAddressFamilies','RestrictNamespaces','RestrictSUIDSGID',
    'LockPersonality','MemoryDenyWriteExecute','TasksMax','MemoryMax','LimitNOFILE',
    'CPUQuotaPerSecUSec','CPUQuotaPeriodUSec','DevicePolicy','DeviceAllow','SystemCallFilter',
    'LoadCredential','LoadCredentialEncrypted','FragmentPath')


def command(argv, timeout=15):
    try:
        result=subprocess.run(argv,capture_output=True,timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise AssertionError({'argv':argv,'outcome_unknown':True,'timeout_seconds':timeout,
            'stdout':(error.stdout or b'')[:65536].decode(errors='replace'),
            'stderr':(error.stderr or b'')[:65536].decode(errors='replace'),
            'automatic_retry':False}) from error
    require(len(result.stdout)<=1024*1024 and len(result.stderr)<=65536,'command output bound')
    require(result.returncode==0,{'argv':argv,'code':result.returncode,
            'stdout':result.stdout.decode(errors='replace'),'stderr':result.stderr.decode(errors='replace')})
    return result.stdout.decode()


def stable_commands(value):
    # systemctl show includes per-invocation observations in command descriptors.
    return re.sub(r' ?; (?:start_time|stop_time|pid|code|status)=[^;}]*', '', value)


def properties():
    shown=tuple(name for name in PROPERTIES if name!='DeviceAllow')
    raw=command(['systemctl','show','actryn-launcher','--property='+','.join(shown)])
    result=dict(line.split('=',1) for line in raw.splitlines())
    require(set(result)==set(shown),'incomplete inherited service properties')
    # systemctl omits an empty DeviceAllow and prints repeated keys for multiple
    # entries. Read the typed array instead of losing either case in a dict.
    allowed=json.loads(command(['/usr/bin/busctl','--system','--json=short','get-property',
        'org.freedesktop.systemd1','/org/freedesktop/systemd1/unit/actryn_2dlauncher_2eservice',
        'org.freedesktop.systemd1.Service','DeviceAllow']))
    require(isinstance(allowed,dict) and set(allowed)=={'type','data'}
            and allowed['type']=='a(ss)' and isinstance(allowed['data'],list)
            and all(isinstance(entry,list) and len(entry)==2
                    and all(isinstance(value,str) for value in entry) for entry in allowed['data']),
            'invalid typed DeviceAllow property')
    result['DeviceAllow']=allowed['data']
    for key in ('ExecStart','ExecStartPre','ExecStopPost'): result[key]=stable_commands(result[key])
    return result


def protected_file(path, cap):
    path=Path(path)
    require(path.is_absolute(),'absolute fixture file required')
    for parent in reversed(path.parents):
        info=parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022,
                'unprotected fixture ancestor: '+str(parent))
    info=path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022 and info.st_nlink==1,
            'unprotected regular fixture file: '+str(path))
    return common.read_bounded(path,cap)


def protected_directory(path):
    for directory in [*reversed(Path(path).parents),Path(path)]:
        info=directory.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022,
                'unprotected fixture directory: '+str(directory))


def library_users(proc_root=Path('/proc')):
    pids=[p for p in proc_root.iterdir() if p.name.isdigit()]
    require(len(pids)<=512,'guest process inventory exceeds fixture bound')
    users=set(); executable=set(); legacy=set()
    identity=LIBRARY.lstat() if LIBRARY.exists() else None
    for pid in pids:
        try: raw=common.read_bounded(pid/'maps',1024*1024)
        except (FileNotFoundError,ProcessLookupError): continue
        for line in raw.decode().splitlines():
            fields=line.split(None,5)
            if len(fields)!=6:continue
            path=fields[5]; original=path.removesuffix(' (deleted)')
            if original not in (str(LIBRARY),str(LEGACY_LIBRARY)):continue
            users.add(int(pid.name))
            if original==str(LEGACY_LIBRARY):legacy.add(int(pid.name));continue
            if identity is not None and path==str(LIBRARY) and 'x' in fields[1] \
                    and int(fields[4])==identity.st_ino \
                    and tuple(int(part,16) for part in fields[3].split(':'))==(os.major(identity.st_dev),os.minor(identity.st_dev)):
                executable.add(int(pid.name))
    return {'library_users':sorted(users),'library_executable_users':sorted(executable),
            'legacy_library_users':sorted(legacy)}


def preflight(manifest_pin):
    require(os.geteuid()==0 and os.uname().release=='6.12.111+deb13-amd64'
            and os.uname().machine=='x86_64'
            and Path('/etc/hostname').read_text().strip().startswith('actryn-install-server'),
            'only the selected disposable installed server guest is allowed')
    require(re.fullmatch('[0-9a-f]{64}',manifest_pin),'manifest pin')
    slot=Path('/opt/actryn/server/current').resolve()
    require(slot.name=='payload' and slot.parent.name==manifest_pin,'installed immutable slot changed')
    raw=protected_file(slot.parent/'manifest.json',1024*1024)
    require(hashlib.sha256(raw).hexdigest()==manifest_pin,'manifest digest')
    manifest=json.loads(raw); require(manifest['role']=='server','installed role')
    entries={v['path']:v for v in manifest['files']}; services={}
    for unit in ('actryn-launcher','actryn-serverd','actryn-observer'):
        state=dict(line.split('=',1) for line in command(['systemctl','show',unit,
                   '--property=MainPID,ActiveState,SubState']).splitlines())
        pid=int(state['MainPID'])
        require(pid>1 and state['ActiveState']=='active' and state['SubState']=='running','service not ready')
        executable=Path(f'/proc/{pid}/exe').resolve()
        require(executable==slot/'bin'/unit,'service outside selected immutable slot')
        digest=hashlib.sha256(protected_file(executable,128*1024*1024)).hexdigest()
        require(digest==entries['bin/'+unit]['sha256'],'service hash differs from manifest')
        start=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19]
        services[unit]={'pid':pid,'start_ticks':int(start),'sha256':digest,'path':str(executable)}
    config=protected_file('/etc/actryn/server.json',65536)
    result={'manifest':manifest_pin,'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'services':services,'config_sha256':hashlib.sha256(config).hexdigest(),
            'properties':properties(),'unit_text':command(['systemctl','cat','actryn-launcher']),
            **library_users()}
    if CONTROL.exists():
        info=CONTROL.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid==0 and stat.S_IMODE(info.st_mode)==0o700,
                'fixture control directory ownership')
    if LIBRARY.exists() or LIBRARY.is_symlink():
        protected_directory(LIBRARY.parent)
        require(stat.S_IMODE(LIBRARY.parent.lstat().st_mode)==0o700
                and stat.S_IMODE(LIBRARY.lstat().st_mode)==0o600,'persistent fixture permissions')
        result['library_sha256']=hashlib.sha256(protected_file(LIBRARY,1024*1024)).hexdigest()
    return result


def validate_instrumentation(record, current):
    require(current['manifest']==record['manifest'] and current['library_sha256']==record['library_sha256']
            and current['library_users']==current['library_executable_users']==[current['services']['actryn-launcher']['pid']]
            and current['legacy_library_users']==[],
            'only the selected launcher may executably map the pinned persistent fixture')
    require(current['properties']==record['instrumented']['properties'],'effective fixture service changed')
    old=record['original']['properties']; new=current['properties']
    require(set(old)==set(new) and all(new[k]==v for k,v in old.items() if k!='ExecStart')
            and new['ExecStart']!=old['ExecStart'],'inherited security/preflight changed')


def verify_instrumented(record,current):
    require(protected_file(DROPIN,4096)==OVERRIDE,'test override changed')
    require(current['config_sha256']==record['original']['config_sha256']
            and current['boot_id']==record['original']['boot_id'],'config or boot changed')
    validate_instrumentation(record,current)


def quiescent():
    rows=common.Campaign(Path('/unused'), 'unused').stores()
    require(all(state=='reaped' for table in rows.values() for state in table.values()),'outstanding attempt prevents service change')
    require(not command(['ctr','--namespace','actryn','tasks','list','--quiet']).strip(),'containerd task remains')
    require(not (CONTROL/'control').exists(),'fault control is still armed')
    return rows


def write_new(path,data,mode=0o600):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,'wb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())


def record(output,name,value):
    write_new(output/name,(json.dumps(value,indent=2)+'\n').encode())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('install','restore'))
    parser.add_argument('--manifest',required=True)
    parser.add_argument('--library',type=Path)
    parser.add_argument('--library-sha256')
    parser.add_argument('--fixture-record',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    initial=preflight(args.manifest); before=quiescent()
    os.umask(0o077); args.output.mkdir(mode=0o700,parents=True,exist_ok=False)
    record(args.output,'intent.json',{'action':args.action,'initial':initial,'stores':before,
            'instrumented_production_path':True,'automatic_retries':False,
            'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    try:
        if args.action=='install':
            require(args.library and re.fullmatch('[0-9a-f]{64}',args.library_sha256 or ''),'library pin required')
            require(not CONTROL.exists() and not CONTROL.is_symlink() and not DROPIN.exists() and not DROPIN.is_symlink()
                    and not LIBRARY.parent.exists() and not LIBRARY.parent.is_symlink()
                    and not initial['library_users'], 'fixture already exists')
            library=protected_file(args.library,1024*1024)
            require(hashlib.sha256(library).hexdigest()==args.library_sha256,'fixture library hash')
            require(library[:6]==b'\x7fELF\x02\x01','native fixture ELF required')
            command(['systemctl','stop','actryn-serverd','actryn-launcher'],70)
            quiescent()
            protected_directory(CONTROL.parent)
            protected_directory(DROPIN.parent.parent)
            protected_directory(LIBRARY.parent.parent)
            require(not os.statvfs(LIBRARY.parent.parent).f_flag&os.ST_NOEXEC,'persistent fixture mount is noexec')
            CONTROL.mkdir(mode=0o700)
            LIBRARY.parent.mkdir(mode=0o700)
            write_new(LIBRARY,library)
            DROPIN.parent.mkdir(mode=0o755,exist_ok=True)
            protected_directory(DROPIN.parent)
            write_new(DROPIN,OVERRIDE,0o644)
            command(['systemctl','daemon-reload'])
            # Normal installed gate is retained. Rejection is a failed setup, never bypassed.
            command(['systemctl','start','actryn-launcher'],40)
            command(['systemctl','start','actryn-serverd'],40)
            current=preflight(args.manifest)
            record(args.output,'instrumented-observed.json',current)
            result={'manifest':args.manifest,'library_sha256':args.library_sha256,
                    'original':initial,'instrumented':current}
            verify_instrumented(result,current)
            record(args.output,'fixture.json',result)
        else:
            require(args.fixture_record is not None,'original fixture record required')
            original=json.loads(protected_file(args.fixture_record,65536))
            verify_instrumented(original,initial)
            command(['systemctl','stop','actryn-serverd','actryn-launcher'],70)
            quiescent()
            require(protected_file(DROPIN,4096)==OVERRIDE,'owned override changed before removal')
            DROPIN.unlink()  # Keep library, latched identity and event files for evidence.
            command(['systemctl','daemon-reload'])
            command(['systemctl','start','actryn-launcher'],40)
            command(['systemctl','start','actryn-serverd'],40)
            current=preflight(args.manifest)
            record(args.output,'restored-observed.json',current)
            require(not current['library_users'] and not current['library_executable_users']
                    and not current['legacy_library_users'] and current['properties']==original['original']['properties']
                    and current['unit_text']==original['original']['unit_text']
                    and current['config_sha256']==original['original']['config_sha256'],
                    'original effective service configuration not restored exactly')
            require(quiescent()==before,'restoration changed retained accounting')
            record(args.output,'restored.json',current)
        record(args.output,'PASS.json',{'action':args.action,'monotonic_ns':time.monotonic_ns()})
    except BaseException as error:
        record(args.output,'FAILED.json',{'action':args.action,'error':repr(error),
                'automatic_retry':False,'required_next_action':'retain state; separately review cleanup'})
        raise


if __name__=='__main__': main()
