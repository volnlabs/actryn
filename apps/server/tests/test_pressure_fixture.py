import copy
import unittest
from unittest.mock import patch
import subprocess
import pressure_fixture as fixture


class FixtureTests(unittest.TestCase):
    def test_service_timeout_preserves_partial_output_and_does_not_resend(self):
        error=subprocess.TimeoutExpired(['systemctl','start','actryn-launcher'],40,
                                        output=b'preflight pending',stderr=b'retained diagnostic')
        with patch.object(fixture.subprocess,'run',side_effect=error) as call:
            with self.assertRaises(AssertionError) as raised:fixture.command(error.cmd,40)
            self.assertEqual(call.call_count,1)
        report=raised.exception.args[0]
        self.assertTrue(report['outcome_unknown']);self.assertFalse(report['automatic_retry'])
        self.assertEqual(report['stdout'],'preflight pending')
        self.assertEqual(report['stderr'],'retained diagnostic')

    def test_runtime_observations_are_removed_without_hiding_command_or_security_changes(self):
        old='{ path=/usr/bin/actryn-launcher ; argv[]=/usr/bin/actryn-launcher ; ignore_errors=no ; start_time=[old] ; stop_time=[n/a] ; pid=3 ; code=(null) ; status=0/0 }'
        new=old.replace('[old]','[new]').replace('pid=3','pid=7')
        self.assertEqual(fixture.stable_commands(old),fixture.stable_commands(new))
        self.assertNotEqual(fixture.stable_commands(old),fixture.stable_commands(old.replace('ignore_errors=no','ignore_errors=yes')))
        self.assertNotEqual(fixture.stable_commands(old),fixture.stable_commands(old.replace('actryn-launcher','arbitrary')))

    def test_instrumentation_requires_only_launcher_mapping_and_unchanged_inherited_security(self):
        record={'original':{'properties':{'ExecStart':'original','MemoryMax':'134217728','ExecStartPre':'pinned'}},
                'instrumented':{'properties':{'ExecStart':'fixed-override','MemoryMax':'134217728','ExecStartPre':'pinned'}},
                'library_sha256':'1'*64,'manifest':'2'*64}
        now={'manifest':'2'*64,'properties':copy.deepcopy(record['instrumented']['properties']),
             'library_sha256':'1'*64,'library_users':[42],
             'services':{'actryn-launcher':{'pid':42}}}
        fixture.validate_instrumentation(record,now)
        for fault in ('extra-loader','different-loader','security','preflight','command','library','manifest'):
            bad=copy.deepcopy(now)
            if fault=='extra-loader':bad['library_users'].append(43)
            elif fault=='different-loader':bad['library_users']=[43]
            elif fault=='security':bad['properties']['MemoryMax']='infinity'
            elif fault=='preflight':bad['properties']['ExecStartPre']=''
            elif fault=='command':bad['properties']['ExecStart']='other'
            elif fault=='library':bad['library_sha256']='0'*64
            else:bad['manifest']='0'*64
            with self.subTest(fault=fault), self.assertRaises(AssertionError):
                fixture.validate_instrumentation(record,bad)

    def test_changed_original_security_cannot_be_blessed_by_instrumented_record(self):
        record={'original':{'properties':{'ExecStart':'old','MemoryMax':'128M'}},
                'instrumented':{'properties':{'ExecStart':'new','MemoryMax':'infinity'}},
                'library_sha256':'1'*64,'manifest':'2'*64}
        now={'manifest':'2'*64,'properties':record['instrumented']['properties'],'library_sha256':'1'*64,
             'library_users':[42],'services':{'actryn-launcher':{'pid':42}}}
        with self.assertRaises(AssertionError): fixture.validate_instrumentation(record,now)


if __name__=='__main__': unittest.main()
