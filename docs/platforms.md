# Platforms and prerequisites

## Supported configurations

| Area | Support |
| --- | --- |
| Shell | Bash 3.2+ and Zsh |
| Operating system | macOS, Debian/Ubuntu Linux, Fedora Linux |
| Architecture | x86_64 and arm64 |
| Native package managers | Homebrew, apt, dnf |
| Desktop package backends | macOS casks/App Store, signed native packages, per-user Flatpak |
| Configuration locations | XDG directories inside HOME; spaces in paths supported |

Other shells, Windows, and other Linux package managers are not currently
supported. Tool and desktop-app requirements can be stricter than shell support;
unsupported catalog entries are excluded from selection.

macOS needs Apple Command Line Tools before bootstrapping. Bootstrap provisions
Git, curl, jq, Python 3, and pinned chezmoi; Linux also provisions unzip and CA
certificates. Homebrew installation code and upstream release downloads use
pinned SHA-256 checksums. Existing installations are preserved.

## Interactive and unattended installation

Interactive first use asks before installing a selected missing tool. Unattended
mode uses saved selections and never waits for a sudo password. Provision root
access or suitable passwordless sudo before using it. Missing privileges produce
an actionable failure. Unknown missing commands never become package names.

Noninteractive shell scripts use ordinary executable lookup. Install their
requirements explicitly before running them:

```sh
dotfiles tools install symfony --non-interactive
dotfiles apps install hoppscotch --non-interactive
```

App Store authentication can require human interaction even for a free app.
MuteKey installation/update therefore requires interactive mode on macOS.
[Application requirements](applications.md) describe Linux desktop restrictions.

## Synchronization

Hourly pulls use a macOS LaunchAgent, Linux user systemd timer, or cron fallback.
Linux needs a functioning user systemd session or cron daemon. Headless containers
can use `dotfiles sync` directly without a scheduler. Startup does not poll GitHub.

Bootstrap and synchronization require the latest Verify **push** run for the
exact candidate SHA and configured branch to be completed successfully. A pull
request run or a success from an earlier commit does not qualify. API failures,
rate limits, malformed responses, and newer pending/failed runs fail closed.
Authentication, when supplied through `GITHUB_TOKEN`, uses a temporary owner-only
curl header file and is not placed in process arguments or diagnostics.

## Validation

```sh
tests/run.sh
scripts/check-public.sh
gitleaks dir --redact
gitleaks git --redact
```

Tests use isolated homes, local Git fixtures, and mocked services. CI includes
macOS/Linux shell and lifecycle checks and actual Ubuntu, Debian, and Fedora
package installations. Shell syntax and ShellCheck target portable shell code.

A headless installation test does not prove that an application window, login,
keyring, microphone, or virtualization session works. Validate those features in
a real graphical session after provisioning. Refresh pinned releases deliberately,
with relevant installation tests, rather than during shell startup.
