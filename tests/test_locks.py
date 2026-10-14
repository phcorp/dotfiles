"""Lock metadata and recovery operate only in disposable fixture homes."""
import os
import pathlib
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class Locks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dotfiles-lock-test-')
        self.addCleanup(self.tmp.cleanup)
        self.home = pathlib.Path(self.tmp.name)
        self.state = self.home / 'state'
        self.state.mkdir()
        self.lock = self.state / 'lifecycle.lock'
        self.env = dict(os.environ, HOME=str(self.home), DOTFILES_LOCK_LIBRARY=str(ROOT / 'lib/locks.sh'),
                        DOTFILES_LOCK_PATH=str(self.lock))

    def shell(self, body, env=None):
        return subprocess.run(['/bin/sh', '-eu', '-c', '. "$DOTFILES_LOCK_LIBRARY"; ' + body],
                              env=env or self.env, capture_output=True, text=True, timeout=10)

    def status(self):
        result = self.shell('lock_status "$DOTFILES_LOCK_PATH"')
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def owner(self, pid=2147483647, host=None, start='Wed Oct 14 00:00:00 2026', nonce='fixture-nonce'):
        self.lock.mkdir(exist_ok=True)
        (self.lock / 'owner').write_text(f'1\t{pid}\t{host or socket.gethostname()}\t{start}\t1\t{nonce}\n')
        (self.lock / 'owner').chmod(0o600)

    def start_holder(self):
        ready = self.home / 'ready'
        env = dict(self.env, DOTFILES_LOCK_READY=str(ready))
        process = subprocess.Popen(['/bin/sh', '-eu', '-c',
                                    '. "$DOTFILES_LOCK_LIBRARY"; lock_acquire "$DOTFILES_LOCK_PATH"; '
                                    ': > "$DOTFILES_LOCK_READY"; while :; do sleep 1; done'],
                                   env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        self.addCleanup(self.stop_holder, process)
        limit = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < limit and process.poll() is None:
            time.sleep(0.02)
        if not ready.exists():
            self.stop_holder(process)
            out, err = process.communicate()
            self.fail('Lock holder did not become ready: ' + out + err)
        return process

    @staticmethod
    def stop_holder(process):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()

    def test_absent_lock_and_nonexistent_private_parent(self):
        self.assertEqual(self.status(), 'absent')
        env = dict(self.env, DOTFILES_LOCK_PATH=str(self.home / 'missing/deeper/lock'))
        result = self.shell('lock_status "$DOTFILES_LOCK_PATH"', env)
        self.assertEqual(result.stdout.strip(), 'absent')

    def test_acquire_is_active_private_and_release_matches_owner(self):
        result = self.shell('lock_acquire "$DOTFILES_LOCK_PATH"; '
                            'lock_status "$DOTFILES_LOCK_PATH"; lock_release "$DOTFILES_LOCK_PATH"; '
                            'lock_status "$DOTFILES_LOCK_PATH"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['active', 'absent'])

    def test_active_lock_never_reclaimed_or_reacquired(self):
        self.start_holder()
        before = (self.lock / 'owner').read_bytes()
        self.assertEqual(self.status(), 'active')
        self.assertEqual(self.lock.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.lock / 'owner').stat().st_mode & 0o777, 0o600)
        for body in ('lock_recover_stale "$DOTFILES_LOCK_PATH"', 'lock_acquire "$DOTFILES_LOCK_PATH"'):
            result = self.shell(body)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((self.lock / 'owner').read_bytes(), before)

    def test_killed_real_holder_is_stale_and_explicitly_recoverable(self):
        process = self.start_holder()
        self.stop_holder(process)
        self.assertEqual(self.status(), 'stale')
        result = self.shell('lock_recover_stale "$DOTFILES_LOCK_PATH"; '
                            'lock_acquire "$DOTFILES_LOCK_PATH"; lock_release "$DOTFILES_LOCK_PATH"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.lock.exists())
        self.assertEqual(list(self.state.iterdir()), [])

    def test_pid_reuse_is_detected_by_start_identity(self):
        process = self.start_holder()
        fields = (self.lock / 'owner').read_text().rstrip('\n').split('\t')
        fields[3] = 'Thu Jan 1 00:00:00 1970'
        (self.lock / 'owner').write_text('\t'.join(fields) + '\n')
        self.assertEqual(self.status(), 'stale')
        result = self.shell('lock_recover_stale "$DOTFILES_LOCK_PATH"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(process.poll(), 'Reclaim must not signal the unrelated reused PID')

    def test_legacy_foreign_host_and_malformed_metadata_are_unknown(self):
        self.lock.mkdir()
        self.assertEqual(self.status(), 'unknown')
        self.assertNotEqual(self.shell('lock_recover_stale "$DOTFILES_LOCK_PATH"').returncode, 0)
        self.owner(host='different-fixture-host')
        before = (self.lock / 'owner').read_bytes()
        self.assertEqual(self.status(), 'unknown')
        self.assertNotEqual(self.shell('lock_recover_stale "$DOTFILES_LOCK_PATH"').returncode, 0)
        self.assertEqual((self.lock / 'owner').read_bytes(), before)
        (self.lock / 'owner').write_text('malformed\n')
        self.assertEqual(self.status(), 'unknown')
        self.assertNotEqual(self.shell('lock_recover_stale "$DOTFILES_LOCK_PATH"').returncode, 0)
        self.assertTrue(self.lock.exists())

    def test_unverifiable_process_is_unknown(self):
        self.owner(pid=os.getpid())
        mock = self.home / 'mock-bin'
        mock.mkdir()
        ps = mock / 'ps'
        ps.write_text('#!/bin/sh\nexit 2\n')
        ps.chmod(0o755)
        env = dict(self.env, PATH=str(mock) + ':' + self.env['PATH'])
        result = self.shell('lock_status "$DOTFILES_LOCK_PATH"', env)
        self.assertEqual(result.stdout.strip(), 'unknown')
        self.assertNotEqual(self.shell('lock_recover_stale "$DOTFILES_LOCK_PATH"', env).returncode, 0)

    def test_release_refuses_replacement_nonce(self):
        result = self.shell('lock_acquire "$DOTFILES_LOCK_PATH"; '
                            'sed "s/$LOCK_NONCE/replacement-nonce/" "$DOTFILES_LOCK_PATH/owner" > "$DOTFILES_LOCK_PATH/next"; '
                            'mv "$DOTFILES_LOCK_PATH/next" "$DOTFILES_LOCK_PATH/owner"; '
                            'lock_release "$DOTFILES_LOCK_PATH"')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('replacement-nonce', (self.lock / 'owner').read_text())

    def cli(self, *args):
        env = dict(self.env, DOTFILES_SOURCE=str(ROOT), DOTFILES_STATE=str(self.state),
                   DOTFILES_CONFIG=str(self.home / 'config'), XDG_CONFIG_HOME=str(self.home / 'config-root'),
                   XDG_STATE_HOME=str(self.home / 'state-root'), XDG_DATA_HOME=str(self.home / 'data'),
                   DOTFILES_MODE='non-interactive', DOTFILES_TESTING='1')
        return subprocess.run([str(ROOT / 'bin/dotfiles'), *args, '--non-interactive'],
                              env=env, cwd=self.home, capture_output=True, text=True, timeout=15)

    def test_doctor_reports_stale_owner_without_unlocking_it(self):
        process = self.start_holder()
        self.stop_holder(process)
        before = (self.lock / 'owner').read_bytes()
        result = self.cli('doctor')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Lifecycle lock stale', result.stdout)
        self.assertIn('recover --unlock-stale', result.stdout)
        self.assertEqual((self.lock / 'owner').read_bytes(), before)

    def test_cli_can_reclaim_stale_lock_without_transaction(self):
        process = self.start_holder()
        self.stop_holder(process)
        result = self.cli('recover', '--unlock-stale')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.lock.exists())
        self.assertFalse((self.state / 'transaction').exists())

    def test_cli_cannot_unlock_aged_active_owner(self):
        process = self.start_holder()
        fields = (self.lock / 'owner').read_text().rstrip('\n').split('\t')
        fields[4] = '1'
        (self.lock / 'owner').write_text('\t'.join(fields) + '\n')
        before = (self.lock / 'owner').read_bytes()
        result = self.cli('doctor')
        self.assertIn('Lifecycle lock active', result.stdout)
        result = self.cli('recover', '--unlock-stale')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.lock / 'owner').read_bytes(), before)
        self.assertIsNone(process.poll())

    def test_cli_preserves_unknown_legacy_lock(self):
        self.lock.mkdir()
        result = self.cli('doctor')
        self.assertRegex(result.stdout, r'Lifecycle lock.*(?:unknown|cannot be verified)')
        result = self.cli('recover', '--unlock-stale')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.lock.is_dir())
        self.assertEqual(list(self.lock.iterdir()), [])

    def test_reclaim_rechecks_process_identity_under_claim(self):
        self.owner()
        before = (self.lock / 'owner').read_bytes()
        env = dict(self.env, DOTFILES_PROBE_COUNT=str(self.home / 'probe-count'))
        body = '_lock_start() {\n    if [ -f "$DOTFILES_PROBE_COUNT" ]; then printf \'%s\\n\' "$_lock_owner_start"\n    else : > "$DOTFILES_PROBE_COUNT"; printf \'different fixture start\\n\'; fi\n}; lock_recover_stale "$DOTFILES_LOCK_PATH"'
        result = self.shell(body, env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.lock / 'owner').read_bytes(), before)
        self.assertFalse((self.lock / 'reclaim').exists())

    def test_symlink_lock_and_unexpected_contents_are_preserved(self):
        outside = self.home / 'outside'
        outside.mkdir()
        (outside / 'sentinel').write_text('preserve')
        self.lock.symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.status(), 'unknown')
        self.assertNotEqual(self.shell('lock_recover_stale "$DOTFILES_LOCK_PATH"').returncode, 0)
        self.assertEqual((outside / 'sentinel').read_text(), 'preserve')
        self.lock.unlink()
        self.owner()
        (self.lock / 'unexpected').write_text('preserve')
        self.assertNotEqual(self.shell('lock_recover_stale "$DOTFILES_LOCK_PATH"').returncode, 0)
        self.assertTrue((self.lock / 'unexpected').exists())
