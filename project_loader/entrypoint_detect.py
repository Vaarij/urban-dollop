"""
Important notation: (foo.py is the file in concern)
- Outgoing refers to an import going out of the file (foo.py has an import xyz line)
- Incoming refers to calls for the file (xyz.py has an import foo line)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def module_name_from_path(module_path: Path, file_path: Path) -> str:
    relative_path = file_path.resolve().relative_to(module_path.resolve())
    module_parts = list(relative_path.parts)
    module_parts[-1] = Path(module_parts[-1]).stem
    if module_parts[-1] == "__init__":
        module_parts.pop()
    return ".".join(module_parts)


def build_module_index(module_path: Path, file_list: list[Path]) -> dict[str, Path]:
    return {
        module_name: file_path
        for file_path in file_list
        if (module_name := module_name_from_path(module_path, file_path))
    }


def _package_parts_for_importer(module_path: Path, importer: Path) -> list[str]:
    module_name = module_name_from_path(module_path, importer)
    if not module_name:
        return []
    if importer.stem == "__init__":
        return module_name.split(".")
    return module_name.split(".")[:-1]


def _candidate_module_names(
    import_record: dict[str, Any],
    importer: Path,
    module_path: Path,
) -> list[str]:
    module_name = str(import_record.get("module") or "")
    imported_name = str(import_record.get("imported_name") or "")
    level = int(import_record.get("level") or 0)
    candidates: list[str] = []

    if import_record.get("ImportFrom"):
        if level > 0:
            package_parts = _package_parts_for_importer(module_path, importer)
            keep_count = max(0, len(package_parts) - max(0, level - 1))
            base_parts = package_parts[:keep_count]
            prefix = [*base_parts, *(part for part in module_name.split(".") if part)]
            if imported_name and imported_name != "*":
                candidates.append(".".join([*prefix, imported_name]))
            if prefix:
                candidates.append(".".join(prefix))
        else:
            if import_record["name"]:
                candidates.append(str(import_record["name"]))
            if module_name and imported_name and imported_name != "*":
                candidates.append(f"{module_name}.{imported_name}")
            if module_name:
                candidates.append(module_name)
    else:
        import_name = str(import_record["name"])
        candidates.append(import_name)
        if "." in import_name:
            candidates.append(import_name.rsplit(".", 1)[0])

    seen: set[str] = set()
    return [candidate for candidate in candidates if candidate and not (candidate in seen or seen.add(candidate))]


def resolve_import_target(
    module_path: Path,
    importer: Path,
    import_record: dict[str, Any],
    module_index: dict[str, Path],
) -> Path | None:
    for candidate in _candidate_module_names(import_record, importer, module_path):
        if candidate in module_index:
            return module_index[candidate]
    return None


def find_root_modules(module_counters: dict[Path, dict[str, Any]]) -> list[Path]:
    roots = [
        file_path
        for file_path, counters in module_counters.items()
        if counters["incoming"] == 0 and counters["outgoing"] != 0
    ]
    if roots:
        return roots
    return [file_path for file_path, counters in module_counters.items() if counters["incoming"] == 0]


def find_entry_points(
    module_path: Path,
    import_dict: dict[str, list[dict[str, Any]]],
    file_list: list[Path],
) -> list[Path]:
    module_index = build_module_index(module_path, file_list)
    module_counters = {
        file_path: {"name": file_path, "outgoing": 0, "incoming": 0}
        for file_path in file_list
    }

    for file_path in file_list:
        for import_record in import_dict.get(str(file_path), []):
            module_key = resolve_import_target(module_path, file_path, import_record, module_index)
            if module_key is None or module_key == file_path:
                continue
            module_counters[file_path]["outgoing"] += 1
            module_counters[module_key]["incoming"] += 1

    return find_root_modules(module_counters)
