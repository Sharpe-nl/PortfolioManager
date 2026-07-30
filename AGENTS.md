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

- `VERSION` is the shipped application version and must use Semantic Versioning.
- For every commit that changes user-visible behaviour, security, database
  schema or deployment, bump `VERSION` and add a concise user-facing entry to
  `CHANGELOG.md` in the same commit.
- Do not bump the version for internal refactors, tests or documentation-only
  corrections that do not affect the shipped application.
- While the project is in beta, use prerelease iterations such as
  `0.1.0-beta.1`, then `0.1.0-beta.2`. A stable release removes the prerelease
  suffix; backwards-compatible fixes increment the patch version afterwards.

## Implementation

- Keep server-rendered pages accessible without JavaScript where practical.
- Reuse the existing liquid-glass design tokens and responsive breakpoints.
- Add or update translations for user-facing strings in both English and Dutch.
- Keep SQLite changes in a new, ordered migration; do not edit applied migrations.

## Verification

- Run `python -m py_compile` for changed Python modules.
- Run `pytest` before handing off changes.
- Run `git diff --check` before committing.
