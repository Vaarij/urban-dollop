import ast
from pathlib import Path


# NOTE: Now assume you have your final candidate

def final_candidate(passing_function: ast.AST, file_path: Path):
    with file_path.open('r', encoding='UTF-8') as file:
        tree = ast.parse(file.read(), filename= file_path)
    
    """ Add in the function over here"""
    
    """ Return the file as python and place into a new folder optimized"""