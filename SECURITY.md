# Security Policy

## Supported Versions

Security fixes are applied to the latest released version.

## Reporting a Vulnerability

Please report vulnerabilities through GitHub Security Advisories:

1. Open the repository Security tab.
2. Click "Report a vulnerability".
3. Include reproduction details, impact, and any suggested fix.

If private reporting is unavailable, open a private channel with the maintainer and avoid posting exploit details publicly.

## Secrets and Credentials

- Never commit API keys, tokens, session files, or `.env` files.
- Use repository secrets for CI publishing credentials.
- Rotate credentials immediately if exposed in terminal output, logs, screenshots, or chat.
