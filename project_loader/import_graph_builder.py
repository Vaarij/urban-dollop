import ast
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def build_import_graph(filename: Path) -> list:
    logger.info("Started finding import graphs")
    with filename.open('r', encoding="UTF-8") as file:
        tree = ast.parse(file.read(), filename=filename)
        
    imports = []
    
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name
                imports.append({
                    "name": mod, 
                    "potential_alias": [alias.asname or alias.name], 
                    "ImportFrom": False
                })
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                mod = f"{module}.{alias.name}" if module else alias.name
                imports.append({
                    "name": mod,
                    "potential_alias": [alias.asname or alias.name],
                    "ImportFrom": True
                })
    logger.info("Finished with import graph")
    return imports
    
    
    