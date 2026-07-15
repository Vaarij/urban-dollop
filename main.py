import logging
from project_loader import file_discover, import_graph_builder, entrypoint_detect
# NOTE: as of right now ast parser functions as more of a project loader, might be worth it to move into project_loader
from analyze import ast_parser, hotspot_detector
from context_builder import prompt_packager
from config import RuntimeConfig, get_config
import state_storage as storage

logger = logging.getLogger(__name__)


def _ensure_runtime_dirs(runtime_config: RuntimeConfig) -> None:
    runtime_config.local_dir.mkdir(parents=True, exist_ok=True)
    runtime_config.state_dir.mkdir(parents=True, exist_ok=True)
    runtime_config.optimized_dir.mkdir(parents=True, exist_ok=True)


def main(runtime_config: RuntimeConfig | None = None) -> int:
    runtime_config = runtime_config or get_config()
    _ensure_runtime_dirs(runtime_config)
    logging.basicConfig(
        handlers=[logging.FileHandler(runtime_config.local_dir / "app.log", mode="w")],
        level=logging.INFO,
        format='%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    runtime_config.write_json()

    run_succeeded = False

    try:
        logger.info("Started")
        if runtime_config.recovery_token is not None:
            logger.info(
                "Recovery token %s requested, but recovery loading is not implemented yet.",
                runtime_config.recovery_token,
            )

        file_smoke = file_discover.walk_through(runtime_config.target_dir)
        final_payload = [str(p) for p in file_smoke]
        storage.save_file_list(runtime_config.state_dir, final_payload)

        logger.info("Looping through imports")
        all_imports = {}
        for file_path in file_smoke:
            tmp_imports = import_graph_builder.build_import_graph(file_path)
            # NOTE: Make this dict assignment better and safer
            all_imports[str(file_path)] = tmp_imports
        logger.info("Finished looping through import")

        storage.save_import_graph(runtime_config.state_dir, all_imports)

        logger.info("Starting Detection of Potential Entry Points")
        roots = entrypoint_detect.find_entry_points(
            runtime_config.target_dir,
            all_imports,
            file_smoke,
        )
        logger.info("Ending Detection of Potential Entry Points")

        roots_str = [str(p) for p in roots]
        storage.save_entry_points(runtime_config.state_dir, roots_str)

        logger.info("Starting AST Parser")
        all_asts = {}
        for file_path in file_smoke:
            tmp_ast = ast_parser.block_generator(file_path)
            all_asts[str(file_path)] = tmp_ast

        storage.save_ast_graphs(runtime_config.state_dir, all_asts)

        file_name, _score = hotspot_detector.find_max_hotspots(all_asts)
        print(
            prompt_packager.build_context_file(
                file_name,
                "generate_complexity_metrics",
                "function",
                all_asts[str(file_name)],
            )
        )

        logger.info("Ended")
        run_succeeded = True
        return 0
    except Exception:
        logger.exception("Optimizer run failed")
        raise
    finally:
        if run_succeeded:
            runtime_config.cleanup_json()

if __name__ == "__main__":
    raise SystemExit("Run `uv run self-optimize --target <path>`.")
