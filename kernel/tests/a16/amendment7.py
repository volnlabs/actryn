#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Derive new numbered sources from exact frozen inputs; never build or launch."""
import argparse
import difflib
import hashlib
import json
import pathlib
import tomllib

HERE = pathlib.Path(__file__).resolve().parent
BASE = {
    'amendment6.toml': '95f37651fc5acbcb7e46b227ba8733d28cff86431e0faebf596ecd634a306809',
    'instrumentation4.toml': '4bd1c67206145c64f7ee1eacd54a0f49eab0ac41386295709d5026aeb83803ae',
    'workload.c': '14148767c53566ce0c274e23af49fdf51c3d900b2e95af7e762fb49eba8ca7a9',
    'protocol.h': '49a88ce9ecbcfce638fdddb033b780d2f0b60fd27d7c7595f576749db44e62f0',
    'common.h': 'bbafd17bb1e119eaee20035c4fb7788ed37df5d38272cee708409e1439c77acf',
    'engine.h': 'de1e33e1b57b38647bd9b55febcf4f28e8f941d868fc4f068e4d2adc18799ac7',
    '../../actryn_wire.c': '8873973e17c4fa8bd3a9a7875fb037faabbf391fadcfcc65159824cdc57362ca',
    '../../actryn_wire.h': '74956048d120c7b45726202a58701f8507c17f220a87cf6c958fd4c0421aa018',
    '../../actryn_control.h': '813b753af6f5dd2f23e9f255cce6b34bfd71b548a000ceb52db8d4b17b062133',
    '../../include/uapi/linux/actryn_authority.h': 'bab4e0b968193bef83b6e082c656cb8c2b101ccd04239729c48c731394d81261',
}
NEW = ('first_sample7.h', 'first_sample7_test.c', 'first_sample7.py', 'first_sample7_test.py', 'capture_guest7.py',
       'capture_guest7_test.py', 'amendment7.py', 'amendment7_test.py', 'dispatch7_test.py', 'prefix7_test.c', 'AMENDMENT7.md')

