import copy
import json
import unittest
from unittest.mock import patch
import subprocess
import pressure_fixture as fixture


class FixtureTests(unittest.TestCase):
    def shown_properties(self, missing=()):
        return ''.join(name+'=pinned-'+name+'\n' for name in fixture.PROPERTIES
                       if name!='DeviceAllow' and name not in missing)

    def test_device_allow_omitted_empty_value_is_read_from_typed_bus_property(self):
        with patch.object(fixture,'command',side_effect=[self.shown_properties(),
                          '{"type":"a(ss)","data":[]}']) as call:
            result=fixture.properties()
        self.assertEqual(result['DeviceAllow'],[])
        self.assertEqual(set(result),set(fixture.PROPERTIES))
        self.assertNotIn('DeviceAllow',call.call_args_list[0].args[0][-1].split('=',1)[1].split(','))
        self.assertEqual(call.call_args_list[1].args[0],[
            '/usr/bin/busctl','--system','--json=short','get-property',
            'org.freedesktop.systemd1',
            '/org/freedesktop/systemd1/unit/actryn_2dlauncher_2eservice',
            'org.freedesktop.systemd1.Service','DeviceAllow'])

    def test_device_allow_preserves_one_or_multiple_entries_without_dict_loss(self):
        for entries in ([['/dev/null','rw']], [['/dev/null','rw'],['/dev/zero','r']]):
            with self.subTest(entries=entries), patch.object(fixture,'command',side_effect=[
                    self.shown_properties(),json.dumps({'type':'a(ss)','data':entries})]):
                result=fixture.properties()
                self.assertEqual(result['DeviceAllow'],entries)

    def test_device_allow_malformed_or_wrong_type_fails_closed(self):
        for value in ('not json','{}','[]',json.dumps({'type':'as','data':[]}),
                      json.dumps({'type':'a(ss)','data':None}),
                      json.dumps({'type':'a(ss)','data':['/dev/null']}),
                      json.dumps({'type':'a(ss)','data':[['/dev/null']]}),
                      json.dumps({'type':'a(ss)','data':[['/dev/null',1]]})):
            with self.subTest(value=value), patch.object(fixture,'command',side_effect=[self.shown_properties(),value]) as call:
                with self.assertRaises((AssertionError,ValueError)):fixture.properties()
                self.assertEqual(call.call_count,2)

    def test_device_allow_command_failure_is_not_assumed_empty(self):
        with patch.object(fixture,'command',side_effect=[self.shown_properties(),AssertionError('bus unavailable')]) as call:
            with self.assertRaisesRegex(AssertionError,'bus unavailable'):fixture.properties()
            self.assertEqual(call.call_count,2)

    def test_missing_other_property_still_fails(self):
        for missing in ('DevicePolicy','ExecStartPre','LoadCredential'):
            with self.subTest(missing=missing), patch.object(fixture,'command',return_value=self.shown_properties((missing,))) as call:
                with self.assertRaisesRegex(AssertionError,'incomplete inherited'):fixture.properties()
                self.assertEqual(call.call_count,1)

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
        record={'original':{'properties':{'ExecStart':'original','MemoryMax':'134217728','ExecStartPre':'pinned','DeviceAllow':[['/dev/null','rw']]}},
                'instrumented':{'properties':{'ExecStart':'fixed-override','MemoryMax':'134217728','ExecStartPre':'pinned','DeviceAllow':[['/dev/null','rw']]}},
                'library_sha256':'1'*64,'manifest':'2'*64}
        now={'manifest':'2'*64,'properties':copy.deepcopy(record['instrumented']['properties']),
             'library_sha256':'1'*64,'library_users':[42],
             'services':{'actryn-launcher':{'pid':42}}}
        fixture.validate_instrumentation(record,now)
        for fault in ('extra-loader','different-loader','security','device-allow','preflight','command','library','manifest'):
            bad=copy.deepcopy(now)
            if fault=='extra-loader':bad['library_users'].append(43)
            elif fault=='different-loader':bad['library_users']=[43]
            elif fault=='security':bad['properties']['MemoryMax']='infinity'
            elif fault=='device-allow':bad['properties']['DeviceAllow'].append(['/dev/zero','r'])
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
