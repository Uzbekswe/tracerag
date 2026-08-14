# TraceRAG evaluation

Dataset: `clippy-v1` (version `1.1.0`)
Corpus pin: `clippy` @ `d2c4d1532d89488a56ec2c3ca12757117fc0b4e2`
Index schema: `2`
Index generation: `155e178d339748cda6d4f51c61c879c9`
Cache path: `embedding-cache`

| Metric | Value | Gate |
|---|---:|:---:|
| citation_validity | 100.0% | PASS |
| recall_at_5 | 100.0% | PASS |
| factuality | 100.0% | PASS |

## Cases

| ID | Status | Evidence targets | Matched target | Failure |
|---|---|---|---|---|
| c01 | pass | book/src/development/basics.md#basics for hacking on clippy > get the code | book/src/development/basics.md#basics for hacking on clippy > get the code (rank 5) |  |
| c02 | pass | book/src/development/basics.md#push to the master branch of your fork > building and testing | book/src/development/basics.md#push to the master branch of your fork > building and testing (rank 1) |  |
| c03 | pass | book/src/development/basics.md#only run dogfood tests > cargo dev | book/src/development/basics.md#only run dogfood tests > cargo dev (rank 5) |  |
| c04 | pass | book/src/development/adding_lints.md#adding a new lint | book/src/development/adding_lints.md#adding a new lint (rank 1) |  |
| c05 | pass | book/src/development/adding_lints.md#adding a new lint > defining our lint > tests location | book/src/development/adding_lints.md#adding a new lint > defining our lint > tests location (rank 5) |  |
| c06 | pass | book/src/development/emitting_lints.md#emitting a lint > suggestions: automatic fixes > applicability; book/src/development/emitting_lints.md#emitting a lint > suggestions: automatic fixes > example | book/src/development/emitting_lints.md#emitting a lint > suggestions: automatic fixes > applicability (rank 1) |  |
| c07 | pass | book/src/development/lint_passes.md#lint passes; book/src/development/lint_passes.md#lint passes > earlylintpass; book/src/development/lint_passes.md#lint passes > latelintpass > example for latelintpass | book/src/development/lint_passes.md#lint passes (rank 1) |  |
| c08 | pass | book/src/development/writing_tests.md#testing > clippy ui tests | book/src/development/writing_tests.md#testing > clippy ui tests (rank 1) |  |
| c09 | pass | book/src/development/macro_expansions.md#dealing with macros and expansions; book/src/development/macro_expansions.md#dealing with macros and expansions > how to work with macros > the isfromprocmacro function | book/src/development/macro_expansions.md#dealing with macros and expansions (rank 1) |  |
| c10 | pass | book/src/development/common_tools_writing_lints.md#common tools for writing lints > checking for a specific type; book/src/development/defining_lints.md#define new lints > lint types | book/src/development/defining_lints.md#define new lints > lint types (rank 1) |  |
| c11 | pass | book/src/development/the_team.md#the team > clippy-contributors > duties | book/src/development/the_team.md#the team > clippy-contributors > duties (rank 3) |  |
| c12 | pass | book/src/development/method_checking.md#method checking > checking if an expr is calling a specific method; book/src/development/common_tools_writing_lints.md#common tools for writing lints > checking if an expr is calling a specific method | book/src/development/method_checking.md#method checking > checking if an expr is calling a specific method (rank 1) |  |
| c13 | pass |  |  |  |
| c14 | pass |  |  |  |
| c15 | pass |  |  |  |