WAIT = r'''static struct first_sample7 first7;
static uint64_t wait_first7(int admin,int events)
{
 uint64_t now,lower=0; int ready;
 for(;;) {
  struct actryn_status s;
  drain(events); s=status(admin); now=a16_now(); ready=first7_ready(&first7,&s,now,&lower);
  assert(ready>=0); if(ready) break; sleep_ms(2);
 }
 emit("{\"type\":\"first_sample_ready\",\"trial\":%u,\"eligible_at_ns\":%llu,"
  "\"hello_sequence\":%llu,\"started_sequence\":%llu,\"hello_host_ns\":%llu,"
  "\"hello_controller_ns\":%llu,\"started_host_ns\":%llu,\"started_controller_ns\":%llu,"
  "\"controller_lower_ns\":%llu,\"settle_ns\":%llu}\n",trial,(unsigned long long)now,
  (unsigned long long)first7.hello_sequence,(unsigned long long)first7.started_sequence,
  (unsigned long long)first7.hello_host,(unsigned long long)first7.hello_ctl,
  (unsigned long long)first7.started_host,(unsigned long long)first7.started_ctl,
  (unsigned long long)lower,(unsigned long long)(now-first7.started_host));
 first7.enabled=false; return now;
}
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def replace(text, old, new, count=1):
    if text.count(old) != count:
        raise ValueError('frozen source edit count differs: ' + repr(old))
    return text.replace(old, new)


def workload(text):
    text = replace(text, '#include "common.h"', '#include "common.h"\n#include "first_sample7.h"')
    text = replace(text, 'static uint64_t observation_id;', 'static uint64_t observation_id;\nstatic struct first_sample7 first7;')
    text = replace(text, '   (unsigned long long)v.status.sequence,v.status.events_lost,bytes);',
                   '   (unsigned long long)v.status.sequence,v.status.events_lost,bytes);\n'
                   '  assert(!first7_event(&first7,&v));')  # Retain a rejected raw event before aborting.
    text = replace(text, 'static void child_trial(int parent_socket,int intent)',
                   WAIT.replace('static struct first_sample7 first7;\n', '') + '\nstatic void child_trial(int parent_socket,int intent)')
    text = replace(text, 'assert(!request(admin,&r));\n end=a16_now()+1500*A16_MS;',
                   'assert(!request(admin,&r));\n s=status(admin); first7_begin(&first7,&s);\n end=a16_now()+1500*A16_MS;')
    text = replace(text, ' r.opcode=ACTRYN_START; assert(!request(runtime,&r));',
                   ' assert(!first7_expect(&first7,&r));\n r.opcode=ACTRYN_START; assert(!request(runtime,&r));')
    text = replace(text, ' start=a16_now();', ' start=wait_first7(admin,events);')
    return replace(text, r'\"amendment\":2', r'\"amendment\":7')


def campaign(text):
    # Preserve lifecycle, retirement fences, denominators and finite waits.
    text = replace(text, 'import analyze\n', 'import analyze\nimport first_sample7\nimport campaign6\n')
    for old, new in (('capture_guest5', 'capture_guest7'),
                     ('instrumentation4', 'instrumentation7'), ('instrumentation5', 'amendment7')):
        text = text.replace(old, new)
    text = replace(text, "BUILD = '/opt/actryn-a16/build-amendment2'", "BUILD = '/opt/actryn-a16/build-amendment7'")
    text = replace(text, "'amendment': 2", "'amendment': 7")
    text = replace(text, 'unchanged amendment-2 workload required', 'amendment-7 common workload required')
    text = replace(text, '    return manifest\n', '    capture_guest7.verify_campaign(manifest, HERE)\n    return manifest\n')
    text = replace(text, "    begins = [row for row in rows if row['type'] == 'trial_begin']",
                   "    first_sample7.qualify(rows)\n    begins = [row for row in rows if row['type'] == 'trial_begin']")
    text = replace(text, '    environment3.verify(root)',
                   "    campaign6.verify_acceptance(root.parents[2], tomllib.loads((HERE / 'amendment6.toml').read_text())['amendment'])\n"
                   "    environment_here = environment3.HERE\n"
                   "    environment3.HERE = root.parents[2] / 'kernel/tests/a16'\n"
                   "    try:\n        environment3.verify(root)  # Verify original amendment2 inputs, not their numbered derivatives.\n"
                   "    finally:\n        environment3.HERE = environment_here")
    # Numbered directories/labels cannot consume or overwrite the failed pilot.
    text = text.replace('tracekernel01', 'tracekernel07').replace('traceuserspace01', 'traceuserspace07')
    text = text.replace("'instrumentation-' + arm + '01'", "'instrumentation-' + arm + '07'")
    text = text.replace("'trace' + arm + '01'", "'trace' + arm + '07'")
    text = text.replace("'comparison'", "'comparison7'").replace('comparison/block', 'comparison7/block7b')
    text = text.replace("f'block{i:02d}'", "f'block7b{i:02d}'")
    text = text.replace("f'block{block:02d}'", "f'block7b{block:02d}'")
    text = replace(text, '/AMENDMENT2', '/AMENDMENT7')
    anchor = " output, 'authority-load.log')"
    text = replace(text, anchor, anchor + "\n            selected = tomllib.loads((HERE / 'amendment6.toml').read_text())['amendment']\n"
                   "            remote.run(campaign6.loaded_command(selected['module_sha256'], bytes.fromhex(selected['module_note_hex']),\n"
                   "                       module=BUILD + '/kernel/actryn_authority.ko'), output, 'module16-loaded.log')")
    return text


def transform(name, data):
    text = data.decode()
    if name == 'workload.c':
        text = workload(text)
    elif name == 'campaign.py':
        text = campaign(text)
    elif name == 'capture/prefix.h':
        text = replace(text, '#define A16_FRAME_MAX 158U', '#define A16_FRAME_MAX 159U')
    elif name == 'capture/actryn_a16_capture.c':
        text = replace(text, 'data[A16_FRAME_MAX],reserved[26]', 'data[A16_FRAME_MAX],reserved[25]')
        text = replace(text, '"A16UART4",8); dump.header.version=cpu_to_le32(4)',
                       '"A16UART7",8); dump.header.version=cpu_to_le32(7)')
    elif name == 'dispatch.py':
        text = replace(text, '<6Qq4I158s26s', '<6Qq4I159s25s')
        text = replace(text, "magic != b'A16UART4' or version != 4", "magic != b'A16UART7' or version != 7")
        text = replace(text, 'requested > 158', 'requested > 159')
        text = replace(text, "return {'revision': 4,", "return {'revision': 7,")
    elif name == 'capture_guest.py':
        text = text.replace('instrumentation4', 'instrumentation7').replace('instrumentation-4', 'instrumentation-7')
        text = replace(text, "manifest['revision'] != 4", "manifest['revision'] != 7")
        text = text.replace('instrumentation amendment 4 required', 'instrumentation amendment 7 required')
    return text.encode()


def sources():
    pins = dict(BASE)
    for name in ('amendment6.toml', 'instrumentation4.toml'):
        raw = (HERE / name).read_bytes()
        if sha(raw) != BASE[name]:
            raise ValueError('frozen base manifest changed: ' + name)
        pins.update(tomllib.loads(raw.decode())['sources'])
    result, changes = {}, {}
    for name, expected in pins.items():
        raw = (HERE / name).read_bytes()
        if sha(raw) != expected:
            raise ValueError('frozen input changed: ' + name)
        result[name] = transform(name, raw)
        if result[name] != raw:
            changes[name] = {'original_sha256': sha(raw), 'derived_sha256': sha(result[name]),
                'diff': ''.join(difflib.unified_diff(raw.decode().splitlines(True), result[name].decode().splitlines(True),
                                                   fromfile='frozen/' + name, tofile='amendment7/' + name))}
    for name in NEW:
        result[name] = (HERE / name).read_bytes()
    return result, changes


def derive(output):
    files, changes = sources()
    output.mkdir()  # Existing or partial source attempt is retained, never overwritten.
    target = output / 'kernel/tests/a16'
    for name, data in files.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data)
    record = {'revision': 7, 'status': 'SOURCE_ONLY; NOT_FROZEN_FOR_EXECUTION',
              'derived_files': {name: sha(data) for name, data in files.items()}, 'changes': changes}
    with (output / 'DERIVATION7.json').open('x') as stream:
        json.dump(record, stream, indent=2); stream.write('\n')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('new_source_directory', type=pathlib.Path)
    args = parser.parse_args()
    result = derive(args.new_source_directory)
    print(json.dumps({'status': result['status'], 'changed_frozen_derivatives': list(result['changes'])}, indent=2))


if __name__ == '__main__':
    main()
