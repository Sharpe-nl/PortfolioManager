# PortfolioManager contributor guide

## Scope and safety

- Keep the application self-hostable and dependency-light.
- Never commit `data/`, database backups, certificates, `.env` files, or real API keys.
- Treat the Logo.dev key as a publishable browser key; do not introduce secret Logo.dev keys.
- Preserve existing user changes and use `apply_patch` for source edits.

## Git workflow

- Do not commit directly to the default branch.
- Work on a dedicated development branch for each coherent change.
- Before merging, open a pull request that explains the change and includes verification results.
- Keep pull requests focused; do not mix unrelated refactors with feature or bug-fix work.

## Versioning and changelog

- `VERSION` is the shipped application version and must use Semantic
  Versioning (`MAJOR.MINOR.PATCH`).
- Increment `MAJOR` only for intentionally incompatible changes that require
  users to change configuration, data or workflow. Increment `MINOR` for new,
  backwards-compatible functionality. Increment `PATCH` for backwards-compatible
  bug fixes, security fixes and small user-visible corrections.
- For every commit that changes user-visible behaviour, security, database
  schema or deployment, choose the appropriate version increment and add
  release notes to `CHANGELOG.md` in the same commit.
- Release notes must be user-facing and grouped under relevant headings such
  as `Added`, `Changed`, `Fixed`, `Security`, `Deprecated` or `Removed`. They
  must clearly call out upgrades that require user action.
- Do not bump the version for internal refactors, tests or documentation-only
  corrections that do not affect the shipped application.

## Implementation

- Keep server-rendered pages accessible without JavaScript where practical.
- Reuse the existing liquid-glass design tokens and responsive breakpoints.
- Add or update translations for user-facing strings in both English and Dutch.
- Keep SQLite changes in a new, ordered migration; do not edit applied migrations.

## Verification

- Run `python -m py_compile` for changed Python modules.
- Run `pytest` before handing off changes.
- Run `git diff --check` before committing.
