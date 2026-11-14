# Security Policy

Stashboard handles personal financial data, so security reports are taken seriously.

## Supported versions

Only the latest release on the `main` branch receives security fixes.

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Report them privately through GitHub:
**Security → Report a vulnerability** on this repository
(<https://github.com/branislav0/stashboard/security/advisories/new>).

Include what you found, how to reproduce it, and the impact you expect. You should get a
first response within a week. Please give a reasonable amount of time for a fix before
disclosing anything publicly.

## Deployment notes

- Stashboard is a **single-user** app protected by one password. It binds to `127.0.0.1`
  by default — do not expose it directly to the internet; put a VPN or an authenticated
  reverse proxy in front of it.
- Secrets live in `.env` and `.secrets/` and the database in `finance.db`. All of them are
  git-ignored; never commit them, and keep your backups private.
- Bank access uses PSD2 consents through Enable Banking. Revoke a consent in your bank or
  in the Enable Banking dashboard if you suspect it has leaked.
