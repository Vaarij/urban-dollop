from __future__ import annotations

import ast
from pathlib import Path

from project_loader.entrypoint_detect import build_module_index, resolve_import_target
from project_loader.import_graph_builder import build_import_graph


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else None
    return None


def _definitions(tree: ast.Module) -> tuple[dict[str, tuple[int, int]], dict[str, set[str]], dict[str, str]]:
    spans: dict[str, tuple[int, int]] = {}
    calls: dict[str, set[str]] = {}
    aliases: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                aliases[alias.asname or alias.name.split(".")[-1]] = alias.name
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            spans[node.name] = (node.lineno - 1, node.end_lineno or node.lineno)
            calls[node.name] = {_call_name(item.func) for item in ast.walk(node) if isinstance(item, ast.Call) and _call_name(item.func)}
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    name = f"{node.name}.{item.name}"
                    spans[name] = (item.lineno - 1, item.end_lineno or item.lineno)
                    calls[name] = {_call_name(call.func) for call in ast.walk(item) if isinstance(call, ast.Call) and _call_name(call.func)}
    return spans, calls, aliases


def analyze_interfunction_calls(file_path: Path) -> dict[str, list[str]]:
    tree = ast.parse(file_path.read_text(encoding="UTF-8"), filename=str(file_path))
    spans, calls, _aliases = _definitions(tree)
    resolved: dict[str, list[str]] = {}
    for name, raw_calls in calls.items():
        class_name = name.split(".", 1)[0] if "." in name else None
        local: set[str] = set()
        for call in raw_calls:
            if call in spans:
                local.add(call)
            elif class_name and call.startswith("self.") and f"{class_name}.{call[5:]}" in spans:
                local.add(f"{class_name}.{call[5:]}")
        resolved[name] = sorted(local)
    return resolved


def build_function_graph(project_dir: Path, file_paths: list[Path]) -> dict[str, set[str]]:
    """Return caller-to-callee graph keys as ``/path/file.py:symbol``."""
    module_index = build_module_index(project_dir, file_paths)
    graph: dict[str, set[str]] = {}
    for file_path in file_paths:
        tree = ast.parse(file_path.read_text(encoding="UTF-8"), filename=str(file_path))
        spans, calls, aliases = _definitions(tree)
        imports = build_import_graph(file_path)
        imported_targets = {
            str(record.get("imported_name") or record.get("name", "")).split(".")[-1]: resolve_import_target(project_dir, file_path, record, module_index)
            for record in imports
        }
        for symbol, raw_calls in calls.items():
            key = f"{file_path.resolve()}:{symbol}"
            graph.setdefault(key, set())
            for call in raw_calls:
                if call in spans:
                    graph[key].add(f"{file_path.resolve()}:{call}")
                elif "." in symbol and call.startswith("self."):
                    candidate = f"{symbol.split('.', 1)[0]}.{call[5:]}"
                    if candidate in spans:
                        graph[key].add(f"{file_path.resolve()}:{candidate}")
                else:
                    base = call.split(".", 1)[0]
                    target = imported_targets.get(base)
                    if target is not None:
                        target_tree = ast.parse(target.read_text(encoding="UTF-8"), filename=str(target))
                        target_spans, _target_calls, _target_aliases = _definitions(target_tree)
                        target_symbol = call.split(".")[-1]
                        if target_symbol in target_spans:
                            graph[key].add(f"{target.resolve()}:{target_symbol}")
    return graph


def collect_called_names(file_path: Path) -> list[str]:
    return sorted({name for calls in analyze_interfunction_calls(file_path).values() for name in calls})
