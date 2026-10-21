import runpy
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock,patch

SCRIPT=Path(__file__).resolve().parent.parent/'companion'/'telemetry-session.py'
class SessionTests(unittest.TestCase):
    def run_session(self,ready,read=b'',kill=False):
        child=Mock();child.poll.return_value=None
        if kill:child.wait.side_effect=[subprocess.TimeoutExpired('reader',2),0]
        with patch('sys.argv',['session','15611']),patch('subprocess.Popen',return_value=child),patch('select.select',return_value=(ready,[],[])),patch('os.read',return_value=read):
            runpy.run_path(str(SCRIPT),run_name='__main__')
        return child
    def test_lease_timeout_releases_reader(self):
        child=self.run_session([])
        child.terminate.assert_called_once();child.wait.assert_called_once_with(timeout=2)
    def test_stdin_eof_releases_reader(self):
        self.run_session([0]).terminate.assert_called_once()
    def test_unresponsive_reader_is_killed(self):
        self.run_session([],kill=True).kill.assert_called_once()
    def test_other_ports_cannot_start_reader(self):
        with patch('sys.argv',['session','14550']),patch('subprocess.Popen') as spawn,self.assertRaises(SystemExit):
            runpy.run_path(str(SCRIPT),run_name='__main__')
        spawn.assert_not_called()
