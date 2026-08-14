# Clippy manual factuality review

This is the human-review companion to the 2026-08-14 H5 run of
`evals/dataset/clippy-v1.json`. The automated report is deterministic; this
table is intentionally separate so the semantic result remains auditable.

| ID | Verdict | Review note |
|---|:---:|---|
| c01 | PASS | The cited development guide explains how to get the Clippy source code. |
| c02 | PASS | Build and test guidance is supported by the cited passages. |
| c03 | PASS | cargo dev usage is supported by the cited development guide. |
| c04 | PASS | New-lint authoring steps are supported by the cited section. |
| c05 | PASS | Test locations are supported by the cited section. |
| c06 | PASS | Suggestions and applicability are supported by the cited passages. |
| c07 | PASS | EarlyLintPass and LateLintPass distinctions are cited. |
| c08 | PASS | Clippy UI-test guidance is cited. |
| c09 | PASS | Macro and expansion handling is cited. |
| c10 | PASS | Type-inspection tools are cited. |
| c11 | PASS | Team duties are supported by the cited guide. |
| c12 | PASS | The cited method-checking passages show how to detect calls to a specific method. |

Result: 12/12 in-scope answers passed this semantic review (100%). Out-of-scope
refusal records are diagnostic and remain outside the semantic denominator.
