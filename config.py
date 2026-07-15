from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path

DEFAULT_TASK = {
    "task_id": "opt-0042",
    "action": "optimize_hotspot",
    "objective": "reduce complexity while preserving observable behavior",
}

DEFAULT_SCOPE_RESTRICTIONS = {
    "source": "...",
    "allowed_changes": [
        "function body",
    ],
    "forbidden_changes": [
        "function name",
        "parameters",
        "return contract",
        "other files",
    ],
}

DEFAULT_INSTRUCTIONS = {
    "return_format": "structured_mutation",
    "may_request_more_context": True,
    "do_not_return_entire_file": True,
    "explain_behavioral_equivalence": True,
}

DEFAULT_SECRET_REFERENCES = {
    "ollama_host": "OLLAMA_HOST",
    "openai_api_key": "OPENAI_API_KEY",
}


@dataclass(slots=True)
class RuntimeConfig:
    workspace_root: Path
    target_dir: Path
    state_dir: Path
    optimized_dir: Path
    local_dir: Path
    config_path: Path
    recovery_token: str | None = None
    prompt_task: dict = field(default_factory=lambda: dict(DEFAULT_TASK))
    scope_restrictions: dict = field(default_factory=lambda: dict(DEFAULT_SCOPE_RESTRICTIONS))
    instructions: dict = field(default_factory=lambda: dict(DEFAULT_INSTRUCTIONS))
    test_targets: list[str] = field(default_factory=list)
    benchmark_targets: list[str] = field(default_factory=list)
    agent_count: int = 1
    secret_references: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SECRET_REFERENCES))
    resolved_secrets: dict[str, str | None] = field(default_factory=dict, repr=False)

    def to_public_dict(self) -> dict:
        return {
            "workspace_root": str(self.workspace_root),
            "target_dir": str(self.target_dir),
            "state_dir": str(self.state_dir),
            "optimized_dir": str(self.optimized_dir),
            "local_dir": str(self.local_dir),
            "config_path": str(self.config_path),
            "recovery_token": self.recovery_token,
            "prompt_task": self.prompt_task,
            "scope_restrictions": self.scope_restrictions,
            "instructions": self.instructions,
            "test_targets": self.test_targets,
            "benchmark_targets": self.benchmark_targets,
            "agent_count": self.agent_count,
            "secret_references": self.secret_references,
        }

    def write_json(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(self.to_public_dict(), indent=2),
            encoding="UTF-8",
        )

    def cleanup_json(self) -> None:
        if self.config_path.exists():
            self.config_path.unlink()


ACTIVE_CONFIG: RuntimeConfig | None = None
TARGET_DIR: Path | None = None
STATE_DIR: Path | None = None
OPTIMIZED_DIR: Path | None = None
LOCAL_DIR: Path | None = None
CONFIG_PATH: Path | None = None
RECOVERY_TOKEN: str | None = None
TASK_CONFIG: dict = dict(DEFAULT_TASK)
SCOPE_RESTRICTIONS: dict = dict(DEFAULT_SCOPE_RESTRICTIONS)
INSTRUCTIONS: dict = dict(DEFAULT_INSTRUCTIONS)
TEST_TARGETS: list[str] = []
BENCHMARK_TARGETS: list[str] = []
AGENT_COUNT: int = 1
SECRET_ENV_VARS: dict[str, str] = dict(DEFAULT_SECRET_REFERENCES)


def _normalize_target_path(target: str | Path, workspace_root: Path) -> Path:
    target_path = Path(target).expanduser()
    if not target_path.is_absolute():
        target_path = workspace_root / target_path
    return target_path.resolve()


def _resolve_secrets(secret_references: dict[str, str]) -> dict[str, str | None]:
    return {
        name: os.getenv(env_name)
        for name, env_name in secret_references.items()
    }


def build_runtime_config(
    target: str | Path,
    recovery_token: str | None = None,
    workspace_root: Path | None = None,
) -> RuntimeConfig:
    resolved_workspace = workspace_root.resolve() if workspace_root else Path.cwd().resolve()
    target_dir = _normalize_target_path(target, resolved_workspace)

    if not target_dir.exists():
        raise FileNotFoundError(f"Target directory does not exist: {target_dir}")
    if not target_dir.is_dir():
        raise NotADirectoryError(f"Target path is not a directory: {target_dir}")

    runtime_config = RuntimeConfig(
        workspace_root=resolved_workspace,
        target_dir=target_dir,
        state_dir=resolved_workspace / "state",
        optimized_dir=resolved_workspace / "optimized",
        local_dir=resolved_workspace / "_local",
        config_path=resolved_workspace / "config.json",
        recovery_token=recovery_token,
    )
    runtime_config.resolved_secrets = _resolve_secrets(runtime_config.secret_references)
    return runtime_config


def init_config(runtime_config: RuntimeConfig) -> RuntimeConfig:
    global ACTIVE_CONFIG
    global TARGET_DIR
    global STATE_DIR
    global OPTIMIZED_DIR
    global LOCAL_DIR
    global CONFIG_PATH
    global RECOVERY_TOKEN
    global TASK_CONFIG
    global SCOPE_RESTRICTIONS
    global INSTRUCTIONS
    global TEST_TARGETS
    global BENCHMARK_TARGETS
    global AGENT_COUNT
    global SECRET_ENV_VARS

    ACTIVE_CONFIG = runtime_config
    TARGET_DIR = runtime_config.target_dir
    STATE_DIR = runtime_config.state_dir
    OPTIMIZED_DIR = runtime_config.optimized_dir
    LOCAL_DIR = runtime_config.local_dir
    CONFIG_PATH = runtime_config.config_path
    RECOVERY_TOKEN = runtime_config.recovery_token
    TASK_CONFIG = dict(runtime_config.prompt_task)
    SCOPE_RESTRICTIONS = dict(runtime_config.scope_restrictions)
    INSTRUCTIONS = dict(runtime_config.instructions)
    TEST_TARGETS = list(runtime_config.test_targets)
    BENCHMARK_TARGETS = list(runtime_config.benchmark_targets)
    AGENT_COUNT = runtime_config.agent_count
    SECRET_ENV_VARS = dict(runtime_config.secret_references)
    return runtime_config


def get_config() -> RuntimeConfig:
    if ACTIVE_CONFIG is None:
        raise RuntimeError("Runtime config is not initialized.")
    return ACTIVE_CONFIG


__all__ = [
    "AGENT_COUNT",
    "BENCHMARK_TARGETS",
    "CONFIG_PATH",
    "DEFAULT_INSTRUCTIONS",
    "DEFAULT_SCOPE_RESTRICTIONS",
    "DEFAULT_SECRET_REFERENCES",
    "DEFAULT_TASK",
    "INSTRUCTIONS",
    "LOCAL_DIR",
    "OPTIMIZED_DIR",
    "RECOVERY_TOKEN",
    "RuntimeConfig",
    "SCOPE_RESTRICTIONS",
    "SECRET_ENV_VARS",
    "STATE_DIR",
    "TARGET_DIR",
    "TASK_CONFIG",
    "TEST_TARGETS",
    "build_runtime_config",
    "get_config",
    "init_config",
]
