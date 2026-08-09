"""Static backward-slice helpers."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

MAX_DISCRETE_COMBINATIONS = 10


@dataclass
class VariableDefinition:
    criterion: str
    line_number: int

@dataclass
class TargetDefinition:
    target: str
    expression: str
    depends_on_constant: bool
    depends_on: list[str]


def _variable_finder(tree: ast.AST) -> list[VariableDefinition]:
    """Return the variables defined by assignments."""
    definitions: list[VariableDefinition] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        if node.value is None:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            for name in ast.walk(target):
                if isinstance(name, ast.Name) and isinstance(name.ctx, ast.Store):
                    definitions.append(VariableDefinition(name.id, node.lineno))

    return definitions


def backward_slice( tree: ast.AST, variables: list[VariableDefinition]) -> list[TargetDefinition]:
    """Return target definitions for the variables in `tree`."""
    assignments = {
        node.lineno: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None
    }
    definitions: list[TargetDefinition] = []

    for variable in variables:
        node = assignments[variable.line_number]
        dependencies = [
            name.id
            for name in ast.walk(node.value)
            if isinstance(name, ast.Name) and isinstance(name.ctx, ast.Load)
        ]
        definitions.append(
            TargetDefinition(
                variable.criterion,
                ast.unparse(node.value),
                isinstance(node.value, ast.Constant),
                dependencies,
            )
        )

    return definitions


def _evaluate_expression(node: ast.expr, values: dict[str, object]) -> object:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return values[node.id]
    if isinstance(node, ast.IfExp):
        branch = node.body if _evaluate_expression(node.test, values) else node.orelse
        return _evaluate_expression(branch, values)
    if isinstance(node, ast.BinOp):
        left = _evaluate_expression(node.left, values)
        right = _evaluate_expression(node.right, values)
        operators = {
            ast.Add: lambda: left + right,
            ast.Sub: lambda: left - right,
            ast.Mult: lambda: left * right,
            ast.Div: lambda: left / right,
            ast.FloorDiv: lambda: left // right,
            ast.Mod: lambda: left % right,
            ast.Pow: lambda: left ** right,
        }
        return operators[type(node.op)]()
    raise ValueError(f"Unsupported transfer expression: {ast.unparse(node)}")


def transfer_function_gen(
    definitions: list[TargetDefinition],
) -> dict[str, list[tuple[dict[str, object], object]]]:
    """Return concrete outputs for the possible constant dependency values."""
    definitions_by_target = {definition.target: definition for definition in definitions}
    target_order = {definition.target: index for index, definition in enumerate(definitions)}
    cache: dict[str, list[tuple[dict[str, object], object]]] = {}

    def outputs_for(target: str) -> list[tuple[dict[str, object], object]]:
        if target in cache:
            return cache[target]

        definition = definitions_by_target[target]
        expression = ast.parse(definition.expression, mode="eval").body
        if definition.depends_on_constant:
            values = [expression.value]
            if isinstance(expression.value, bool):
                values = [True, False]
            cache[target] = [
                ({target: value}, value)
                for value in values[:MAX_DISCRETE_COMBINATIONS]
            ]
            return cache[target]

        scenarios = [({}, {})]
        for dependency in sorted(
            set(definition.depends_on), key=lambda name: (target_order.get(name, len(definitions)), name)
        ):
            next_scenarios = []
            for inputs, values in scenarios:
                for dependency_inputs, output in outputs_for(dependency):
                    next_scenarios.append(
                        ({**inputs, **dependency_inputs}, {**values, dependency: output})
                    )
                    if len(next_scenarios) == MAX_DISCRETE_COMBINATIONS:
                        break
                if len(next_scenarios) == MAX_DISCRETE_COMBINATIONS:
                    break
            scenarios = next_scenarios
        cache[target] = [
            (inputs, _evaluate_expression(expression, values))
            for inputs, values in scenarios
        ]
        return cache[target]

    return {definition.target: outputs_for(definition.target) for definition in definitions}
    


def main():
    target_path = Path("/Users/vaarijbetala/Desktop/self-optimize/_local/scratch.py")
    tree = ast.parse(target_path.read_text(encoding="UTF-8"), filename=str(target_path))
    targets = backward_slice(tree, _variable_finder(tree))
    print(targets)
    print("-------------------")
    print(transfer_function_gen(targets))
    
if __name__ == "__main__":
    main()
