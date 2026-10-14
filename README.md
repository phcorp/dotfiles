# Portable dotfiles

Bash 3.2+ and Zsh on macOS, Debian/Ubuntu, and Fedora. Configuration uses chezmoi,
XDG directories, a shared Starship prompt, and a POSIX-shell lifecycle CLI.
Supported architectures are x86_64 and arm64. Other shells and package managers
are not currently supported.

## Install

Download and review the bootstrap script, then run it:

```sh
curl -fsSLo bootstrap.sh https://raw.githubusercontent.com/phcorp/dotfiles/master/bootstrap.sh
sh bootstrap.sh
```

The wizard selects profiles, preserves existing files, optionally provisions
tools immediately, and offers hourly synchronization. On macOS, Apple Command
Line Tools must be installed first (`xcode-select --install`). A new Homebrew
installation can require administrator access. Homebrew installation code and
upstream binary downloads use pinned versions and SHA-256 checksums.

For unattended installation:

```sh
sh bootstrap.sh --non-interactive --profiles=shell,php,runtimes --sync
```

This saves the noninteractive first-use mode. Existing package managers and
runtime versions are retained; project version files are not rewritten.
Unattended installation never requests a sudo password. Provision root access
or suitable passwordless sudo in advance, or run the interactive wizard.

Profiles: `shell`, `runtimes`, `php`, `cloud`, `databases`, `desktop`.
The wizard filters unsupported platform entries. `dotfiles tools list` displays
the catalog and package mappings. Database profiles install clients, not running
servers. Docker installs the CLI; install/select a container engine separately
(OrbStack is an optional macOS desktop choice). Linux desktop support currently
includes native Firefox; other desktop choices are macOS-only.

## Everyday use

```sh
dotfiles wizard
dotfiles doctor
dotfiles mode interactive
dotfiles install --profiles shell,php --dry-run
dotfiles tools install symfony --non-interactive
dotfiles tools update symfony
dotfiles repair
dotfiles sync
```

Selected tools install on first use in interactive shells. The interactive mode
asks first; noninteractive mode uses saved selections. Existing commands always
win. Arbitrary missing commands are never mapped to packages. Startup itself
does not install software or contact the repository. Noninteractive scripts use
normal executable lookup; provision their dependencies explicitly beforehand.

Upstream tools are version/checksum pinned in `lib/tools-upstream.tsv`; native
packages follow the OS repositories. Tool updates apply only to software
installed and recorded by dotfiles, and do not run as part of automatic sync.

`ls`, `ll`, and `la` use eza when available, with a system `ls` fallback. `sc`
invokes Symfony's `bin/console` or legacy `app/console` with quoted arguments.
`tsplit` passes arguments directly to `tmux split-window`; the former eval-based
multi-pane helper is retired. `ssh-use-key` adds a key to an existing agent.

## Existing machines and private settings

Installation preserves original managed files under
`$XDG_STATE_HOME/dotfiles/originals` (default `~/.local/state/dotfiles/originals`).
Existing Git configuration is copied to a private include, retaining identity,
credential helpers, and conditional includes. Backups and overrides are kept
outside the source checkout, in restricted directories.

For existing shell integrations, review then run this local migration helper
**before installation**:

```sh
python3 ~/.local/share/chezmoi/scripts/migrate-local.py
```

It preserves literal exported settings, installed app hooks, and selected custom
aliases locally. It does not execute old startup files or copy them into Git.
Unsafe legacy helpers and manager initialization are excluded. Review anything
else in your private backup and migrate necessary behavior deliberately.

Private override files under `$XDG_CONFIG_HOME/dotfiles/local/`:

- `env.sh`: portable environment and machine paths.
- `bash.sh`, `zsh.sh`: shell-specific final overrides.
- `pre-bash.sh`, `pre-zsh.sh`: integrations requiring early interactive loading.
- `login-bash.sh`, `login-zsh.sh`, and their `pre-login-*` counterparts: login hooks.
- `gitconfig`: private Git identity and credential settings.

Override files are never imported, committed, or pushed by the CLI. Do not put
credentials in public managed files. Keep credentials in the system credential
store or an independently configured secret manager. Diagnostics do not dump
your environment or command arguments. Shell histories remain local; normal
shell history can still record commands you type, so avoid typing secrets.

Relocated XDG configuration inside HOME is supported, including spaces in paths.
Managed/private directory symlinks that escape HOME are rejected. Tabs/newlines
in installation paths are unsupported.

## Synchronization and publishing

```sh
dotfiles sync enable
dotfiles sync disable
dotfiles publish "Improve shared shell configuration"
```

Hourly pulls use a macOS LaunchAgent, Linux user systemd timer, or cron fallback.
Linux requires a functioning user systemd session or cron daemon; minimal
containers can run `dotfiles sync` directly. Pulls require successful `Verify`
GitHub Actions for the candidate revision. Dirty sources, modified managed
files, diverged histories, rate limits, or unavailable CI stop the update and
preserve the current configuration. Changes appear in the next shell session.
`doctor` reports scheduler configuration and the last lifecycle result.

Automatic synchronization never pushes. Edit public source files, run tests,
then explicitly publish. Publishing and Git hooks enforce public path policy,
GitHub noreply commit identity, and redacted Gitleaks checks. Install Python 3
and Gitleaks before publishing. Git hooks are a convenience; CI and the explicit
publish command also enforce checks.

No scanner can classify every possible private string. The primary privacy
boundary is keeping all machine data and secrets outside the allowlisted public
source. Review public edits before publishing. Rewriting repository history
cannot erase previously downloaded copies or GitHub caches.

## Recovery and uninstall

```sh
dotfiles recover
dotfiles uninstall --dry-run
dotfiles uninstall
dotfiles tools remove symfony
```

Interrupted file transactions can be restored with `recover`. A failed apply
restores the preceding files. `repair` refuses local managed edits; move those
edits to private overrides or use `repair --force` only after review.

Uninstallation disables sync and restores original files. Modified managed
files are retained and reported with a nonzero exit status. Private overrides,
backups, source checkout, and installed software remain. Explicit tool removal
requires dotfiles ownership, rejects installed dependents, and refuses language
runtime removal. Keep original backups until you have validated recovery.

## Validation

```sh
tests/run.sh
scripts/check-public.sh
gitleaks dir --redact
gitleaks git --redact
```

Tests use disposable homes and temporary Git repositories. CI covers macOS and
Linux shell behavior plus actual Ubuntu, Debian, and Fedora package installs.
Bootstrap downloads and release checksums should be refreshed deliberately,
with installation tests, when adopting new upstream versions.
