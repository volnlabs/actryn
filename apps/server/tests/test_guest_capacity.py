import importlib.util
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('guest_capacity', Path(__file__).with_name('guest_capacity.py'))
campaign = importlib.util.module_from_spec(spec)
spec.loader.exec_module(campaign)


def complete_export(started=True):
    """The six-artifact wire shape observed in installed-server positive03."""
    attempt, artifact = 'b' * 32, 'sha256:' + 'a' * 64
    observer = {'collector_epoch': 'f66de495-301b-42e7-a39f-1cea5bb71c60',
                'ready': True, 'lost': 0, 'sequence': 0,
                'coverage': ['process.lifecycle', 'syscall.openat', 'syscall.connect',
                             'syscall.bpf', 'syscall.perf_event_open', 'syscall.mount',
                             'syscall.unshare', 'syscall.setns']}
    binding = {'ambiguous_create': False, 'boot_id': 'a917164d-7c9a-4f72-a38c-4c68ce1ffad5',
               'cgroup_id': 6653, 'observer': observer,
               'device_policy': {'program_id': 244, 'instruction_sha256':
                                 'c7b12a60a8b611b7b760af1aa2628a1b884f8ebf3ee6a85c48fe82b9910d8e05'},
               'snapshot': {'pid': 2245, 'start_ticks': 46207, 'cgroup': '/actryn/' + attempt,
                            'uid': 65532, 'gid': 65532, 'capabilities': 0,
                            'no_new_privileges': True, 'seccomp_mode': 2,
                            'private_namespaces': True, 'root_readonly': True, 'network_routes': 0,
                            'unexpected_mounts': [], 'device_programs': [244],
                            'device_programs_direct': [244], 'device_attach_flags': 2,
                            'memory_max': 268435456, 'pids_max': 64,
                            'cpu_max': '50000 100000\n',
                            'io_max': '254:0 rbps=1048576 wbps=1048576 riops=128 wiops=128\n'}}
    final_observer = copy.deepcopy(observer); final_observer['sequence'] = 170
    resources = {'captured_boottime_ms': 462464, 'classification': 'observed_cgroup_v2_counters',
                 'stage': 'after_descendants_empty_before_runtime_delete', 'unavailable': [],
                 'counters': {'cpu.stat': 'usage_usec 11753\n', 'io.stat': '254:0 \n',
                              'memory.current': '65536\n', 'memory.events': 'oom_kill 0\n',
                              'memory.peak': '3657728\n', 'pids.current': '0\n',
                              'pids.events': 'max 0\n', 'pids.peak': '6\n'}}
    proposal = {'event': 'preview_proposal', 'authority_issued': False,
                'value': {'origin': 'server_attested', 'attempt_id': attempt,
                          'model': 'offline-fixture', 'robot_handle': None}}
    logs = {'stdout': (json.dumps(proposal).encode() + b'\n') if started else b'', 'stderr': b''}
    call = {'id': 'c' * 32, 'request_key': 'preview-1', 'state': 'settled',
            'publication_closed': True, 'consumed_tokens': 0, 'deadline_ms': 492288}
    outcome = {'id': attempt, 'artifact_digest': artifact, 'state': 'reaped',
               'outcome': 'cancelled', 'deadline_ms': 582269, 'binding': None}
    inspection = {'attempt': {**outcome, 'binding': json.dumps(binding)},
                  'calls': [call] if started else [], 'denials': [], 'denials_omitted': 0,
                  'evidence_gaps': [], 'robot_binding': None, 'robot_requests': []}
    contents = {'attempt': outcome, 'runtime_binding': binding,
                'runtime_facts': {'observer': final_observer, 'observer_health_unavailable': False,
                                  'resources': resources},
                'broker': {'classification': 'broker_application_policy_and_delegated_accounting',
                           'attempt_state': 'reaped', 'attempt_outcome': 'cancelled',
                           'calls': inspection['calls'], 'evidence_gaps': [], 'policy_denials': [],
                           'policy_denials_retained': 0}}
    for name, raw in logs.items():
        contents[name] = {'classification': 'untrusted_agent_output_not_policy_attribution',
                          'file_complete': True, 'source_truncated': False,
                          'retained_bytes': len(raw),
                          'retained_sha256': 'sha256:' + hashlib.sha256(raw).hexdigest(),
                          'tail_encoding': 'hex', 'tail': raw[-2048:].hex(), 'tail_omitted_bytes': 0}
    bundle = {'schema': 'actryn.server.evidence.v1', 'attempt_id': attempt,
              'execution_replay_eligible': False, 'omissions': [],
              'artifacts': [{'name': name, 'content': copy.deepcopy(content)}
                            for name, content in contents.items()]}
    rehash(bundle)
    summary = {'status': final_observer, 'local_lost': 0, 'retained_bytes': 63965}
    return bundle, attempt, artifact, binding, inspection, logs, summary, 63965, started


