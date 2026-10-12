# Security

## Model

Atelier is a **single-user, local** application. It listens on `127.0.0.1` only and must not be exposed to a
network. Protections: local `Host` only, same-origin `Origin`, `Sec-Fetch-Site` filtering on `/api/*`,
resolved and confined file paths, argument-list subprocesses, sandboxed document reading (pandoc).

## Reporting a vulnerability

Please use GitHub's **private vulnerability reporting** (Security tab → *Report a vulnerability*) rather than
a public issue. Include the version/commit, a minimal reproduction and the impact you expect. I aim to
acknowledge reports within a week.

## Out of scope

- Exposing the service to an untrusted network or running it as a shared multi-user server.
- Vulnerabilities in the third-party tools Atelier drives (report those upstream).
