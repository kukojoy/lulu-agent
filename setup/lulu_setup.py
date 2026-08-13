from __future__ import annotations

import shutil
from pathlib import Path


SETUP_DIR = Path(__file__).resolve().parent
REPO_ROOT = SETUP_DIR.parent
HOME_DIR = Path.home() / ".lulu"
MEMORY_PATH = HOME_DIR / "memory" / "MEMORY.md"
SKILLS_ROOT = HOME_DIR / "skills"
TEMPLATE_DIR = SETUP_DIR / "template"
BUILT_IN_SKILLS_DIR = SETUP_DIR / "built_in_skills"
MCP_TEMPLATE_PATH = TEMPLATE_DIR / "mcp.json"
MODELS_TEMPLATE_PATH = TEMPLATE_DIR / "models.json"


def main() -> int:
    actions: list[str] = []
    actions.extend(ensure_memory())
    actions.extend(install_built_in_skills())
    actions.extend(ensure_template(MCP_TEMPLATE_PATH, HOME_DIR / "mcp.json"))
    actions.extend(ensure_template(MODELS_TEMPLATE_PATH, HOME_DIR / "models.json"))

    for action in actions:
        print(action)
    return 0


def ensure_memory() -> list[str]:
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if MEMORY_PATH.exists():
        return [f"[skip] memory: {MEMORY_PATH}"]
    MEMORY_PATH.write_text("", encoding="utf-8")
    return [f"[create] memory: {MEMORY_PATH}"]


def install_built_in_skills() -> list[str]:
    if not BUILT_IN_SKILLS_DIR.exists():
        return [f"[skip] built-in skills: seed directory missing ({BUILT_IN_SKILLS_DIR})"]

    records: list[str] = []
    SKILLS_ROOT.mkdir(parents=True, exist_ok=True)
    for source in sorted(path for path in BUILT_IN_SKILLS_DIR.iterdir() if path.is_dir()):
        target = SKILLS_ROOT / source.name
        if target.exists():
            records.append(f"[skip] built-in skill: {source.name}")
            continue
        shutil.copytree(source, target)
        records.append(f"[install] built-in skill: {source.name}")
    return records


def ensure_template(source: Path, target: Path) -> list[str]:
    if not source.exists():
        return [f"[skip] template: missing {source.name}"]

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return [f"[skip] file: {target}"]
    shutil.copyfile(source, target)
    return [f"[create] file: {target}"]


if __name__ == "__main__":
    raise SystemExit(main())
