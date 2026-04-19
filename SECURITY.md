# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅ Current |

Pre-1.0 releases receive security fixes on a best-effort basis.
After `1.0.0` is tagged, we will maintain a clear support window.

## Responsible Disclosure

If you discover a security vulnerability in OpenMobility OS, please **do not**
open a public GitHub issue. Instead:

1. **Email** the maintainers at the address listed in the repository profile, **or**
2. **Open a [GitHub Security Advisory](https://github.com/richardkfm/openmobility-os/security/advisories/new)**
   (private, visible only to maintainers).

Include as much detail as you can:
- A description of the vulnerability and its potential impact
- Steps to reproduce (proof of concept, if available)
- Affected versions
- Any suggested mitigations

We will acknowledge your report within **72 hours**, provide an initial
assessment within **7 days**, and coordinate a fix and disclosure timeline
with you.

We appreciate responsible disclosure and will credit researchers in the
release notes unless they prefer to remain anonymous.

## Threat Model

OpenMobility OS is designed to be self-hosted by municipalities. The
following are **in scope** for security reports:

- Authentication bypass or privilege escalation (ADMIN_TOKEN exposure)
- SQL injection or arbitrary query execution
- Cross-site scripting (XSS) in templates
- Server-side request forgery (SSRF) in connector URL handling
- Path traversal or arbitrary file read/write
- Remote code execution via crafted data sources

The following are **out of scope**:

- Vulnerabilities in third-party dependencies that are already publicly known
  (report those to the upstream project)
- Issues requiring physical access to the server
- Social engineering

## Hardening Checklist for Self-Hosters

Before exposing an instance to the internet:

- [ ] Set a strong, random `SECRET_KEY` (never use the default)
- [ ] Set a strong, random `ADMIN_TOKEN`
- [ ] Set `DEBUG=False`
- [ ] Restrict `ALLOWED_HOSTS` to your domain(s)
- [ ] Run behind a reverse proxy (Nginx, Caddy) with TLS
- [ ] Ensure the `db` service is NOT exposed on a public port
- [ ] Rotate the `ADMIN_TOKEN` periodically and after any personnel change
