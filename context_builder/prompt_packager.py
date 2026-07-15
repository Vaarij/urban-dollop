from pathlib import Path
from copy import deepcopy

import config

# NOTE: Get a working hash
# NOTE: dynamically build contracts for functions, input types, return types
def build_context_file(target_path: Path, symbol_id: str, symbol_type: str, ast_graph: dict):
    scope_restrictions = deepcopy(config.SCOPE_RESTRICTIONS)
    instructions = deepcopy(config.INSTRUCTIONS)
    task = deepcopy(config.TASK_CONFIG)

    target = {
        "file" : str(target_path),
        "symbol" : symbol_id,
        "symbol_type": symbol_type,
        "ast_data": ast_graph,
        "source_hash" : "sha..."
    }
    scope_restrictions["source"] = str(target_path)
    
    return {
        "task" : task,
        "target" : target,
        "instructions" : instructions,
        "scope" : scope_restrictions,
    }
