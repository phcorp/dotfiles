# Changelog

## cmux

- Add cmux installation, updates, and owned-only removal on macOS, preserving
  existing apps and exposing the bundled CLI. Use WezTerm as the Linux equivalent.

## Desktop application lifecycle

- Add requested desktop apps and documented Linux equivalents to the catalog.
- Add wizard and unattended app installation, update, and owned-only removal.
- Preserve existing applications and app data; keep authentication private.
- Add signed user-scoped Flatpak support and official native GUI installers.

## Project-aware prompt

- Show Node, Lua, and AWS context only in relevant projects and subdirectories.
- Ignore global HOME settings and unrelated parent repositories; keep AWS
  account/profile identities hidden.

## Portable overhaul

- Replace the legacy shell files with chezmoi-managed Bash/Zsh configuration.
- Add portable lifecycle wizard, first-use dependencies, backups, recovery,
  private overrides, and hourly CI-gated pull synchronization.
- Add selectable developer profiles, native Linux installation, verified
  upstream releases, and ownership-aware update/removal.
- Retire unsafe eval-based helpers, destructive Git synchronization, and
  working-directory-dependent PATH entries.
- Add macOS/Linux behavioral tests, package validation, and publication privacy
  checks. Public history starts fresh with a GitHub noreply identity.
