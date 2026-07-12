from pathlib import Path
from typing import Tuple, Any

""" Don't write this to state, it can be rebuilt from ast_graphs.json anytime"""
def find_max_hotspots(ast_graph: dict) -> Tuple[Any | None, int]:
    # NOTE: Score is max nest depth + max conditionals
    highest_score = -1
    best_file = None

    for file_path, blocks in ast_graph.items():
        # The data structure separates standalone functions into blocks[0]
        functions = blocks[0]
        
        # Calculate total score for the current file
        file_score = sum(func["max_conditionals"] + func["max_nesting"] for func in functions)
        
        # Track the file with the highest score
        if file_score > highest_score:
            highest_score = file_score
            best_file = file_path

    # NOTE: this is hacky, make it work better and throw an exception
    best_file_path = Path(best_file)
    
    return best_file_path, highest_score