# TODO

## Project Direction (Too high level, Don't worry about this)
- [ ] Build the end-to-end optimizer pipeline described in `INTENT.md`: config, project loading, AST analysis, candidate generation, evaluation, mutation/combination, benchmarking, and final reporting.
- [ ] Preserve the current stdlib-first design goal from `INTENT.md`, unless there is a deliberate choice to add dependencies.
- [ ] Standardize typing usage across the project, starting from the note in `analyze/ast_parser.py`.

## Orchestration And State
- [X] Refactor the AST-loading responsibility out of `main.py` into `project_loader`, since the current note says it acts more like a loader. (ignore)
- [ ] Remove or replace the hardcoded debug project path in `main.py`. -> should be accepted to arguments
- [ ] Add recovery-aware state usage in `main.py` so saved state is used after crashes, not as the default path. -> needs to handled by --recovery
- [ ] Add a manifest/versioning scheme for state compatibility, as called out in `main.py` and `recovery.py`.
- [ ] Wrap `STATE_DIR` handling in a cleaner abstraction instead of passing it around everywhere in `main.py`.
- [ ] Ensure an `optimized/` output directory exists at startup in `main.py`.
- [X] Consider splitting the top-level workflow in `main.py` into smaller phases/modules.
- [ ] Make the import-graph dict assignment safer in `main.py`.
- [ ] Consolidate the duplicated JSON persistence code in `state_storage.py`.
- [X] Optionally evaluate Redis for faster state storage if external dependencies become acceptable in `state_storage.py`.

## Config And Recovery
- [ ] Replace hardcoded config with generated runtime config as outlined in `config.py`.
- [ ] Generate a `config.json`, clean it up after a full run, and move secrets to a secure path per `config.py`.
- [ ] Implement the recovery loader in `recovery.py`.
- [ ] Add robust recovery fallbacks, manifest comparison, and failure behavior when requested state is missing in `recovery.py`.
- [ ] Wire `main.py --recovery ...` into the orchestration flow described by `recovery.py`.

## Project Loading And Graphing
- [ ] Wire root dir from config.py into `file_discover.py`
- [ ] Implement test-file discovery in `project_loader/file_discover.py`.
- [ ] Replace the string-based import/module matching in `project_loader/entrypoint_detect.py` with a more reliable resolver.
- [ ] Implement inter-function call analysis in `analyze/interfunction_calls.py`.
- [ ] Implement or extend per-file call tracking hinted by `analyze/file_calls.py`.

## AST Analysis
- [ ] Rename the dataclass helper in `analyze/ast_parser.py` as intended so it can't be called outside of the file
- [X] Revisit the AST parser design in `analyze/ast_parser.py`: it currently mixes graph generation with code clipping responsibilities. (Don't worry, I don't know what this goal means)
- [ ] Verify the prior recursion issues mentioned in the parser docstring are fully resolved by the iterative approach in `analyze/ast_parser.py`.
- [X] Improve hotspot scoring in `analyze/hotspot_detector.py`, which is currently just `max_nesting + max_conditionals`.
- [ ] Replace the hacky "best file" handling in `analyze/hotspot_detector.py` and raise a proper exception when no candidate exists.
- [X] Keep hotspot data derived from AST state rather than persisted separately, per `analyze/hotspot_detector.py`.

## Prompting And LLM Execution
- [ ] Generate prompt/task packaging dynamically from config/user input instead of hardcoded constants in `context_builder/prompt_packager.py`.
- [ ] Compute a real source hash in `context_builder/prompt_packager.py`.
- [ ] Build function contracts dynamically in `context_builder/prompt_packager.py`, including input and return types.
- [ ] Fix the LLM client behavior in `llm/llmagent.py` so responses are bounded and non-streaming if that is the intended mode.
- [ ] Add a job manager / multi-agent execution model in `llm/llmagent.py`, and expose agent-count configuration to users.

## Candidate Generation And Optimization Loop
- [ ] Implement candidate evaluation in `candidates/candidate_evaluation.py`.
- [ ] Support iterative evaluation rounds in `candidates/candidate_evaluation.py`.
- [ ] Add candidate-combination logic in `candidates/candidate_evaluation.py`, likely by feeding passing candidates back to the agent and reducing them.
- [ ] Implement final candidate insertion/rewrite in `candidates/final_candidate.py`.
- [ ] Emit rewritten Python files into `optimized/` from `candidates/final_candidate.py`.
