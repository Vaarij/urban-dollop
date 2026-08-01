from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STATE_MANIFEST_VERSION = "1"

FILE_LIST_STAGE = "files"
IMPORT_GRAPH_STAGE = "imports"
ENTRY_POINTS_STAGE = "entry_points"
AST_STAGE = "asts"
ORCHESTRATOR_ROUND_STAGE = "orchestrator_round"

STAGE_FILES = {
    FILE_LIST_STAGE: Path("explore/files_list.json"),
    IMPORT_GRAPH_STAGE: Path("explore/import_graph.json"),
    ENTRY_POINTS_STAGE: Path("explore/entry_points.json"),
    AST_STAGE: Path("analyze/ast_graphs.json"),
    ORCHESTRATOR_ROUND_STAGE: Path("orchestrator/round.json"),
}


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class StateStore:
    root_dir: Path
    target_dir: Path
    manifest_version: str = STATE_MANIFEST_VERSION

    def ensure_dirs(self) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)

    @property
    def manifest_path(self) -> Path:
        return self.root_dir / "manifest.json"

    def stage_path(self, stage_name: str) -> Path:
        try:
            relative_path = STAGE_FILES[stage_name]
        except KeyError as exc:
            raise KeyError(f"Unknown state stage: {stage_name}") from exc
        return self.root_dir / relative_path

    def save_json(self, stage_name: str, payload: Any) -> None:
        stage_path = self.stage_path(stage_name)
        stage_path.parent.mkdir(parents=True, exist_ok=True)
        stage_path.write_text(json.dumps(payload, indent=2), encoding="UTF-8")
        self.record_stage(stage_name)

    def load_json(self, stage_name: str) -> Any:
        stage_path = self.stage_path(stage_name)
        return json.loads(stage_path.read_text(encoding="UTF-8"))

    def write_manifest(self) -> None:
        self.ensure_dirs()
        manifest = self._read_manifest_or_default()
        manifest["manifest_version"] = self.manifest_version
        manifest["target_dir"] = str(self.target_dir)
        manifest["updated_at"] = _timestamp()
        if "created_at" not in manifest:
            manifest["created_at"] = manifest["updated_at"]
        if "stages" not in manifest:
            manifest["stages"] = {}
        self.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="UTF-8")

    def record_stage(self, stage_name: str) -> None:
        manifest = self._read_manifest_or_default()
        stage_path = self.stage_path(stage_name)
        stages = manifest.setdefault("stages", {})
        stages[stage_name] = {
            "path": str(stage_path.relative_to(self.root_dir)),
            "updated_at": _timestamp(),
        }
        manifest["manifest_version"] = self.manifest_version
        manifest["target_dir"] = str(self.target_dir)
        manifest["updated_at"] = _timestamp()
        if "created_at" not in manifest:
            manifest["created_at"] = manifest["updated_at"]
        self.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="UTF-8")

    def _read_manifest_or_default(self) -> dict[str, Any]:
        if not self.manifest_path.exists():
            return {
                "manifest_version": self.manifest_version,
                "target_dir": str(self.target_dir),
                "created_at": _timestamp(),
                "updated_at": _timestamp(),
                "stages": {},
            }
        return json.loads(self.manifest_path.read_text(encoding="UTF-8"))


def build_state_store(state_dir: Path, target_dir: Path) -> StateStore:
    return StateStore(root_dir=state_dir, target_dir=target_dir)


def save_file_list(state_store: StateStore, file_list: list[str]) -> None:
    state_store.save_json(FILE_LIST_STAGE, file_list)


def load_file_list(state_store: StateStore) -> list[str]:
    return state_store.load_json(FILE_LIST_STAGE)


def save_import_graph(state_store: StateStore, import_graph: dict[str, list[dict[str, Any]]]) -> None:
    state_store.save_json(IMPORT_GRAPH_STAGE, import_graph)


def load_import_graph(state_store: StateStore) -> dict[str, list[dict[str, Any]]]:
    return state_store.load_json(IMPORT_GRAPH_STAGE)


def save_entry_points(state_store: StateStore, roots_list: list[str]) -> None:
    state_store.save_json(ENTRY_POINTS_STAGE, roots_list)


def load_entry_points(state_store: StateStore) -> list[str]:
    return state_store.load_json(ENTRY_POINTS_STAGE)


def save_ast_graphs(state_store: StateStore, ast_dict: dict[str, Any]) -> None:
    state_store.save_json(AST_STAGE, ast_dict)


def load_ast_graphs(state_store: StateStore) -> dict[str, Any]:
    return state_store.load_json(AST_STAGE)


def save_orchestrator_round(state_store: StateStore, round_state: dict[str, Any]) -> None:
    state_store.save_json(ORCHESTRATOR_ROUND_STAGE, round_state)


def load_orchestrator_round(state_store: StateStore) -> dict[str, Any]:
    return state_store.load_json(ORCHESTRATOR_ROUND_STAGE)


__all__ = [
    "AST_STAGE",
    "ENTRY_POINTS_STAGE",
    "FILE_LIST_STAGE",
    "IMPORT_GRAPH_STAGE",
    "ORCHESTRATOR_ROUND_STAGE",
    "STATE_MANIFEST_VERSION",
    "STAGE_FILES",
    "StateStore",
    "build_state_store",
    "load_ast_graphs",
    "load_entry_points",
    "load_file_list",
    "load_import_graph",
    "save_ast_graphs",
    "save_entry_points",
    "save_file_list",
    "save_import_graph",
    "load_orchestrator_round",
    "save_orchestrator_round",
]
