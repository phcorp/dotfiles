import copy
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHA = 'a' * 40


def run_record(**changes):
    run = dict(id=100, run_number=8, run_attempt=1, name='Verify',
               path='.github/workflows/verify.yml', event='push', head_branch='master',
               head_sha=SHA, status='completed', conclusion='success',
               repository={'full_name': 'phcorp/dotfiles'},
               head_repository={'full_name': 'phcorp/dotfiles'})
    run.update(changes)
    return run


@unittest.skipUnless(shutil.which('jq'), 'jq is required')
class CommitCI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dotfiles-ci-')
        self.addCleanup(self.tmp.cleanup)
        self.home = pathlib.Path(self.tmp.name)
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        self.response = self.home / 'response.json'
        self.log = self.home / 'curl.json'
        curl = self.bin / 'curl'
        curl.write_text(f'#!{sys.executable}\n' + '''import json, os, pathlib, sys
args = sys.argv[1:]
pathlib.Path(os.environ['CURL_LOG']).write_text(json.dumps(args))
if os.environ.get('CURL_FAIL'):
    print('private request diagnostics', file=sys.stderr)
    sys.exit(22)
pathlib.Path(args[args.index('-o') + 1]).write_bytes(pathlib.Path(os.environ['CI_RESPONSE']).read_bytes())
''')
        curl.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.home), CI_RESPONSE=str(self.response),
                        CURL_LOG=str(self.log), PATH=str(self.bin) + ':' + os.environ['PATH'])
        for key in ['GITHUB_TOKEN', 'DOTFILES_REPOSITORY', 'DOTFILES_BRANCH', 'DOTFILES_SYNC_SKIP_CI', 'DOTFILES_TESTING']:
            self.env.pop(key, None)

    def check(self, response, expected=True, repository=None, branch=None):
        self.response.write_text(response if isinstance(response, str) else json.dumps(response))
        if repository:
            self.env['DOTFILES_REPOSITORY'] = repository
        if branch:
            self.env['DOTFILES_BRANCH'] = branch
        result = subprocess.run(['/bin/sh', '-c', '. "$1"; ci_verify_commit "$2"',
                                 'ci-test', str(ROOT / 'lib/ci.sh'), SHA],
                                env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode == 0, expected, result.stderr)
        self.assertEqual(result.stdout, '')
        return result

    def test_valid_exact_commit(self):
        self.check({'total_count': 1, 'workflow_runs': [run_record()]})
        args = json.loads(self.log.read_text())
        url = next(x for x in args if x.startswith('https://api.github.com/'))
        self.assertIn('head_sha=' + SHA, url)
        self.assertIn('event=push', url)
        self.assertNotIn('status=completed', url)

    def test_latest_failed_or_incomplete_cannot_be_hidden(self):
        for changes in [dict(conclusion='failure'), dict(status='queued', conclusion=None),
                        dict(status='in_progress', conclusion=None), dict(conclusion='cancelled')]:
            with self.subTest(changes=changes):
                older = run_record(id=99, run_number=7)
                self.check({'total_count': 2, 'workflow_runs': [older, run_record(**changes)]}, False)

    def test_latest_run_and_rerun_attempt(self):
        self.check({'total_count': 2, 'workflow_runs': [run_record(id=99, run_number=7, conclusion='failure'), run_record(run_attempt=2)]})

    def test_wrong_identity_or_workflow_never_qualifies(self):
        for changes in [dict(head_sha='b' * 40), dict(head_branch='feature'), dict(event='pull_request'),
                        dict(name='Other'), dict(path='.github/workflows/other.yml'),
                        dict(repository={'full_name': 'other/dotfiles'}),
                        dict(head_repository={'full_name': 'fork/dotfiles'})]:
            with self.subTest(changes=changes):
                self.check({'total_count': 1, 'workflow_runs': [run_record(**changes)]}, False)

    def test_missing_malformed_and_truncated_responses(self):
        invalid = ['', 'not-json', '{}', 'null', '[]', {'message': 'API rate limit exceeded'},
                   {'total_count': 0, 'workflow_runs': []},
                   {'total_count': 101, 'workflow_runs': [run_record()]},
                   {'total_count': '1', 'workflow_runs': [run_record()]},
                   {'total_count': 1, 'workflow_runs': {}},
                   {'total_count': 2, 'workflow_runs': [run_record(), run_record()]},
                   {'total_count': 1, 'workflow_runs': [None]}]
        for field in run_record():
            broken = copy.deepcopy(run_record())
            del broken[field]
            invalid.append({'total_count': 1, 'workflow_runs': [broken]})
        for response in invalid:
            with self.subTest(response=response):
                self.check(response, False)

    def test_invalid_status_and_numeric_fields(self):
        for changes in [dict(status='banana'), dict(conclusion='green'), dict(id='100'),
                        dict(run_number=0), dict(run_attempt=1.5), dict(run_attempt=True)]:
            with self.subTest(changes=changes):
                self.check({'total_count': 1, 'workflow_runs': [run_record(**changes)]}, False)

    def test_configured_repository_branch(self):
        run = run_record(head_branch='release/review', repository={'full_name': 'team/config'},
                         head_repository={'full_name': 'team/config'})
        self.check({'total_count': 1, 'workflow_runs': [run]}, repository='git@github.com:team/config.git', branch='release/review')
        args = json.loads(self.log.read_text())
        self.assertTrue(any('/repos/team/config/' in arg and 'branch=release%2Freview' in arg for arg in args))

    def test_failed_network_and_test_flags_never_bypass(self):
        self.env.update(CURL_FAIL='1', DOTFILES_TESTING='1', DOTFILES_SYNC_SKIP_CI='1')
        result = self.check({'total_count': 1, 'workflow_runs': [run_record()]}, False)
        self.assertNotIn('private request diagnostics', result.stderr)

    def test_token_is_not_reported(self):
        self.env.update(GITHUB_TOKEN='fixture-private-token', CURL_FAIL='1')
        result = self.check('{}', False)
        self.assertNotIn('fixture-private-token', result.stdout + result.stderr)

    def test_bootstrap_embedded_policy_identical(self):
        text = (ROOT / 'bootstrap.sh').read_text()
        embedded = text.split('# BEGIN EMBEDDED CI VALIDATOR\n', 1)[1].split('# END EMBEDDED CI VALIDATOR', 1)[0]
        self.assertEqual(embedded, (ROOT / 'lib/ci.sh').read_text())

    def test_documented_workflow_reference_paths(self):
        for path in ['.github/workflows/verify.yml@master', '.github/workflows/verify.yml@refs/heads/master']:
            with self.subTest(path=path):
                self.check({'total_count': 1, 'workflow_runs': [run_record(path=path)]})
        self.check({'total_count': 1, 'workflow_runs': [run_record(path='.github/workflows/verify.yml@other')]}, False)
