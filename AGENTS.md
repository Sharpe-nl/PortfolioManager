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

## Implementation

- Keep server-rendered pages accessible without JavaScript where practical.
- Reuse the existing liquid-glass design tokens and responsive breakpoints.
- Add or update translations for user-facing strings in both English and Dutch.
- Keep SQLite changes in a new, ordered migration; do not edit applied migrations.

## Verification

- Run `python -m py_compile` for changed Python modules.
- Run `pytest` before handing off changes.
- Run `git diff --check` before committing.
