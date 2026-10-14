# Changelog

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
