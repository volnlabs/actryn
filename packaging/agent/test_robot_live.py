# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
from types import SimpleNamespace
import unittest

import guest_robot_acceptance as campaign
from guest_robot_acceptance import VerificationTests  # Exercise unchanged offline assertions in CI too.


def lineage():
    observation = dict(zip(campaign.OBSERVATION_FIELDS, [7, 1, 2, 1_000_000_001, 3, 4, 5, True, 1, 100]))
    handle = {'attempt': 'a' * 32, 'namespace': 'b' * 32, 'key': 'c' * 64}
    intent = {'request_key': 'live-preview-1', 'request_digest': 'sha256:' + 'd' * 64,
              'robot_epoch': 'e' * 32, 'handle': handle, 'observation': observation,
              'observation_digest': campaign.digest(observation, sort=False)}
    intent['parent_digest'] = campaign.digest({k: intent[k] for k in ('handle', 'request_digest', 'robot_epoch', 'observation')})
    value = {'origin': 'server_attested', 'attempt_id': handle['attempt'], 'request_key': 'live-preview-1',
             'model': 'gpt-5.4-mini-2026-03-17',
             'output': {'left_delta_ticks': -12, 'right_delta_ticks': 14, 'duration_ms': 4000},
             'robot_handle': handle, 'trusted_robot_observation': observation,
             'observation_digest': intent['observation_digest'], 'lineage_digest': intent['parent_digest'],
             'request_digest': intent['request_digest'], 'agent_observation_reference': 'live-preview-reference'}
    return value, intent


class LiveCampaignTests(unittest.TestCase):
    def test_live_preflight_generated_guest_program_is_valid_and_selects_live_input(self):
        obj = object.__new__(campaign.Campaign)
        obj.live, obj.request_key = True, 'live-preview-1'
        obj.args = SimpleNamespace(artifact='sha256:' + 'a' * 64, cli=Path(__file__),
                                   server_port=1, robot_port=2)
        obj.remote_output = '/var/lib/actryn-test-campaigns/test'
        obj.save = lambda *args: None
        programs = []
        def ssh(port, program):
            compile(program, '<guest-preflight>', 'exec')
            programs.append(program)
            if len(programs) <= 2:
                arch, kernel = ('x86_64', 'amd64') if port == 1 else ('aarch64', 'arm64')
                return campaign.compact({'arch': arch, 'kernel': '6.12.111+deb13-' + kernel, 'boot': 'test'})
            if len(programs) == 3:
                return b'linux,dummy-virt'
            raise RuntimeError('stop before guest execution')
        obj.ssh = ssh
        with self.assertRaisesRegex(RuntimeError, 'stop before guest execution'):
            obj.preflight()
        self.assertIn("=='live'", programs[-1])
        self.assertIn("=='live-preview-1'", programs[-1])

    def test_live_lineage_accepts_bounded_proposal_but_not_offline_substitution(self):
        value, intent = lineage()
        campaign.verify_lineage(value, intent, 'a' * 32, 'b' * 32, live=True)
        for change in ({'model': 'offline-fixture'}, {'request_key': 'preview-1'},
                       {'agent_observation_reference': 'offline-preview-reference'},
                       {'output': {'left_delta_ticks': 101, 'right_delta_ticks': 0, 'duration_ms': 1000}},
                       {'output': {'left_delta_ticks': True, 'right_delta_ticks': 0, 'duration_ms': 1000}},
                       {'output': {'left_delta_ticks': 0, 'right_delta_ticks': 0, 'duration_ms': 10001}}):
            with self.subTest(change=change), self.assertRaises(AssertionError):
                campaign.verify_lineage(dict(value, **change), intent, 'a' * 32, 'b' * 32, live=True)

    def test_live_observation_cannot_be_replaced_or_lifetime_extended(self):
        value, intent = lineage()
        value['trusted_robot_observation'] = dict(intent['observation'], id=8)
        with self.assertRaises(AssertionError):
            campaign.verify_lineage(value, intent, 'a' * 32, 'b' * 32, live=True)
        value, intent = lineage()
        intent['observation']['valid_until_ns'] += 1
        with self.assertRaises(AssertionError):
            campaign.verify_lineage(value, intent, 'a' * 32, 'b' * 32, live=True)

    def test_live_executes_one_combined_attempt_and_never_retries_failure(self):
        for live in (False, True):
            calls = []
            obj = SimpleNamespace(live=live)
            for name in ('preflight', 'negative_bindings', 'independent_server', 'combined'):
                setattr(obj, name, lambda name=name: calls.append(name))
            campaign.run_scenarios(obj)
            self.assertEqual(calls, ['preflight', 'combined'] if live else
                             ['preflight', 'negative_bindings', 'independent_server', 'combined'])
            calls.clear()
            def fail():
                calls.append('combined')
                raise TimeoutError('uncertain call')
            obj.combined = fail
            with self.assertRaises(TimeoutError):
                campaign.run_scenarios(obj)
            self.assertEqual(calls.count('combined'), 1)

    def test_accounting_requires_exact_integer_bounded_usage(self):
        for tokens in (-1, 1025, True, None):
            with self.subTest(tokens=tokens), self.assertRaises(AssertionError):
                campaign.verify_model_tokens(tokens, live=True)
        for tokens in (0, 1, 1024):
            campaign.verify_model_tokens(tokens, live=True)
        with self.assertRaises(AssertionError):
            campaign.verify_model_tokens(1, live=False)


if __name__ == '__main__':
    unittest.main()
