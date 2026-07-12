from pathlib import Path 
import logging
# from config import PROJECT_SUBDIR

# NOTE: Make this an absolute path eventually
# p = Path(PROJECT_SUBDIR)
logger = logging.getLogger(__name__)

SKIPPED_DIRS = [".gitignore", "cache", ".git", ".venv", "venv", "env", "__pycache__",
                ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".nox", "node_modules",
                "build", "dist", ".idea", ".vscode"]

def walk_through(root_dir: Path):
    files_in_project = []
    logger.info(f"Walking through {root_dir.name}")
    for root, dirs, files in root_dir.walk():
        dirs[:] = [d for d in dirs if d not in SKIPPED_DIRS]
            
        for filename in files:
            if filename.endswith('.py'):
                files_in_project.append(root / filename)
    
    return files_in_project

# FIXME: Add support to find test files

def find_test_files():
    raise NotImplementedError()