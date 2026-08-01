from __future__ import annotations

import json
from pathlib import Path

from state_storage import ORCHESTRATOR_ROUND_STAGE, STAGE_FILES, STATE_MANIFEST_VERSION, StateStore


class RecoveryError(RuntimeError):
    """Raised when saved state cannot be used safely."""


RECOVERY_STAGE_ORDER = tuple(STAGE_FILES.keys())


def _read_manifest(manifest_path: Path) -> dict:
    if not manifest_path.exists():
        raise RecoveryError(f"Recovery manifest is missing: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="UTF-8"))


def _validate_manifest(manifest: dict, state_store: StateStore) -> None:
    manifest_version = manifest.get("manifest_version")
    if manifest_version != STATE_MANIFEST_VERSION:
        raise RecoveryError(
            f"State manifest version {manifest_version!r} does not match "
            f"expected {STATE_MANIFEST_VERSION!r}."
        )

    manifest_target = manifest.get("target_dir")
    if manifest_target != str(state_store.target_dir):
        raise RecoveryError(
            f"State target {manifest_target!r} does not match current target "
            f"{str(state_store.target_dir)!r}."
        )


def _required_stages(last_completed_stage: str) -> tuple[str, ...]:
    if last_completed_stage not in RECOVERY_STAGE_ORDER:
        valid = ", ".join(RECOVERY_STAGE_ORDER)
        raise RecoveryError(
            f"Unknown recovery stage {last_completed_stage!r}. "
            f"Expected one of: {valid}."
        )

    stage_index = RECOVERY_STAGE_ORDER.index(last_completed_stage)
    return RECOVERY_STAGE_ORDER[: stage_index + 1]


def validate_recovery_state(state_store: StateStore, last_completed_stage: str) -> None:
    manifest = _read_manifest(state_store.manifest_path)
    _validate_manifest(manifest, state_store)

    stages = manifest.get("stages", {})
    for stage_name in _required_stages(last_completed_stage):
        stage_info = stages.get(stage_name)
        if stage_info is None:
            raise RecoveryError(
                f"Manifest is missing required recovery stage {stage_name!r}."
            )

        stage_path = state_store.stage_path(stage_name)
        if not stage_path.exists():
            raise RecoveryError(
                f"Recovery requested {stage_name!r}, but state file is missing: {stage_path}"
            )


def load_recovery_bundle(state_store: StateStore, last_completed_stage: str) -> dict[str, object]:
    validate_recovery_state(state_store, last_completed_stage)

    recovered_data: dict[str, object] = {}
    for stage_name in _required_stages(last_completed_stage):
        recovered_data[stage_name] = state_store.load_json(stage_name)
    return recovered_data


__all__ = [
    "RECOVERY_STAGE_ORDER",
    "RecoveryError",
    "load_recovery_bundle",
    "validate_recovery_state",
]
