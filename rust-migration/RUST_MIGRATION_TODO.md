# Rust Migration TODO

## Scope

- [ ] Keep the Python CLI, state storage, recovery, final project writes, diffs, and reports.
- [ ] Move context generation, orchestration, and candidate evaluation to Rust.
- [ ] Do not port `orchestrator/runners/*`.
- [ ] Replace rather than port `context_builder/prompt_packager.py` with a static, multi-file backward slicer.

## 1. Establish the Python/Rust Boundary

- [ ] Create a Rust workspace with a single `self-optimize-core` binary.
- [ ] Add a versioned JSON request schema sent from the Python CLI to the Rust binary.
- [ ] Include target paths, configured test and benchmark commands, candidate settings, and supplied optimization targets in each request.
- [ ] Define a versioned JSON result schema containing contexts, candidate decisions, accepted file replacements, command outcomes, and diagnostics.
- [ ] Keep state/recovery persistence and report generation in Python; Rust must return data rather than write those artifacts.
- [ ] Add a Python subprocess adapter behind a feature flag, retaining the current Python path as the fallback during migration.
- [ ] Reject unsupported protocol versions and surface structured Rust diagnostics through the Python CLI.

## 2. Port Candidate Evaluation First

- [ ] Define Rust types for candidate payloads, external dependencies, command results, evaluation rounds, and final selections.
- [ ] Validate candidate JSON and reject malformed or unparsable candidate source without aborting unrelated candidates.
- [ ] Create isolated candidate project copies and apply one candidate at a time.
- [ ] Run configured tests as the mandatory acceptance gate.
- [ ] Run configured benchmarks, record duration and exit status, and use results for ranking rather than acceptance.
- [ ] Reimplement AST complexity scoring and diff-size calculation.
- [ ] Preserve ranking behavior: evidence-backed complexity reductions first, then benchmark improvement, complexity score, and smaller diffs.
- [ ] Reimplement candidate deduplication, survivor selection, combination rounds, and safe fallback to baseline source.
- [ ] Return the selected source and complete evaluation metadata to Python for final file writes and reporting.

## 3. Build Python Static Analysis in Rust

- [ ] Add `rustpython-parser` as the focused Python parsing dependency; keep other dependencies minimal.
- [ ] Parse files into source spans, imports, module-level definitions, methods, calls, references, and globals.
- [ ] Build a project module index from discovered Python files.
- [ ] Resolve project-local absolute and relative imports.
- [ ] Distinguish project-local dependencies from external modules.
- [ ] Emit deterministic, structured parse and resolution diagnostics instead of silently omitting unsupported source constructs.
- [ ] Keep v1 Python-specific; defer a language-adapter abstraction until another language is being implemented.

## 4. Implement the New Transitive Backward Slice Context

- [ ] Accept a target symbol or source span as the slice root.
- [ ] Trace project-local callers, referenced definitions, imported symbols, and required globals backward from that root.
- [ ] Continue transitively across files until dependencies are exhausted or the configured context budget is reached.
- [ ] Deduplicate symbols, detect cycles, and preserve deterministic source ordering.
- [ ] Attach file paths and exact source spans to every included symbol.
- [ ] Represent external modules as compact dependency metadata; do not include external source.
- [ ] Apply configurable source-size or token budgets with deterministic truncation.
- [ ] Return omitted dependencies and the truncation reason so candidate generation can identify incomplete context.
- [ ] Replace the current prompt-packager contract with this slice result before Rust orchestration becomes the default.

## 5. Port Orchestration Without Runners

- [ ] Have Rust orchestration consume supplied optimization targets or slice roots; do not select, expand, or invoke existing runners.
- [ ] For each supplied target, generate its backward-slice context, request candidates, evaluate them, and return accepted edits.
- [ ] Preserve cumulative working-tree behavior so later targets evaluate against previously accepted edits.
- [ ] Move Codex subprocess invocation to Rust after evaluator parity is established.
- [ ] Preserve the current candidate JSON schema and allow partial worker failures when at least one usable candidate remains.
- [ ] Return per-target progress and diagnostics to Python so it can update state and final reports.

## 6. Roll Out Incrementally

- [ ] Add a Rust evaluator shadow mode that compares Python and Rust acceptance, ranking, selected source, and command records.
- [ ] Enable Rust evaluation by default only after representative parity tests pass.
- [ ] Add a Rust orchestration shadow mode while Python still owns target selection and lifecycle management.
- [ ] Enable Rust orchestration by default only after its returned edits produce the same Python-managed state and reports.
- [ ] Introduce Rust backward-slice context generation as the default context source after its golden tests pass.
- [ ] Retain the Python fallback for one stable release cycle, then remove superseded Python evaluation, orchestration, and context code.

## Verification

- [ ] Add JSON contract tests for valid messages, unknown fields, and unsupported protocol versions.
- [ ] Add evaluator differential tests using the same candidate fixtures in Python and Rust.
- [ ] Add parser and module-resolution tests for imports, aliases, methods, globals, cycles, and malformed Python.
- [ ] Add golden slice tests for multi-file transitive dependencies, cycles, external imports, and budget truncation.
- [ ] Add end-to-end Python CLI tests for successful Rust results, Rust diagnostics, and Rust process failure.
- [ ] Confirm Python state/recovery and reports are unchanged when the Rust path is used.
- [ ] Confirm the Rust path neither imports nor invokes existing runners.
