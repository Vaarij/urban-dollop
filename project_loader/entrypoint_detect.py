"""
Important notation: (foo.py is the file in concern)
- Outgoing refers to an import going out of the file (foo.py has an import xyz line)
- Incoming refers to calls for the file (xyz.py has an import foo line)
"""

from pathlib import Path


def find_root_modules(module_counters: dict) -> list:
    roots = []
    for k,v in module_counters.items():
        if v["incoming"] == 0 and v["outgoing"] != 0:
            roots.append(k)
            
    return roots
        

def find_entry_points(module_path: Path, import_dict: dict, file_list:list) -> list:
    module_counters = {}
    
    def find_module(import_name: str, potential_alias:list, import_from: bool) -> str | None:
        # NOTE: This is a string match, needs to change for better results
        for filepath in file_list:
            tmp_target_dir = filepath.relative_to(module_path)
            path_without_extension = tmp_target_dir.with_suffix("")
            tmp_import_notation = ".".join(path_without_extension.parts)
            
            if import_name == str(tmp_import_notation):
                return filepath
        
        return None
    
    for file in file_list:
        if file not in module_counters:
            module_counters[file] = {
                "name" : file,
                "outgoing" : 0,
                "incoming" : 0,
            }
        imports = import_dict[str(file)]
        for dict_j in imports:
            module_counters[file]["outgoing"] += 1
            module_key = find_module(dict_j["name"], dict_j["potential_alias"], dict_j["ImportFrom"])
            if module_key is not None:
                if module_key not in module_counters:
                    module_counters[module_key] = {
                        "name" : module_key,
                        "outgoing" : 0,
                        "incoming" : 0,
                    }
                
                module_counters[module_key]["incoming"] += 1
    
    root_modules = find_root_modules(module_counters)
    return root_modules
    