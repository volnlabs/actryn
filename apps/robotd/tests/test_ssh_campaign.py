import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from ssh_campaign import SharedSsh, passenger_command


class SharedSshTests(unittest.TestCase):
    def test_missing_master_cannot_fall_back_to_network_connection(self):
        with tempfile.TemporaryDirectory() as directory, socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            listener.settimeout(.05)
            common = ['ssh', '-F', '/dev/null', '-p', str(listener.getsockname()[1]),
                      '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=1']
            command = passenger_command(common, 'root@127.0.0.1', Path(directory) / 'absent')
            result = subprocess.run([*command, 'true'], capture_output=True, timeout=3)
            self.assertNotEqual(result.returncode, 0)
            with self.assertRaises(TimeoutError):
                listener.accept()

    def test_owned_master_starts_once_and_finally_terminates_only_its_child(self):
        with tempfile.TemporaryDirectory() as output:
            process, control = Mock(), socket.socket(socket.AF_UNIX)
            process.pid = 32101
            process.returncode = None
            process.poll.return_value = None
            def terminate():
                process.returncode = -15
                process.poll.return_value = -15
            process.terminate.side_effect = terminate
            def start(command, **_):
                path = next(arg.removeprefix('ControlPath=') for arg in command if arg.startswith('ControlPath='))
                control.bind(path)
                os.chmod(path, 0o600)
                return process
            check = subprocess.CompletedProcess([], 0, b'', b'Master running (pid=32101)\r\n')
            master = SharedSsh(['ssh', '-p', '26221', 'root@127.0.0.1'], Path(output))
            try:
                with patch('ssh_campaign.subprocess.Popen', side_effect=start) as spawn, \
                     patch('ssh_campaign.subprocess.run', return_value=check) as run, \
                     patch('ssh_campaign.write_json'), self.assertRaisesRegex(RuntimeError, 'campaign failed'):
                    with master as shared:
                        self.assertIn('ProxyCommand=/usr/bin/false', shared.command)
                        self.assertNotIn('ControlMaster=auto', shared.command)
                        raise RuntimeError('campaign failed')
                spawn.assert_called_once()
                run.assert_called_once()  # Read-only check, never an exit sent to an unowned socket.
                process.terminate.assert_called_once()
                process.kill.assert_not_called()
                self.assertFalse(master.control.parent.exists())
                master.close()
                process.terminate.assert_called_once()
            finally:
                control.close()

    def test_failed_master_start_never_enters_campaign_or_retries(self):
        with tempfile.TemporaryDirectory() as output:
            process, action = Mock(), Mock()
            process.poll.return_value = 255
            process.returncode = 255
            with patch('ssh_campaign.subprocess.Popen', return_value=process) as spawn, \
                 patch('ssh_campaign.subprocess.run') as run, patch('ssh_campaign.write_json'):
                with self.assertRaises(AssertionError):
                    with SharedSsh(['ssh', 'root@127.0.0.1'], Path(output)):
                        action()
            spawn.assert_called_once()
            run.assert_not_called()
            action.assert_not_called()
            process.terminate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
