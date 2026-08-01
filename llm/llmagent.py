from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
import subprocess
import tempfile
import time


DEFAULT_CODEX_COMMAND = ("codex", "exec")
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CandidatePayload:
    candidate_id: str
    file_source: str
    reason: str


@dataclass(slots=True)
class CandidateJobSpec:
    candidate_index: int
    sample_count: int
    prompt: str


@dataclass(slots=True)
class CandidateJobResult:
    candidate_index: int
    status: str
    payload: CandidatePayload | None
    tokens_used: int | None
    duration_seconds: float
    error: str | None = None


def _build_output_schema(schema_path: Path) -> None:
    schema = {
        "type": "object",
        "properties": {
            "candidate_id": {"type": "string"},
            "file_source": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["candidate_id", "file_source", "reason"],
        "additionalProperties": False,
    }
    schema_path.write_text(json.dumps(schema), encoding="UTF-8")


def _extract_json_payload(raw_output: str) -> CandidatePayload:
    text = raw_output.strip()
    if text.startswith("```"):
        lines = [line.strip() for line in text.splitlines()]
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    payload = json.loads(text)
    return CandidatePayload(
        candidate_id=str(payload["candidate_id"]),
        file_source=str(payload["file_source"]),
        reason=str(payload["reason"]),
    )


def _find_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        digits = value.replace(",", "").strip()
        if digits.isdigit():
            return int(digits)
    return None


def _extract_tokens_from_json_event(event: object) -> int | None:
    if not isinstance(event, dict):
        return None

    direct_keys = (
        "total_tokens",
        "tokens_used",
        "token_count",
    )
    for key in direct_keys:
        token_value = _find_int(event.get(key))
        if token_value is not None:
            return token_value

    nested_keys = ("usage", "token_usage", "metrics")
    for key in nested_keys:
        nested = event.get(key)
        if not isinstance(nested, dict):
            continue
        for nested_key in ("total_tokens", "tokens_used", "output_tokens", "input_tokens"):
            token_value = _find_int(nested.get(nested_key))
            if token_value is not None:
                return token_value
    return None


def _extract_tokens_from_json_lines(raw_output: str) -> int | None:
    token_counts: list[int] = []
    for line in raw_output.splitlines():
        text = line.strip()
        if not text or not text.startswith("{"):
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        token_value = _extract_tokens_from_json_event(payload)
        if token_value is not None:
            token_counts.append(token_value)
    if token_counts:
        return max(token_counts)
    return None


def _extract_tokens_from_text(raw_output: str) -> int | None:
    patterns = (
        r"tokens used\s*[:\n]\s*([\d,]+)",
        r"total tokens\s*[:\n]\s*([\d,]+)",
        r"total_tokens\s*[:=]\s*([\d,]+)",
        r"tokens_used\s*[:=]\s*([\d,]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, raw_output, flags=re.IGNORECASE)
        if match is None:
            continue
        return int(match.group(1).replace(",", ""))
    return None


def _extract_tokens_used(raw_output: str) -> int | None:
    if token_value := _extract_tokens_from_json_lines(raw_output):
        return token_value
    return _extract_tokens_from_text(raw_output)


def _build_candidate_prompt(
    context: dict,
    file_path: Path,
    file_source: str,
    candidate_index: int,
    sample_count: int,
) -> str:
    context_json = json.dumps(context, indent=2, sort_keys=True)
    return f"""Generate one Python complexity-reduction candidate.

Return only JSON matching the requested schema.

Candidate index: {candidate_index + 1} of {sample_count}
Target file: {file_path}

Rules:
- Preserve observable behavior.
- Return a complete rewritten file, not a diff.
- Keep imports valid.
- Do not change other files.
- Lower AST complexity is the primary goal.
- Prefer high-signal simplifications over cosmetic rewrites.
- Avoid trivial local refactors like aliasing lookups, formatting-only changes, or condensing branches unless they clearly simplify control flow.
- Make this candidate meaningfully different from the others.

Optimization context:
{context_json}

Current file source:
```python
{file_source}
```
"""


def _build_combination_prompt(
    context: dict,
    file_path: Path,
    baseline_source: str,
    passing_candidates: list[dict[str, object]],
    candidate_index: int,
    sample_count: int,
) -> str:
    context_json = json.dumps(context, indent=2, sort_keys=True)
    candidate_json = json.dumps(passing_candidates, indent=2, sort_keys=True)
    return f"""Combine passing Python optimization candidates into one lower-complexity result.

Return only JSON matching the requested schema.

Combination index: {candidate_index + 1} of {sample_count}
Target file: {file_path}

Rules:
- Preserve observable behavior.
- Return a complete rewritten file, not a diff.
- Only use content compatible with the current file contract and imports.
- Splice safe pieces from the passing candidates into a lower-complexity result.
- Lower AST complexity is the primary goal.
- Behavioral preservation is mandatory.
- Avoid no-op combinations or cosmetic merges without a real simplification.

Optimization context:
{context_json}

Current retained baseline:
```python
{baseline_source}
```

Passing candidates with scores:
{candidate_json}
"""


def _build_candidate_specs(
    context: dict,
    file_path: Path,
    sample_count: int,
) -> list[CandidateJobSpec]:
    file_source = file_path.read_text(encoding="UTF-8")
    return [
        CandidateJobSpec(
            candidate_index=candidate_index,
            sample_count=sample_count,
            prompt=_build_candidate_prompt(
                context,
                file_path,
                file_source,
                candidate_index,
                sample_count,
            ),
        )
        for candidate_index in range(sample_count)
    ]


def _build_combination_specs(
    context: dict,
    file_path: Path,
    baseline_source: str,
    passing_candidates: list[dict[str, object]],
    sample_count: int,
) -> list[CandidateJobSpec]:
    return [
        CandidateJobSpec(
            candidate_index=candidate_index,
            sample_count=sample_count,
            prompt=_build_combination_prompt(
                context,
                file_path,
                baseline_source,
                passing_candidates,
                candidate_index,
                sample_count,
            ),
        )
        for candidate_index in range(sample_count)
    ]


def _log_prompt_projection(file_path: Path, specs: list[CandidateJobSpec]) -> None:
    prompt_chars = sum(len(spec.prompt) for spec in specs)
    prompt_bytes = sum(len(spec.prompt.encode("UTF-8")) for spec in specs)
    logger.info(
        "Projected candidate prompt volume for %s: %s chars across %s bytes for %s jobs",
        file_path,
        prompt_chars,
        prompt_bytes,
        len(specs),
    )


def _run_candidate_job(
    spec: CandidateJobSpec,
    file_path: Path,
    working_dir: Path,
    model: str | None = None,
    codex_command: tuple[str, ...] = DEFAULT_CODEX_COMMAND,
) -> CandidateJobResult:
    started_at = time.perf_counter()
    logger.info("Queued candidate job %s for %s", spec.candidate_index, file_path)

    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        schema_path = temp_dir / "candidate_schema.json"
        output_path = temp_dir / "candidate_output.json"
        _build_output_schema(schema_path)

        command = [
            *codex_command,
            "--json",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--ephemeral",
            "--color",
            "never",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
            "-C",
            str(working_dir),
        ]
        if model is not None:
            command.extend(["--model", model])
        command.append("-")

        completed = subprocess.run(
            command,
            input=spec.prompt,
            cwd=working_dir,
            capture_output=True,
            text=True,
            check=False,
        )

        duration_seconds = time.perf_counter() - started_at
        if completed.returncode != 0:
            error_text = completed.stderr.strip() or completed.stdout.strip() or "unknown Codex error"
            logger.error(
                "Candidate job %s failed for %s: %s",
                spec.candidate_index,
                file_path,
                error_text,
            )
            return CandidateJobResult(
                candidate_index=spec.candidate_index,
                status="failed",
                payload=None,
                tokens_used=_extract_tokens_used(completed.stdout),
                duration_seconds=duration_seconds,
                error=error_text,
            )
        if not output_path.exists():
            error_text = f"Codex did not write output for {file_path}"
            logger.error("Candidate job %s failed for %s: %s", spec.candidate_index, file_path, error_text)
            return CandidateJobResult(
                candidate_index=spec.candidate_index,
                status="failed",
                payload=None,
                tokens_used=_extract_tokens_used(completed.stdout),
                duration_seconds=duration_seconds,
                error=error_text,
            )

        payload = _extract_json_payload(output_path.read_text(encoding="UTF-8"))
        return CandidateJobResult(
            candidate_index=spec.candidate_index,
            status="completed",
            payload=payload,
            tokens_used=_extract_tokens_used(completed.stdout),
            duration_seconds=duration_seconds,
            error=None,
        )


def _log_job_totals(file_path: Path, results: list[CandidateJobResult]) -> None:
    token_total = sum(result.tokens_used for result in results if result.tokens_used is not None)
    unknown_count = sum(1 for result in results if result.tokens_used is None)
    logger.info(
        "Generated %s candidate job results for %s using %s total tokens (%s unknown)",
        len(results),
        file_path,
        token_total,
        unknown_count,
    )


def _execute_candidate_specs(
    file_path: Path,
    specs: list[CandidateJobSpec],
    working_dir: Path,
    agent_count: int,
    model: str | None = None,
    codex_command: tuple[str, ...] = DEFAULT_CODEX_COMMAND,
) -> list[str]:
    worker_count = max(1, min(agent_count, len(specs)))
    ordered_candidates: dict[int, str] = {}
    results: list[CandidateJobResult] = []
    failed_indices: list[int] = []

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_map = {
            executor.submit(
                _run_candidate_job,
                spec,
                file_path,
                working_dir,
                model,
                codex_command,
            ): spec.candidate_index
            for spec in specs
        }
        for future in as_completed(future_map):
            result = future.result()
            results.append(result)
            if result.status != "completed" or result.payload is None:
                failed_indices.append(result.candidate_index)
                continue
            ordered_candidates[result.candidate_index] = result.payload.file_source
            logger.info(
                "Candidate %s for %s used %s tokens in %.3fs",
                result.payload.candidate_id,
                file_path,
                result.tokens_used if result.tokens_used is not None else "unknown",
                result.duration_seconds,
            )

    _log_job_totals(file_path, results)

    if failed_indices:
        logger.warning("Candidate generation failed for %s at indices %s", file_path, sorted(failed_indices))

    if not ordered_candidates:
        logger.warning("Optimizer did not find a better candidate for %s during generation", file_path)
        failure_messages = [
            f"{result.candidate_index}: {result.error or 'unknown error'}"
            for result in sorted(results, key=lambda item: item.candidate_index)
        ]
        raise RuntimeError(
            f"Codex candidate generation failed for {file_path}: " + "; ".join(failure_messages)
        )

    return [ordered_candidates[index] for index in sorted(ordered_candidates)]


def generate_candidates(
    context: dict,
    file_path: Path,
    sample_count: int,
    working_dir: Path,
    agent_count: int = 1,
    model: str | None = None,
    codex_command: tuple[str, ...] = DEFAULT_CODEX_COMMAND,
) -> list[str]:
    specs = _build_candidate_specs(context, file_path, sample_count)
    _log_prompt_projection(file_path, specs)
    return _execute_candidate_specs(
        file_path,
        specs,
        working_dir,
        agent_count,
        model,
        codex_command,
    )


def generate_combined_candidates(
    context: dict,
    file_path: Path,
    baseline_source: str,
    passing_candidates: list[dict[str, object]],
    sample_count: int,
    working_dir: Path,
    agent_count: int = 1,
    model: str | None = None,
    codex_command: tuple[str, ...] = DEFAULT_CODEX_COMMAND,
) -> list[str]:
    specs = _build_combination_specs(
        context,
        file_path,
        baseline_source,
        passing_candidates,
        sample_count,
    )
    _log_prompt_projection(file_path, specs)
    return _execute_candidate_specs(
        file_path,
        specs,
        working_dir,
        agent_count,
        model,
        codex_command,
    )
