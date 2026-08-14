# Security policy

## Supported versions

| Version | Security support |
|---|---|
| 1.2.x | Supported |
| 1.1.x and older | Best effort only |

TraceRAG is a local-first terminal application with a local-only trust boundary.
It is not a hosted service and
does not provide authentication, tenant isolation, or a public HTTP API.

## Trust boundary

- Treat ingested documents, corpus checkouts, and local model responses as
  untrusted input. Do not ingest sensitive or hostile material in a shared
  process without an operating-system sandbox.
- Ollama is expected to remain on loopback. Do not expose its port or add a
  database listener; TraceRAG uses its embedded SQLite vector store.
- The optional container runs as a non-root user and mounts documents
  read-only. Keep the data volume private and review compose changes before
  granting additional write access.
- Dependency and CI inputs are pinned or monitored. Review Dependabot updates
  and rerun the locked deterministic checks before merging them.

## Reporting a vulnerability

For a private disclosure, use GitHub's private vulnerability reporting or
security-advisory channel when it is available for this repository. Otherwise,
contact the repository owner through GitHub before opening a public issue.
Please include the affected version, reproduction steps, impact, and any
required configuration. Do not include private documents, credentials, or
model files in a report.

Please allow time for triage and a coordinated fix before public disclosure.

## Verification limits

The repository runs dependency auditing, Bandit, CodeQL, secret scanning where
GitHub makes it available, and deterministic tests. These checks reduce risk;
they are not a malware certification or a guarantee that every document,
dependency, model, or host configuration is safe.
