from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
from pathlib import Path
from typing import Any

from orchestrator.region import RegionProposal

import config


def _source_hash(file_path: Path) -> str:
    return hashlib.sha256(file_path.read_bytes()).hexdigest()


def _annotation_text(annotation: ast.expr | None) -> str | None:
    if annotation is None:
        return None
    return ast.unparse(annotation)


def _decorator_names(function_node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    decorators: set[str] = set()
    for decorator in function_node.decorator_list:
        if isinstance(decorator, ast.Name):
            decorators.add(decorator.id)
        elif isinstance(decorator, ast.Attribute):
            decorators.add(decorator.attr)
    return decorators


def _parameter_contracts(function_node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[dict[str, Any]]:
    params: list[dict[str, Any]] = []
    positional = [*function_node.args.posonlyargs, *function_node.args.args]
    positional_defaults = [None] * (len(positional) - len(function_node.args.defaults)) + list(function_node.args.defaults)

    for argument, default in zip(positional, positional_defaults, strict=True):
        params.append(
            {
                "name": argument.arg,
                "kind": "positional_only" if argument in function_node.args.posonlyargs else "positional_or_keyword",
                "annotation": _annotation_text(argument.annotation),
                "has_default": default is not None,
            }
        )

    if function_node.args.vararg is not None:
        params.append(
            {
                "name": function_node.args.vararg.arg,
                "kind": "var_positional",
                "annotation": _annotation_text(function_node.args.vararg.annotation),
                "has_default": False,
            }
        )

    for argument, default in zip(function_node.args.kwonlyargs, function_node.args.kw_defaults, strict=True):
        params.append(
            {
                "name": argument.arg,
                "kind": "keyword_only",
                "annotation": _annotation_text(argument.annotation),
                "has_default": default is not None,
            }
        )

    if function_node.args.kwarg is not None:
        params.append(
            {
                "name": function_node.args.kwarg.arg,
                "kind": "var_keyword",
                "annotation": _annotation_text(function_node.args.kwarg.annotation),
                "has_default": False,
            }
        )

    return params


def _function_contract(
    function_node: ast.FunctionDef | ast.AsyncFunctionDef,
    class_name: str | None = None,
) -> dict[str, Any]:
    decorators = _decorator_names(function_node)
    qualified_name = function_node.name if class_name is None else f"{class_name}.{function_node.name}"
    return {
        "symbol": qualified_name,
        "symbol_type": "method" if class_name is not None else "function",
        "class_name": class_name,
        "parameters": _parameter_contracts(function_node),
        "return_annotation": _annotation_text(function_node.returns),
        "is_async": isinstance(function_node, ast.AsyncFunctionDef),
        "is_classmethod": "classmethod" in decorators,
        "is_staticmethod": "staticmethod" in decorators,
    }


def _class_contract(class_node: ast.ClassDef) -> dict[str, Any]:
    return {
        "symbol": class_node.name,
        "symbol_type": "class",
        "class_name": class_node.name,
        "parameters": [],
        "return_annotation": None,
        "is_async": False,
        "is_classmethod": False,
        "is_staticmethod": False,
        "methods": [
            _function_contract(child, class_name=class_node.name)
            for child in class_node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        ],
    }


def _all_contracts(tree: ast.Module) -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            contracts.append(_function_contract(node))
        elif isinstance(node, ast.ClassDef):
            contracts.append(_class_contract(node))
    return contracts


def _targeted_contracts(tree: ast.Module, symbol_id: str, symbol_type: str) -> list[dict[str, Any]]:
    if symbol_type == "file":
        return _all_contracts(tree)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol_id:
            return [_function_contract(node)]
        if isinstance(node, ast.ClassDef) and node.name == symbol_id:
            return [_class_contract(node)]
    return []


def build_context_file(
    region_or_path: RegionProposal | Path,
    symbol_id: str | None = None,
    symbol_type: str | None = None,
    ast_graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(region_or_path, RegionProposal):
        target_path = region_or_path.criterion.file_path
        symbol_id = region_or_path.criterion.symbol
        symbol_type = "function"
        ast_graph = {"editable_spans": list(region_or_path.editable_spans), "dependencies": list(region_or_path.dependencies), "evidence": region_or_path.evidence}
    else:
        target_path = region_or_path
    if symbol_id is None or symbol_type is None:
        raise ValueError("A context target requires a symbol and symbol type.")
    runtime_config = config.get_config()
    scope_restrictions = deepcopy(runtime_config.scope_restrictions)
    instructions = deepcopy(runtime_config.instructions)
    task = deepcopy(runtime_config.prompt_task)

    source = target_path.read_text(encoding="UTF-8")
    tree = ast.parse(source, filename=str(target_path))
    target = {
        "file": str(target_path.resolve()),
        "symbol": symbol_id,
        "symbol_type": symbol_type,
        "ast_data": ast_graph or {},
        "source_hash": _source_hash(target_path),
        "contracts": _targeted_contracts(tree, symbol_id, symbol_type),
    }
    scope_restrictions["source"] = str(target_path.resolve())
    if isinstance(region_or_path, RegionProposal):
        scope_restrictions["editable_spans"] = list(region_or_path.editable_spans)

    return {
        "task": task,
        "target": target,
        "instructions": instructions,
        "scope": scope_restrictions,
    }
