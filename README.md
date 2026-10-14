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
(OrbStack or its Linux equivalent, Podman Desktop, is a desktop choice).

## Desktop apps

Select `desktop` in the wizard or save it with the other profiles you use, then
choose the wizard's app installation, update, or removal option. Equivalent
Linux applications retain the catalog ID of the requested macOS application.
Use `dotfiles apps list` to see the package mappings.

```sh
dotfiles repair --profiles shell,runtimes,php,cloud,databases,desktop
dotfiles apps install --non-interactive
dotfiles apps update hoppscotch --non-interactive
dotfiles apps remove hoppscotch --non-interactive
```

`apps install` and `apps update` without an ID operate on selected desktop apps;
`apps remove` without an ID removes only desktop apps recorded as installed by
dotfiles. `--dry-run` changes no files or packages. Existing apps are detected
before installation and are never silently adopted for removal. Normal dotfiles
uninstallation retains apps; application removal is a separate, explicit action.
Application data, login sessions, and shared dependencies are retained. No app
is launched or signed in during provisioning.

| Catalog ID | macOS | Linux |
| --- | --- | --- |
| `claude-desktop` | Claude | Official Claude desktop beta on Debian/Ubuntu |
| `chatgpt` | ChatGPT, including Codex | Official ChatGPT Linux preview |
| `codexbar` | CodexBar | Official CodexBar desktop |
| `cyberduck` | Cyberduck | FileZilla (FTP/SFTP; not all Cyberduck cloud backends) |
| `github-desktop` | GitHub Desktop | Community Linux GitHub Desktop fork |
| `orbstack` | OrbStack | Podman Desktop and Podman |
| `hoppscotch` | Hoppscotch | Official desktop: amd64 DEB or AppImage |
| `mutekey` | MuteKey (Mac App Store) | Microphone toggle using PulseAudio/PipeWire |
| `sequel-ace` | Sequel Ace | DBeaver Community |
| `stats` | Stats | Mission Center |

Official [Claude](https://claude.com/download) and
[ChatGPT/Codex](https://chatgpt.com/download) Linux desktop releases are currently
beta/preview. Claude requires Ubuntu 22+ or Debian 12+; ChatGPT requires Ubuntu
24+, Debian 13+, or Fedora 43+. Unsupported platform entries are excluded from
selection. CodexBar's Linux desktop requires glibc 2.39+ and Qt 6.4+; the official
CLI remains available on older supported Linux systems. Hoppscotch's published
Linux desktop binaries currently support amd64 only.

Native downloads are pinned in `lib/tools-desktop.tsv`, with SHA-256 validation;
Claude and ChatGPT also verify signed vendor repository metadata using pinned
public keys. Updating these downloads to a new release requires a reviewed
manifest update and repository synchronization. An existing newer native
installation is retained. Credentials and application settings never enter
these manifests or the dotfiles repository.

Linux Flatpak apps use a signed Flathub remote and per-user installations. Shared
Flatpak runtimes and the remote are retained on removal. Native GUI installers
require a working graphical desktop to run their apps; headless containers can
verify installation but cannot exercise their windows. macOS MuteKey requires
an Apple account signed in to the Mac App Store and may request Apple
authentication per app. Its installation and update require interactive mode;
unattended setup reports this requirement instead of opening authentication
prompts. Existing MuteKey installations are preserved. On Linux, `mutekey`
toggles the default microphone through `pactl` only when invoked; bind the command
to a desktop shortcut if desired. Provisioning never changes microphone state.

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
packages follow the OS repositories. Explicit updates can also update existing
apps registered with the supported package manager, without granting removal
ownership. Apps installed outside that manager retain their original updater.
Updates do not run as part of automatic sync.

`ls`, `ll`, and `la` use eza when available, with a system `ls` fallback. `sc`
invokes Symfony's `bin/console` or legacy `app/console` with quoted arguments.
`tsplit` passes arguments directly to `tmux split-window`; the former eval-based
multi-pane helper is retired. `ssh-use-key` adds a key to an existing agent.

Node, Lua, and AWS prompt indicators appear only in matching projects, including
their subdirectories. Global settings in HOME never count as project markers;
scanning stops at HOME or a Git repository boundary. Node requires a package,
lockfile, local version file, or `node_modules`, rather than arbitrary JavaScript.
AWS detection recognizes SAM/CDK/Amplify, AWS SDK dependencies, AWS Terraform
providers/resources, and AWS Serverless/CloudFormation templates. Add an empty
`.aws-project` file for an AWS project without those standard markers. Only its
region is displayed; account identities stay hidden. Detection reads bounded
configuration files and never executes project scripts or contacts cloud APIs.

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

Set `DOTFILES_INIT_RVM=0` in private environment overrides to keep an installed
RVM from initializing in a shell that normally uses another Ruby installation.

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
publish command also enforce checks. Bootstrap provides Python 3; publishing
installs selected Gitleaks automatically if needed.

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
