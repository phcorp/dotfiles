import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class PublicPolicy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dotfiles-public-test-')
        self.addCleanup(self.tmp.cleanup)
        self.repo = pathlib.Path(self.tmp.name)
        (self.repo / 'scripts').mkdir()
        shutil.copy2(ROOT / 'scripts/check-public.sh', self.repo / 'scripts/check-public.sh')
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True, capture_output=True)
        for key, value in [('user.name', 'fixture'), ('user.email', 'fixture@users.noreply.github.com')]:
            subprocess.run(['git', '-C', str(self.repo), 'config', key, value], check=True, capture_output=True)

    def scan(self):
        return subprocess.run([str(self.repo / 'scripts/check-public.sh')],
                              cwd=self.repo, text=True, capture_output=True, timeout=10)

    def test_generic_documentation_is_allowed(self):
        (self.repo / 'README.md').write_text('Configure private Git identity in local overrides.\n')
        result = self.scan()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_private_paths_and_identity_are_rejected(self):
        (self.repo / '.env').write_text('EXAMPLE=value\n')
        (self.repo / 'home').mkdir()
        (self.repo / 'home/dot_gitconfig').write_text('[user]\n    email = fixture@example.invalid\n')
        result = self.scan()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('private file path', result.stderr)
        self.assertIn('private identity', result.stderr)
        self.assertNotIn('fixture@example.invalid', result.stderr)

    def test_private_commit_identity_is_rejected_without_exposure(self):
        subprocess.run(['git', '-C', str(self.repo), 'config', 'user.email', 'private@example.invalid'], check=True)
        result = self.scan()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('publication identity', result.stderr)
        self.assertNotIn('private@example.invalid', result.stderr)

    def test_private_history_is_rejected_without_exposure(self):
        (self.repo / 'README.md').write_text('public content\n')
        subprocess.run(['git', '-C', str(self.repo), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.repo), '-c', 'core.hooksPath=/dev/null',
                        '-c', 'user.email=private@example.invalid', 'commit', '-qm', 'fixture'], check=True)
        result = self.scan()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('nonpublic author or committer', result.stderr)
        self.assertNotIn('private@example.invalid', result.stderr)

    def test_github_merge_committer_is_allowed(self):
        (self.repo / 'README.md').write_text('public content\n')
        subprocess.run(['git', '-C', str(self.repo), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.repo), '-c', 'core.hooksPath=/dev/null',
                        'commit', '-qm', 'public merge'], check=True,
                       env=dict(os.environ, GIT_COMMITTER_NAME='GitHub',
                                GIT_COMMITTER_EMAIL='noreply@github.com'))
        result = self.scan()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_github_committer_does_not_allow_private_author(self):
        (self.repo / 'README.md').write_text('public content\n')
        subprocess.run(['git', '-C', str(self.repo), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.repo), '-c', 'core.hooksPath=/dev/null',
                        'commit', '-qm', 'private merge'], check=True,
                       env=dict(os.environ, GIT_AUTHOR_EMAIL='private@example.invalid',
                                GIT_COMMITTER_NAME='GitHub',
                                GIT_COMMITTER_EMAIL='noreply@github.com'))
        result = self.scan()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('nonpublic author or committer', result.stderr)
        self.assertNotIn('private@example.invalid', result.stderr)

    def test_staged_private_content_cannot_hide_in_clean_worktree(self):
        (self.repo / 'home').mkdir()
        target = self.repo / 'home/dot_gitconfig'
        target.write_text('[user]\n    email = private@example.invalid\n')
        subprocess.run(['git', '-C', str(self.repo), 'add', '.'], check=True)
        target.write_text('[init]\n    defaultBranch = main\n')
        result = self.scan()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('private identity', result.stderr)
        self.assertNotIn('private@example.invalid', result.stderr)

    def test_public_symlink_is_rejected_without_reading_target(self):
        (self.repo / 'README.md').symlink_to('/dev/null')
        result = self.scan()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('symlink', result.stderr)
