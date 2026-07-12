import ast
from pathlib import Path
from typing import Tuple, List # NOTE: standardize with typing library all over project

""" 
AST Parser should just compile a graph of function blocks per file
This is stupid, but this function will also clip code per block
Recursion is getting stuck, either on the while loop at 33 or if statement at 23
"""
# NOTE: make this a helper function with an underscore before the name
def is_dataclass_decorated(cls: ast.ClassDef) -> bool:
    for d in cls.decorator_list:
        # Handles: @dataclass
        if isinstance(d, ast.Name) and d.id == "dataclass":
            return True
        # Handles: @dataclasses.dataclass
        if isinstance(d, ast.Attribute) and d.attr == "dataclass":
            return True
    return False

def _max_nested_elements(start: ast.AST) -> int:
    """
    Finds the maximum nesting depth of statements within a node.
    Using an explicit stack avoids recursive errors.
    """
    max_nesting = 0
    # The stack stores tuples of (node, current_depth)
    stack = [(start, 0)]
    
    while stack:
        node, current_depth = stack.pop()
        
        # We only increment depth for structural statement blocks
        is_stmt_block = isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.FunctionDef, ast.ClassDef))
        
        # If it's a structural statement block (and not the entry node), increment depth
        new_depth = current_depth + 1 if (is_stmt_block and node is not start) else current_depth
        max_nesting = max(max_nesting, new_depth)
        
        # Add all child nodes to the stack to continue exploring deeper
        for child in ast.iter_child_nodes(node):
            stack.append((child, new_depth))
            
    return max_nesting

def _max_conditionals(start: ast.AST) -> int:
    """
    Finds the maximum number of individual conditions inside any BoolOp chain.
    Iterative stack approach replaces the previous recursive logic.
    """
    max_num_conditionals = 0
    
    for sub_node in ast.walk(start):
        if isinstance(sub_node, ast.BoolOp):
            # Flatten out nested BoolOps using a stack
            total = 0
            bool_stack = [sub_node]
            
            while bool_stack:
                current = bool_stack.pop()
                for val in current.values:
                    if isinstance(val, ast.BoolOp):
                        bool_stack.append(val)
                    else:
                        total += 1
                        
            max_num_conditionals = max(max_num_conditionals, total)
        
    return max_num_conditionals

def block_generator(file_path : Path) -> Tuple[List, List]:
    functions = []
    classes = []
    
    with file_path.open('r', encoding="UTF-8") as file:
        tree = ast.parse(file.read(), filename=file_path)
        
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            start = node.lineno - 1
            end = node.end_lineno if node.end_lineno is not None else start
            max_conditionals = _max_conditionals(node)
            max_nesting = _max_nested_elements(node)
            functions.append({
                "function_name" : node.name,
                "start_line": start,
                "end_line" : end,
                "max_conditionals" : max_conditionals,
                "max_nesting" : max_nesting,
                })
            
        if isinstance(node, ast.ClassDef):
            tmpFn = []
            isdataclass = False
            start = node.lineno - 1
            end = node.end_lineno if node.end_lineno is not None else start
            if not is_dataclass_decorated(node):
                for sub_node in ast.walk(node):
                    if isinstance(sub_node, ast.FunctionDef):
                        sub_start = sub_node.lineno - 1
                        sub_end = sub_node.end_lineno if sub_node.end_lineno is not None else sub_start
                        max_conditionals = _max_conditionals(sub_node)
                        max_nesting = _max_nested_elements(sub_node)
                        tmpFn.append({
                            "function_name" : sub_node.name,
                            "start_line" : sub_start,
                            "end_line" : sub_end,
                            "max_conditionals" : max_conditionals,
                            "max_nesting" : max_nesting,
                        })
            
            else:
                isdataclass = True
            
            classes.append({
                "class_name" : node.name,
                "class_methods" : tmpFn,
                "data_class" : isdataclass,
                "start_line": start,
                "end_line" : end,
            })
            
    return functions, classes
