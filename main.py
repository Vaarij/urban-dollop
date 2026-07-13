import logging
from project_loader import file_discover, import_graph_builder, entrypoint_detect
# NOTE: as of right now ast parser functions as more of a project loader, might be worth it to move into project_loader
from analyze import ast_parser, hotspot_detector
from context_builder import prompt_packager
from pathlib import Path
import state_storage as storage

logger = logging.getLogger(__name__)

# NOTE: for debug only right now:
test_dir = Path("/Users/vaarijbetala/Desktop/model-optimize")


# NOTE: add logic for state to only be used in case the project crashes at some point
# NOTE: if building a state loader, you also need a manifest which documents the current requirements
# NOTE: kind of tedious to pass state dir everytime, consider making state dir a class with the dir as a constant, because then I can add to gitignore with _local
# NOTE: On startup, make sure a directory called optimized exists, where the final files will be stored.
STATE_DIR = Path("state")
STATE_DIR.mkdir(parents=True, exist_ok=True)

#NOTE: might be helpful to split work up
def main():
    logging.basicConfig(handlers=[logging.FileHandler("_local/app.log", mode="w")],
                        level=logging.INFO, 
                        format='%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S',
                        )
    logger.info("Started")
    file_smoke = file_discover.walk_through(test_dir)
    final_payload = [str(p) for p in file_smoke]
    storage.save_file_list(STATE_DIR, final_payload)
    
    logger.info("Looping through imports")
    all_imports = {}
    for i in file_smoke:
        tmpImports = import_graph_builder.build_import_graph(i)
        # NOTE: Make this dict assignment better and safer
        all_imports[str(i)] = tmpImports
    logger.info("Finished looping through import")
    
    storage.save_import_graph(STATE_DIR, all_imports)
    
    logger.info("Starting Detection of Potential Entry Points")
    roots = entrypoint_detect.find_entry_points(test_dir, all_imports, file_smoke)
    logger.info("Ending Detection of Potential Entry Points")
    
    roots_str = [str(p) for p in roots]
    storage.save_entry_points(STATE_DIR, roots_str)
    
    logger.info("Starting AST Parser")
    all_asts = {}
    for i in file_smoke:
        tmpAST = ast_parser.block_generator(i)
        all_asts[str(i)] = tmpAST
    
    storage.save_ast_graphs(STATE_DIR, all_asts)
    
    file_name, score = hotspot_detector.find_max_hotspots(all_asts)
    # print(all_asts[str(file_name)])
    
    print(prompt_packager.build_context_file(file_name, "generate_complexity_metrics", "function", all_asts[str(file_name)]))
    
    logger.info("Ended")
    

if __name__ == "__main__":
    main()