def rehash(bundle):
    for item in bundle['artifacts']:
        raw = json.dumps(item['content'], sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
        item.update(bytes=len(raw), sha256='sha256:' + hashlib.sha256(raw).hexdigest())


class CapacityCampaignTests(unittest.TestCase):
    def test_expected_denial_is_opt_in_exact_and_default_stays_empty(self):
        args = list(complete_export())
        denied = {'request_key': 'denied-1', 'method': 'admin.grant', 'reason': 'method_not_allowed'}
        broker = next(v['content'] for v in args[0]['artifacts'] if v['name'] == 'broker')
        broker.update(policy_denials=[denied], policy_denials_retained=1)
        args[4]['denials'] = [denied]
        rehash(args[0])
        with self.assertRaises(AssertionError): campaign.validate_export(*args)
        campaign.validate_export(*args, expected_denials=[denied])
        for wrong in ([], [{'request_key': 'other', 'method': 'admin.grant'}], [denied, denied]):
            with self.subTest(wrong=wrong), self.assertRaises(AssertionError):
                campaign.validate_export(*args, expected_denials=wrong)

    def test_fixed_device_proof_is_required_even_when_runtime_binding_hashes_agree(self):
        for fault in ('missing', 'hash', 'id_bool', 'id_overflow', 'direct_missing',
                      'effective_missing', 'flags_zero', 'flags_override', 'flags_bool',
                      'duplicate', 'nonpositive', 'overflow', 'unsorted', 'not_subset'):
            args = list(complete_export())
            binding = args[3]
            snapshot = binding['snapshot']
            if fault == 'missing': del binding['device_policy']
            elif fault == 'hash': binding['device_policy']['instruction_sha256'] = '0' * 64
            elif fault == 'id_bool': binding['device_policy']['program_id'] = True
            elif fault == 'id_overflow': binding['device_policy']['program_id'] = 2**32
            elif fault == 'direct_missing': del snapshot['device_programs_direct']
            elif fault == 'effective_missing': snapshot['device_programs'] = [245]
            elif fault == 'flags_zero': snapshot['device_attach_flags'] = 0
            elif fault == 'flags_override': snapshot['device_attach_flags'] = 1
            elif fault == 'flags_bool': snapshot['device_attach_flags'] = True
            elif fault == 'duplicate': snapshot['device_programs_direct'] = [244, 244]
            elif fault == 'nonpositive': snapshot['device_programs'] = [0, 244]
            elif fault == 'overflow': snapshot['device_programs'] = list(range(1, 66))
            elif fault == 'unsorted': snapshot['device_programs'] = [245, 244]
            else: snapshot['device_programs_direct'] = [244, 245]
            args[4]['attempt']['binding'] = json.dumps(binding)
            next(item for item in args[0]['artifacts'] if item['name'] == 'runtime_binding')['content'] = binding
            rehash(args[0])
            with self.subTest(fault=fault), self.assertRaises(AssertionError):
                campaign.validate_export(*args)

    def test_fixed_instruction_hash_matches_authored_source(self):
        import ast
        import re
        source = Path(__file__).parents[1] / 'bpf/device_policy.insns'
        rows = ast.literal_eval(re.sub(r'//[^\n]*', '', source.read_text()))
        self.assertTrue(rows and all(len(row) == 8 for row in rows))
        self.assertEqual(hashlib.sha256(bytes(value for row in rows for value in row)).hexdigest(),
                         campaign.DEVICE_POLICY_SHA256)

    def test_complete_started_and_cancelled_prepared_exports_pass(self):
        for started in (False, True):
            campaign.validate_export(*complete_export(started))

    def test_missing_duplicate_or_omitted_export_cannot_pass(self):
        for fault in ('empty', 'duplicate', 'missing', 'omission', 'schema', 'replay', 'bad_hash'):
            args = list(complete_export())
            bundle = args[0]
            if fault == 'empty': bundle['artifacts'] = []
            elif fault == 'duplicate': bundle['artifacts'][-1] = copy.deepcopy(bundle['artifacts'][0])
            elif fault == 'missing': bundle['artifacts'].pop()
            elif fault == 'omission': bundle['omissions'] = [{'artifact': 'stdout', 'reason': 'unavailable'}]
            elif fault == 'schema': bundle['schema'] = 'unknown'
            elif fault == 'replay': bundle['execution_replay_eligible'] = True
            else: bundle['artifacts'][0]['sha256'] = 'sha256:' + '0' * 64
            with self.subTest(fault=fault), self.assertRaises(AssertionError):
                campaign.validate_export(*args)

    def test_hash_valid_forged_semantics_and_raw_disagreement_are_rejected(self):
        for fault in ('artifact', 'binding_pid', 'isolation', 'terminal', 'epoch', 'lost',
                      'health_missing', 'counter_missing', 'descendants', 'unavailable',
                      'summary_loss', 'summary_size', 'publication_open', 'call_unsettled',
                      'truncated', 'incomplete', 'raw_changed', 'tail_changed', 'key_changed'):
            args = list(complete_export())
            content = {item['name']: item['content'] for item in args[0]['artifacts']}
            if fault == 'artifact': content['attempt']['artifact_digest'] = 'sha256:' + 'f' * 64
            elif fault == 'binding_pid': content['runtime_binding']['snapshot']['pid'] += 1
            elif fault == 'isolation':
                args[3]['snapshot']['capabilities'] = 1
                args[4]['attempt']['binding'] = json.dumps(args[3])
                content['runtime_binding'] = args[3]
                next(item for item in args[0]['artifacts'] if item['name'] == 'runtime_binding')['content'] = args[3]
            elif fault == 'terminal': content['attempt']['state'] = 'running'
            elif fault == 'epoch': content['runtime_facts']['observer']['collector_epoch'] = 'wrong'
            elif fault == 'lost': content['runtime_facts']['observer']['lost'] = 1
            elif fault == 'health_missing': content['runtime_facts']['observer_health_unavailable'] = True
            elif fault == 'counter_missing': del content['runtime_facts']['resources']['counters']['cpu.stat']
            elif fault == 'descendants': content['runtime_facts']['resources']['counters']['pids.current'] = '1\n'
            elif fault == 'unavailable': content['runtime_facts']['resources']['unavailable'] = ['io.stat']
            elif fault == 'summary_loss': args[6]['local_lost'] = 1
            elif fault == 'summary_size': args[6]['retained_bytes'] += 1
            elif fault == 'publication_open': content['broker']['calls'][0]['publication_closed'] = False
            elif fault == 'call_unsettled': content['broker']['calls'][0]['state'] = 'unknown'
            elif fault == 'truncated': content['stdout']['source_truncated'] = True
            elif fault == 'incomplete': content['stdout']['file_complete'] = False
            elif fault == 'raw_changed': args[5]['stdout'] += b'forged\n'
            elif fault == 'tail_changed': content['stdout']['tail'] = '00'
            else: content['broker']['calls'][0]['request_key'] = 'replacement'
            if fault in ('publication_open', 'call_unsettled', 'key_changed'):
                args[4]['calls'] = copy.deepcopy(content['broker']['calls'])
            rehash(args[0])  # Correct hashes must not disguise missing or conflicting evidence.
            with self.subTest(fault=fault), self.assertRaises(AssertionError):
                campaign.validate_export(*args)

    def test_unstarted_export_cannot_hide_dispatch_or_output(self):
        for fault in ('output', 'call'):
            args = list(complete_export(False))
            content = {item['name']: item['content'] for item in args[0]['artifacts']}
            if fault == 'output':
                raw = b'unexpected execution\n'
                args[5]['stdout'] = raw
                content['stdout'].update(retained_bytes=len(raw),
                    retained_sha256='sha256:' + hashlib.sha256(raw).hexdigest(), tail=raw.hex())
            else:
                call = {'request_key': 'preview-1', 'publication_closed': True,
                        'state': 'settled', 'consumed_tokens': 0}
                args[4]['calls'] = content['broker']['calls'] = [call]
            rehash(args[0])
            with self.subTest(fault=fault), self.assertRaises(AssertionError):
                campaign.validate_export(*args)

    def test_raw_evidence_reader_rejects_oversize_and_final_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, 'raw')
            path.write_bytes(b'12345')
            with self.assertRaises(AssertionError):
                campaign.read_bounded(path, 4)
            link = Path(directory, 'link')
            link.symlink_to(path)
            with self.assertRaises(OSError):
                campaign.read_bounded(link, 5)
            self.assertEqual(campaign.read_bounded(path, 5), b'12345')

    def test_empty_export_cannot_pass_as_complete_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            run = campaign.Campaign(Path(directory), 'sha256:' + 'a' * 64)
            attempt = 'b' * 32
            forged = {'attempt_id': attempt, 'execution_replay_eligible': False, 'artifacts': []}
            def reply(*arguments):
                Path(directory, attempt + '-export.json').write_text(json.dumps(forged))
            with patch.object(run, 'cli', side_effect=reply), self.assertRaises(AssertionError):
                run.export(attempt)

    def test_active_identity_and_outcome_cannot_change_after_a_denied_request(self):
        binding = {'snapshot': {'pid': 51, 'start_ticks': 900}}
        active = {'attempt': {'id': 'a' * 32, 'state': 'running', 'outcome': 'pending',
                              'binding': json.dumps(binding)}}
        campaign.active_identity(active, ('a' * 32, 51, 900))
        for field, value in [('state', 'retiring'), ('outcome', 'capacity'), ('id', 'b' * 32)]:
            changed = json.loads(json.dumps(active))
            changed['attempt'][field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                campaign.active_identity(changed, ('a' * 32, 51, 900))
        with self.assertRaises(AssertionError):
            campaign.active_identity(active, ('a' * 32, 51, 901))

    def test_unknown_cancel_is_recorded_and_never_resent_by_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            run = campaign.Campaign(Path(directory), 'sha256:' + 'a' * 64)
            attempt = 'b' * 32
            with patch.object(run, 'cli', side_effect=subprocess.TimeoutExpired('cancel', 15)) as call:
                with self.assertRaises(subprocess.TimeoutExpired):
                    run.cancel(attempt)
                self.assertFalse(run.cancel(attempt))
                call.assert_called_once()
            self.assertIn(attempt, run.cancel_sent)

    def test_noncapacity_error_cannot_pass_an_expected_capacity_rejection(self):
        for result in ({'result': 'error', 'message': 'service unavailable'},
                       {'result': 'ok', 'message': 'active capacity exhausted'}):
            with self.assertRaises(AssertionError):
                campaign.capacity_rejection(result, 'active capacity exhausted')
        campaign.capacity_rejection({'result': 'error', 'message': 'active capacity exhausted'},
                                    'active capacity exhausted')


if __name__ == '__main__':
    unittest.main()
