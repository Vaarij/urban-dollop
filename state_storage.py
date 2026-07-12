from pathlib import Path
import json
import logging

logger = logging.getLogger(__name__)

# NOTE: Crazy amounts of duplicated code

def save_file_list(state_dir: Path, file_list: list) -> None:
    file_discovery_path = state_dir / "explore" / "files_list.json"
    file_discovery_path.parent.mkdir(parents=True, exist_ok=True)
    file_discovery_path.write_text(json.dumps(file_list, indent=2), encoding="UTF-8")

def save_import_graph(state_dir: Path, import_graph: list) -> None:
    import_graph_path = state_dir / "explore" / "import_graph.json"
    import_graph_path.parent.mkdir(parents=True, exist_ok=True)
    import_graph_path.write_text(json.dumps(import_graph, indent=2), encoding="UTF-8")

def save_entry_points(state_dir: Path, roots_list: list) -> None:
    entry_point_path = state_dir / "explore" / "entry_points.json"
    entry_point_path.parent.mkdir(parents=True, exist_ok=True)
    entry_point_path.write_text(json.dumps(roots_list, indent=2), encoding="UTF-8")

def save_ast_graphs(state_dir: Path, ast_dict: dict) -> None:
    ast_graph_path = state_dir / "analyze" / "ast_graphs.json"
    ast_graph_path.parent.mkdir(parents=True, exist_ok=True)
    ast_graph_path.write_text(json.dumps(ast_dict, indent=2), encoding="UTF-8")