# A LLM in the Loop Code Optimizer

This is a code optimization program that reduces code complexity by chunks. For this optimizer, minimizing complexity means improving readability. This project can be wired into any local or cloud LLM as long as the CLI has been configured for it. For now, this project is built to work with Codex only.

This project uses only the standard library at runtime and requires Python 3.12+. Install it with `pip install .`, then use the installed `self-optimize` command. The optimizer saves progress as it goes, so a run can be resumed with `--recovery` after an interruption.

Do not run `main.py` directly: use the console command so the supported Python environment and CLI configuration are applied.

## A Description of the Project

The goal of this project was to find a way to reduce readability complexity in python programs. The main target is nested if statements and for loops. Readability complexity is somewhat subjective, and there's no way to know the global minimum complexity without reading the entire program. So to try to get as close to a global minimum, I decided to optimize the code in blocks. 

### A Definition of Code Blocks for This Project
Blocks of code for this project are "arbitrarily drawn". They are arbitrary because I had to balance the size of the block so it would be small enough to test for logic breaking changes, but large enough that changes would be meaningful. The first version of this was to use an AST Parser and go through blocks manually. This created a problem because AST blocks weren't always good representations of program use. Functions, for instance, could have multiple inputs and outputs with upstream dependencies. The next idea was to move away limiting blocks, and focus on call paths. By using a backwards static or dynamic call path as context, I can be sure that by comparing the final value of a variable (or another point of interest), with the value before, I am not breaking any logic. (This is not a comphrensive test, but it's meant to illustrate that this kind of block is still small enough for tests to be meaningful). 

## Limitations
The main limitation is a defined test suite. Target projects must have comphrensive test suites. My next goal will be to minimize the dependency. 

## Working example

This captured command uses the local smoke project from development; replace `_local/smoke_proj` with your project root. Repeat `--test-command` or `--benchmark-command` to run more than one command. Test commands gate candidate acceptance; benchmark commands are timed for each candidate and included in the final report.

```console
$ pip install .
$ self-optimize --target _local/smoke_proj \
    --test-command 'python3 -m unittest discover -s tests' \
    --benchmark-command 'python3 -m unittest discover -s tests'
```

Each successful run writes its copied project, `optimization_diff.patch`, and `optimization_report.json` under `optimized/<target>-<timestamp>/`. The report records every command, its exit status, standard output/error, and `duration_seconds`; it labels a change as measured only when the configured evidence supports it.

For the smoke project on 2026-08-02, the configured benchmark command completed successfully, ran all 6 tests, and the report timing wrapper measured **0.048 seconds**. This is an environment-specific measurement, not a portable performance claim.

One prior smoke run produced this excerpt from `optimization_diff.patch`:

```diff
 def schedule_tasks(tasks: list[TaskSpec]) -> ExecutionPlan:
-    ordered_specs = topological_order(tasks)
-    scheduled: list[ScheduledTask] = []
-    warnings: list[str] = []
-    adjusted_durations: dict[str, int] = {}
-
-    for task in ordered_specs:
-        effect = evaluate_rules(task)
-        adjusted_duration = max(1, task.duration + effect.duration_delta)
+    entries = [
+        (
+            ScheduledTask(
+                name=name,
+                adjusted_duration=adjusted_duration,
+                score=score,
+                dependencies=task.dependencies,
+                warnings=task_warnings,
+            ),
+            task_warnings,
+            name,
+            adjusted_duration,
+        )
+        for task in topological_order(tasks)
+        for effect in [evaluate_rules(task)]
```

That run's report recorded two changed files but no benchmark evidence, so its confidence was `safe but unproven`; the example shows the artifact format, not an endorsed optimization.
