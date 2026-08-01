from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

"""
AST Parser should just compile a graph of function blocks per file.
The traversal stays iterative so deeply nested control flow does not depend on recursion.
"""


def _is_dataclass_decorated(class_node: ast.ClassDef) -> bool:
    for decorator in class_node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "dataclass":
            return True
        if isinstance(decorator, ast.Attribute) and decorator.attr == "dataclass":
            return True
    return False


def _max_nested_elements(start: ast.AST) -> int:
    max_nesting = 0
    stack: list[tuple[ast.AST, int]] = [(start, 0)]

    while stack:
        node, current_depth = stack.pop()
        is_stmt_block = isinstance(
            node,
            (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
        )
        new_depth = current_depth + 1 if is_stmt_block and node is not start else current_depth
        max_nesting = max(max_nesting, new_depth)
        for child in ast.iter_child_nodes(node):
            stack.append((child, new_depth))

    return max_nesting


def _max_conditionals(start: ast.AST) -> int:
    max_num_conditionals = 0

    for sub_node in ast.walk(start):
        if not isinstance(sub_node, ast.BoolOp):
            continue
        total = 0
        bool_stack = [sub_node]
        while bool_stack:
            current = bool_stack.pop()
            for value in current.values:
                if isinstance(value, ast.BoolOp):
                    bool_stack.append(value)
                else:
                    total += 1
        max_num_conditionals = max(max_num_conditionals, total)

    return max_num_conditionals


def _block_data(function_node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, int | str]:
    start = function_node.lineno - 1
    end = function_node.end_lineno if function_node.end_lineno is not None else start
    return {
        "function_name": function_node.name,
        "start_line": start,
        "end_line": end,
        "max_conditionals": _max_conditionals(function_node),
        "max_nesting": _max_nested_elements(function_node),
    }


def _build_blocks(tree: ast.Module) -> tuple[list[dict[str, int | str]], list[dict[str, object]]]:
    functions: list[dict[str, int | str]] = []
    classes: list[dict[str, object]] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(_block_data(node))
            continue

        if not isinstance(node, ast.ClassDef):
            continue

        start = node.lineno - 1
        end = node.end_lineno if node.end_lineno is not None else start
        is_dataclass = _is_dataclass_decorated(node)
        class_methods = []
        if not is_dataclass:
            class_methods = [
                _block_data(child)
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]

        classes.append(
            {
                "class_name": node.name,
                "class_methods": class_methods,
                "data_class": is_dataclass,
                "start_line": start,
                "end_line": end,
            }
            )

    return functions, classes


def block_generator(file_path: Path) -> tuple[list[dict[str, int | str]], list[dict[str, object]]]:
    with file_path.open("r", encoding="UTF-8") as file:
        tree = ast.parse(file.read(), filename=str(file_path))
    return _build_blocks(tree)


def block_generator_from_source(
    source: str,
    filename: str = "<unknown>",
) -> tuple[list[dict[str, int | str]], list[dict[str, Any]]]:
    tree = ast.parse(source, filename=filename)
    return _build_blocks(tree)
