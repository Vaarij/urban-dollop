from pathlib import Path

# NOTE: Generate this from config.py based on user input
TASK = {
    "task_id": "opt-0042",
    "action": "optimize_hotspot",
    "objective": "reduce complexity while preserving observable behavior"
  }

SCOPE_RESTRICTIONS = {
    "source": "...",
    "allowed_changes": [
      "function body"
    ],
    "forbidden_changes": [
      "function name",
      "parameters",
      "return contract",
      "other files"
    ]
  }

INSTRUCTIONS = {
    "return_format": "structured_mutation",
    "may_request_more_context": True,
    "do_not_return_entire_file": True,
    "explain_behavioral_equivalence": True
  }

# NOTE: Get a working hash
# NOTE: dynamically build contracts for functions, input types, return types
def build_context_file(target_path: Path, symbol_id: str, symbol_type: str, ast_graph: dict):
    target = {
        "file" : str(target_path),
        "symbol" : symbol_id,
        "symbol_type": symbol_type,
        "ast_data": ast_graph,
        "source_hash" : "sha..."
    }
    
    return {
        "task" : TASK,
        "target" : target,
        "instructions" : INSTRUCTIONS,
        "scope" : SCOPE_RESTRICTIONS,
    }