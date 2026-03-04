# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability, please report it through [GitHub Security Advisories](https://github.com/MBifolco/gotg/security/advisories/new) rather than opening a public issue.

We will acknowledge receipt within 72 hours and provide an estimated timeline for a fix.

## API Key Safety

GOTG reads API keys from a local `.env` file. To keep your keys safe:

- **Never commit `.env` files.** The `.gitignore` excludes `.env` by default.
- **Never pass API keys as command-line arguments** where they may appear in shell history.
- **Rotate keys immediately** if you suspect they have been exposed.

## File Access Boundaries

GOTG's FileGuard system enforces boundaries on what agents can read and write. If you discover a way to bypass these boundaries, please report it as a security vulnerability.
