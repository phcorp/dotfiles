"""Kill actual Git setup processes between durable transaction writes."""
import os
import pathlib
import signal
import subprocess
import sys
import time
import unittest
import test_git_setup as fixture


class GitInterruption(unittest.TestCase):
    setUp = fixture.GitSetup.setUp
    cli = fixture.GitSetup.cli
    install = fixture.GitSetup.install
    write_input = fixture.GitSetup.write_input
    setup_git = fixture.GitSetup.setup_git

    def prepare(self, absent_revision=False):
        self.install('[user]\n name = Fixture Original\n email = original@example.invalid\n')
        self.write_input('[user]\n name = Fixture First\n email = first@example.invalid\n')
        self.setup_git()
        if absent_revision:
            (self.state / 'applied-revision').unlink(missing_ok=True)
        self.before = {path: path.read_bytes() if path.exists() else None for path in (
            self.output, self.state / 'git-setup.tsv', self.state / 'managed.tsv',
            self.home / '.gitconfig', self.state / 'applied-revision')}
        self.shims = self.home / 'shims'
        self.shims.mkdir()
        self.ready = self.home / 'gate-ready'
        wrapper = '#!' + sys.executable + '\n' + '''import os, pathlib, runpy, sys, time
script, *args = sys.argv[1:]
if pathlib.Path(script).name != 'git-setup.py':
    os.execv(sys.executable, [sys.executable, script, *args])
kind = os.environ.get('GIT_SETUP_GATE', '')
output = pathlib.Path(os.environ['DOTFILES_CONFIG']) / 'local/git/config'
original_replace = os.replace
def replacement(source, destination, *args, **kwargs):
    original_replace(source, destination, *args, **kwargs)
    if kind == 'output' and pathlib.Path(destination) == output:
        pause()
def pause():
    pathlib.Path(os.environ['GIT_SETUP_READY']).write_text('ready')
    while True:
        time.sleep(0.02)
os.replace = replacement
if kind == 'retain' and args and args[0] == 'retain':
    pause()
sys.argv = [script, *args]
runpy.run_path(script, run_name='__main__')
'''
        shim = self.shims / 'python3'
        shim.write_text(wrapper)
        shim.chmod(0o755)
        self.env.update(PATH=str(self.shims) + os.pathsep + self.env['PATH'],
                        GIT_SETUP_READY=str(self.ready))

    def interrupt(self, gate, *action):
        self.env['GIT_SETUP_GATE'] = gate
        process = subprocess.Popen([str(fixture.ROOT / 'bin/dotfiles'), *action, '--non-interactive'],
                                   env=self.env, cwd=self.home, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True)
        try:
            deadline = time.monotonic() + 30
            while not self.ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            if not self.ready.exists():
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate(timeout=5)
                self.fail('Fault gate was not reached: ' + stdout + stderr)
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=5)
            self.assertEqual(process.returncode, -signal.SIGKILL)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate(timeout=5)
            self.env.pop('GIT_SETUP_GATE', None)

    def restored(self):
        self.cli('recover', '--unlock-stale', '--non-interactive')
        for path, data in self.before.items():
            if data is None:
                self.assertFalse(path.exists(), str(path))
            else:
                self.assertEqual(path.read_bytes(), data, str(path))
        self.assertFalse((self.state / 'transaction').exists())
        self.assertFalse(list((self.config / 'local/git').glob('*.new')))
        self.assertFalse((self.state / 'git-setup.tsv.new').exists())
        self.assertFalse((self.home / '.gitconfig.new').exists())

    def test_setup_killed_after_output_before_ownership_ledger_restores_then_retries(self):
        self.prepare()
        self.write_input('[user]\n name = Fixture Second\n email = second@example.invalid\n')
        self.interrupt('output', 'git', 'setup')
        self.assertNotEqual(self.output.read_bytes(), self.before[self.output])
        self.assertEqual((self.state / 'git-setup.tsv').read_bytes(), self.before[self.state / 'git-setup.tsv'])
        self.restored()
        self.setup_git()
        self.assertIn(b'second@example.invalid', self.output.read_bytes())

    def test_uninstall_killed_after_original_restore_before_retained_include_recovers(self):
        self.prepare(absent_revision=True)
        self.interrupt('retain', 'uninstall')
        self.assertIn('original@example.invalid', (self.home / '.gitconfig').read_text())
        self.restored()
        self.cli('uninstall', '--non-interactive')
        self.assertTrue(self.output.exists())
        self.assertIn(str(self.output), (self.home / '.gitconfig').read_text())
