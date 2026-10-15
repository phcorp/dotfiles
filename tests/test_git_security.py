"""Adversarial Git setup checks, confined to disposable private fixture homes."""
import os
import hashlib
import shutil
import subprocess
import unittest

import test_git_setup as fixtures


class GitSecurity(unittest.TestCase):
    setUp = fixtures.GitSetup.setUp
    cli = fixtures.GitSetup.cli
    install = fixtures.GitSetup.install
    write_input = fixtures.GitSetup.write_input
    setup_git = fixtures.GitSetup.setup_git
    git_value = fixtures.GitSetup.git_value
    snapshot = fixtures.GitSetup.snapshot
    assert_redacted = fixtures.GitSetup.assert_redacted

    def gpg_fixture(self, validity='u', expiration='', capabilities='s'):
        mock_bin = self.home / 'mock-gpg-bin'
        mock_bin.mkdir(exist_ok=True)
        executable = mock_bin / 'gpg'
        executable.write_text('#!/bin/sh\n'
                              'printf "%s\\n" "$@" >> "$GPG_FIXTURE_LOG"\n'
                              'case " $* " in\n'
                              '  *" --list-secret-keys "*) printf "%s\\n" "$GPG_FIXTURE_METADATA" ;;\n'
                              '  *) exit 93 ;;\n'
                              'esac\n')
        executable.chmod(0o755)
        if str(mock_bin) not in self.env['PATH'].split(os.pathsep):
            self.env['PATH'] = str(mock_bin) + os.pathsep + self.env['PATH']
        fingerprint = 'A' * 40
        fields = ['sec', validity, '255', '22', fingerprint[-16:], '1', expiration,
                  '', '', '', '', capabilities, '', '', '+']
        self.env['GPG_FIXTURE_METADATA'] = ':'.join(fields) + ':'
        # Keep mock instrumentation outside HOME so snapshot checks cover only
        # production side effects, not the fixture's invocation recording.
        log = self.home.parent / 'gpg-fixture-invocations'
        self.env['GPG_FIXTURE_LOG'] = str(log)
        self.write_input('[user]\n name = Fixture GPG\n email = gpg@example.invalid\n'
                         f' signingkey = {fingerprint}\n[gpg]\n format = openpgp\n'
                         '[commit]\n gpgsign = true\n')
        return log, fingerprint

    def profile(self, text):
        path = self.home / 'private-profile.gitconfig'
        path.write_text(text)
        path.chmod(0o600)
        return path

    def repository(self):
        directory = self.home / 'work projects'
        directory.mkdir()
        repo = directory / 'project'
        subprocess.run(['git', 'init', str(repo)], env=self.env,
                       capture_output=True, check=True)
        return directory, repo

    def test_retained_profile_wins_after_later_global_identity_edit(self):
        self.install()
        directory, repo = self.repository()
        profile = self.profile('[user]\n name = Fixture Work\n email = work@example.invalid\n')
        self.write_input('[user]\n name = Fixture Personal\n email = personal@example.invalid\n'
                         f'[includeIf "gitdir:{directory}/"]\n path = "{profile}"\n')
        self.setup_git()
        self.write_input('[user]\n name = Fixture Replacement\n email = replacement@example.invalid\n')
        self.setup_git()
        self.assertEqual(self.git_value('user.name', repo).stdout.strip(), 'Fixture Work')
        self.assertEqual(self.git_value('user.email', repo).stdout.strip(), 'work@example.invalid')
        self.assertEqual(self.git_value('user.name').stdout.strip(), 'Fixture Replacement')
        self.assertEqual(self.git_value('user.email').stdout.strip(), 'replacement@example.invalid')

    def test_secure_helper_replaces_legacy_chain_on_actual_credential_approve(self):
        mock_bin = self.home / 'mock-bin'
        mock_bin.mkdir()
        for name in ('fixturelegacy', 'manager'):
            helper = mock_bin / ('git-credential-' + name)
            helper.write_text('#!/bin/sh\ncat >/dev/null\nprintf "%s\\n" "$1" >> "$HOME/'
                              + name + '-calls"\n')
            helper.chmod(0o755)
        self.env['PATH'] = str(mock_bin) + os.pathsep + self.env['PATH']
        self.env['GIT_TERMINAL_PROMPT'] = '0'
        self.install('[credential]\n helper = fixturelegacy\n')
        self.write_input('[credential]\n helper = manager\n')
        self.setup_git()
        result = subprocess.run(['git', 'credential', 'approve'], env=self.env, cwd=self.home,
                                input='protocol=https\nhost=fixture.example.invalid\n'
                                      'username=fixture\npassword=fixture-only\n\n',
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.home / 'fixturelegacy-calls').exists())
        self.assertEqual((self.home / 'manager-calls').read_text(), 'store\n')

    def test_uninstall_retains_setup_without_changing_home_permissions(self):
        self.install('[user]\n name = Fixture Original\n email = original@example.invalid\n')
        self.write_input('[user]\n email = retained@example.invalid\n')
        self.setup_git()
        self.home.chmod(0o751)
        content = self.output.read_bytes()
        self.cli('uninstall', '--non-interactive')
        self.assertEqual(self.home.stat().st_mode & 0o777, 0o751)
        self.assertEqual(self.output.read_bytes(), content)
        self.assertEqual(self.git_value('user.email').stdout.strip(), 'retained@example.invalid')

    def test_profile_signing_inherits_global_key_declared_after_include(self):
        executable = shutil.which('ssh-keygen')
        if not executable:
            self.skipTest('ssh-keygen unavailable')
        self.install()
        directory, repo = self.repository()
        key = self.home / 'fixture signing key'
        subprocess.run([executable, '-q', '-t', 'ed25519', '-N', '', '-C', 'fixture-only', '-f', str(key)],
                       env=self.env, capture_output=True, check=True)
        profile = self.profile('[user]\n email = signing-profile@example.invalid\n'
                               '[commit]\n gpgsign = true\n')
        self.write_input(f'[includeIf "gitdir:{directory}/"]\n path = "{profile}"\n'
                         '[gpg]\n format = ssh\n[user]\n'
                         f' signingkey = "{key}.pub"\n')
        result = self.setup_git()
        self.assert_redacted(result, 'signing-profile@example.invalid', str(key))
        self.assertEqual(self.git_value('commit.gpgsign', repo).stdout.strip(), 'true')
        self.assertEqual(self.git_value('gpg.format', repo).stdout.strip(), 'ssh')

    def test_preexisting_unowned_setup_cannot_smuggle_forbidden_configuration(self):
        self.install()
        self.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        marker = self.home / 'forbidden-command-marker'
        self.output.write_text('[alias]\n forbidden = !touch "' + str(marker) + '"\n')
        self.output.chmod(0o600)
        self.write_input('[user]\n name = Fixture Private\n email = hidden@example.invalid\n')
        before = self.snapshot()
        result = self.setup_git(ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(marker.exists())
        self.assert_redacted(result, 'Fixture Private', 'hidden@example.invalid', str(marker))

    def test_signing_can_be_disabled_after_private_identity_becomes_unavailable(self):
        executable = shutil.which('ssh-keygen')
        if not executable:
            self.skipTest('ssh-keygen unavailable')
        self.install()
        key = self.home / 'fixture unavailable key'
        subprocess.run([executable, '-q', '-t', 'ed25519', '-N', '', '-C', 'fixture-only', '-f', str(key)],
                       env=self.env, capture_output=True, check=True)
        self.write_input('[gpg]\n format = ssh\n[user]\n'
                         f' signingkey = "{key}.pub"\n'
                         '[commit]\n gpgsign = true\n[tag]\n gpgsign = true\n')
        self.setup_git()
        key.unlink()
        self.env.pop('SSH_AUTH_SOCK', None)
        self.write_input('[commit]\n gpgsign = false\n[tag]\n gpgsign = false\n')
        self.setup_git()
        self.assertEqual(self.git_value('commit.gpgsign').stdout.strip(), 'false')
        self.assertEqual(self.git_value('tag.gpgsign').stdout.strip(), 'false')

    def test_gpg_preview_does_not_open_keyring_or_run_gpg(self):
        self.install()
        log, fingerprint = self.gpg_fixture()
        before = self.snapshot()
        result = self.setup_git('--dry-run')
        self.assertEqual(before, self.snapshot())
        self.assertFalse(log.exists())
        self.assertFalse((self.home / '.gnupg').exists())
        self.assert_redacted(result, fingerprint, 'gpg@example.invalid')
        self.assertIn('NEEDS INFO', result.stdout)

    def test_gpg_rejects_expired_revoked_disabled_and_non_signing_metadata(self):
        self.install()
        for validity, expiration, capabilities in [('u', '1', 's'), ('r', '', 's'),
                                                    ('e', '', 's'), ('d', '', 's'),
                                                    ('u', '', 'e'), ('u', '', 'sD')]:
            with self.subTest(validity=validity, expiration=expiration, capabilities=capabilities):
                log, fingerprint = self.gpg_fixture(validity, expiration, capabilities)
                before = self.snapshot()
                result = self.setup_git(ok=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(before, self.snapshot())
                self.assertFalse(self.output.exists())
                self.assertIn('--list-secret-keys', log.read_text())
                self.assert_redacted(result, fingerprint, 'gpg@example.invalid')

    def test_valid_gpg_metadata_is_accepted_without_signing_or_login(self):
        self.install()
        log, fingerprint = self.gpg_fixture()
        result = self.setup_git()
        self.assert_redacted(result, fingerprint, 'gpg@example.invalid')
        self.assertEqual(self.git_value('gpg.format').stdout.strip(), 'openpgp')
        self.assertEqual(self.git_value('commit.gpgsign').stdout.strip(), 'true')
        arguments = log.read_text().splitlines()
        self.assertIn('--list-secret-keys', arguments)
        self.assertIn('--batch', arguments)
        self.assertNotIn('--sign', arguments)
        self.assertNotIn('--login', arguments)
        self.assertFalse((self.home / '.gnupg').exists())

    def test_ownership_ledger_cannot_omit_existing_setup(self):
        self.install()
        self.write_input('[user]\n email = initial@example.invalid\n')
        self.setup_git()
        (self.state / 'git-setup.tsv').write_text('')
        self.write_input('[user]\n email = replacement@example.invalid\n')
        before = self.snapshot()
        result = self.setup_git(ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, self.snapshot())
        self.assert_redacted(result, 'initial@example.invalid', 'replacement@example.invalid')

    def test_ownership_ledger_cannot_claim_unrelated_private_file(self):
        self.install()
        self.write_input('[user]\n email = initial@example.invalid\n')
        self.setup_git()
        private = self.home / 'unrelated-private-fixture'
        private.write_text('fixture-only-private-material')
        private.chmod(0o600)
        digest = hashlib.sha256(private.read_bytes()).hexdigest()
        with (self.state / 'git-setup.tsv').open('a') as stream:
            stream.write(digest + '\t' + str(private) + '\n')
        self.write_input('[user]\n email = replacement@example.invalid\n')
        before = self.snapshot()
        result = self.setup_git(ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, self.snapshot())
        self.assert_redacted(result, 'fixture-only-private-material', str(private),
                             'initial@example.invalid', 'replacement@example.invalid')
