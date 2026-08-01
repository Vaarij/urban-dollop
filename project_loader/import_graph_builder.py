from __future__ import annotations

import ast
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def build_import_graph(filename: Path) -> list[dict[str, object]]:
    logger.info("Started finding import graphs")
    with filename.open("r", encoding="UTF-8") as file:
        tree = ast.parse(file.read(), filename=str(filename))

    imports: list[dict[str, object]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append({
                    "name": alias.name,
                    "module": alias.name,
                    "imported_name": None,
                    "potential_alias": [alias.asname or alias.name.split(".")[0]],
                    "ImportFrom": False,
                    "level": 0,
                })
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                imports.append({
                    "name": f"{module}.{alias.name}" if module else alias.name,
                    "module": module,
                    "imported_name": alias.name,
                    "potential_alias": [alias.asname or alias.name],
                    "ImportFrom": True,
                    "level": node.level,
                })
    logger.info("Finished with import graph")
    return imports
