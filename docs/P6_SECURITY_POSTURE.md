# v1.2 security posture

This record captures the P6 checks for the private repository. It describes
what was verified; it is not a malware certification.

## Repository controls

Verified through the GitHub repository API on 2026-08-15:

- Repository visibility remains private.
- Dependabot vulnerability alerts are enabled.
- Dependabot automated security fixes are enabled.
- Code scanning and secret scanning are unavailable on the current plan because
  GitHub reports that Advanced Security has not been purchased.

The repository includes a commit-pinned CodeQL workflow that performs analysis
without uploading SARIF (`upload: false`) because the current plan does not
permit code-scanning storage. The local Bandit check remains an independent
static-analysis gate.

## Local checks

- Locked runtime dependency export audited with `pip-audit`: no known
  vulnerabilities.
- `bandit -q -r tracerag -ll`: no medium/high findings.
- Tracked-file credential pattern scan: no matches.
- Tracked-file artifact scan: no generated data, reports, databases, pickles,
  binaries, or model files.
- Docker image build and non-root `--help`/`doctor` smoke checks passed without
  requiring model inference. The container correctly reports Ollama unavailable
  when no host service is provided.

The local-only boundary remains deliberate: TraceRAG uses an embedded SQLite
vector store, does not start a Chroma server, and expects Ollama on loopback.
