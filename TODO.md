# TODO

## Evaluation And Confidence
- [X] Require evaluation evidence for every completed run, and mark runs without benchmark or complexity evidence as incomplete or low-confidence.
- [X] Add a confidence label to final output, such as `safe but unproven`, `measurably improved`, `complexity-reducing cleanup`, or `behavior-preserving cleanup`.
- [X] Define the minimum evidence needed for a run to be considered successful instead of only `tests passed`.

## Scoring And Selection
- [X] Rank candidate changes by measured improvement, not just passing tests.
- [X] Update candidate scoring so verified complexity reduction outranks cosmetic or low-impact rewrites.
- [X] Penalize no-op or near-no-op diffs unless they show measurable benefit.
- [X] Distinguish between safe rewrites and meaningful improvements in survivor selection.

## Mutation Quality
- [X] Separate cleanup mutations from true optimization or complexity-reduction mutations.
- [X] Bias mutation generation toward fewer, higher-signal candidates instead of many trivial rewrites.
- [X] Reduce search-space preference for local refactors like cached lookups, formatting collapse, or variable aliasing unless they support a larger simplification.

## Reporting
- [X] Report net gain per file in the final report.
- [X] Report net gain per accepted change, including whether the result improved complexity, runtime, both, or neither.
- [X] Show when a file had no measurable gain so accepted edits are easier to audit.
- [X] Expand final reporting beyond lineage and survivor counts to include outcome quality and confidence.

## Project Direction (Too high level, Don't worry about this)
- [ ] Build the end-to-end complexity minimizer pipeline described in `INTENT.md`: config, project loading, AST analysis, candidate generation, evaluation, mutation/combination, measurement, and final reporting.
- [ ] Preserve the current stdlib-first design goal from `INTENT.md`, unless there is a deliberate choice to add dependencies.
- [ ] Standardize typing usage across the project, starting from the note in `analyze/ast_parser.py`.
- [ ] Output a graph before running that identifies the scope of the project and how data flows through.
- [ ] If the user specifies more than 1 iteration, allow for loop based genetic evals
- [ ] Nice to have: if the user wants to use Claude Code or another local agent we can let them

## Config And Recovery
- [ ] Generate a `config.json`, clean it up after a full run, and move secrets to a secure path per `config.py`.

## Completed Tasks
### Orchestration And State
- [X] Refactor the AST-loading responsibility out of `main.py` into `project_loader`, since the current note says it acts more like a loader. (ignore)
- [X] Remove or replace the hardcoded debug project path in `main.py`. -> should be accepted to arguments
- [X] Add recovery-aware state usage in `main.py` so saved state is used after crashes, not as the default path. -> needs to handled by --recovery
- [X] Add a manifest/versioning scheme for state compatibility, as called out in `main.py` and `recovery.py`.
- [X] Wrap `STATE_DIR` handling in a cleaner abstraction instead of passing it around everywhere in `main.py`.
- [X] Ensure an `optimized/` output directory exists at startup in `main.py`.
- [X] Consider splitting the top-level workflow in `main.py` into smaller phases/modules.
- [X] Make the import-graph dict assignment safer in `main.py`.
- [X] Consolidate the duplicated JSON persistence code in `state_storage.py`.
- [X] Optionally evaluate Redis for faster state storage if external dependencies become acceptable in `state_storage.py`.

### Config And Recovery
- [X] Replace hardcoded config with generated runtime config as outlined in `config.py`.
- [X] Implement the recovery loader in `recovery.py`.
- [X] Add robust recovery fallbacks, manifest comparison, and failure behavior when requested state is missing in `recovery.py`.
- [X] Wire `main.py --recovery ...` into the orchestration flow described by `recovery.py`.

### Project Loading And Graphing
- [X] Wire root dir from config.py into `file_discover.py`
- [X] Implement test-file discovery in `project_loader/file_discover.py`.
- [X] Replace the string-based import/module matching in `project_loader/entrypoint_detect.py` with a more reliable resolver.
- [X] Implement inter-function call analysis in `analyze/interfunction_calls.py`.
- [X] Implement or extend per-file call tracking hinted by `analyze/file_calls.py`.

### AST Analysis
- [X] Rename the dataclass helper in `analyze/ast_parser.py` as intended so it can't be called outside of the file
- [X] Revisit the AST parser design in `analyze/ast_parser.py`: it currently mixes graph generation with code clipping responsibilities. (Don't worry, I don't know what this goal means)
- [X] Verify the prior recursion issues mentioned in the parser docstring are fully resolved by the iterative approach in `analyze/ast_parser.py`.
- [X] Improve hotspot scoring in `analyze/hotspot_detector.py`, which is currently just `max_nesting + max_conditionals`.
- [X] Replace the hacky "best file" handling in `analyze/hotspot_detector.py` and raise a proper exception when no candidate exists.
- [X] Keep hotspot data derived from AST state rather than persisted separately, per `analyze/hotspot_detector.py`.

### Prompting And LLM Execution
- [X] Generate prompt/task packaging dynamically from config/user input instead of hardcoded constants in `context_builder/prompt_packager.py`.
- [X] Compute a real source hash in `context_builder/prompt_packager.py`.
- [X] Build function contracts dynamically in `context_builder/prompt_packager.py`, including input and return types.
- [X] Fix the LLM client behavior in `llm/llmagent.py` so responses are bounded and non-streaming if that is the intended mode.
- [X] Add a job manager / multi-agent execution model in `llm/llmagent.py`, and expose agent-count configuration to users.
- [X] Fix token count projection and notify in logs if the optimizer can't find a better file.

### Candidate Generation And Optimization Loop
- [X] Implement the first pass of candidate evaluation in `candidates/candidate_evaluation.py`.
- [X] Replace the placeholder candidate inputs in `candidates/candidate_evaluation.py` with real generated mutations instead of reusing the original file source.
- [X] Expand iterative evaluation in `candidates/candidate_evaluation.py` beyond the current `N = 1` loop and make the round count configurable.
- [X] Add candidate-combination logic in `candidates/candidate_evaluation.py` so passing candidates can be reduced and merged across rounds.
- [X] Improve candidate scoring in `candidates/candidate_evaluation.py`; the current implementation picks the first passing candidate and does not compare benchmark results.
- [X] Implement final file rewrite into the optimized project copy in `candidates/final_candidate.py`.
- [X] Emit rewritten Python files into `optimized/` from `candidates/final_candidate.py`.
- [X] Preserve and apply cumulative edits across optimization rounds with explicit mutation tracking instead of treating each file pass independently.
- [X] Replace the final pass/fail-only test run in `main.py` with the intended benchmark stage and diff/report output.
