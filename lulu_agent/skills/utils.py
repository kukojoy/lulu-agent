import shutil

from pathlib import Path

from lulu_agent.skills.store import DEFAULT_SKILLS_ROOT, SkillStore


DEFAULT_BUNDLED_SKILLS_ROOT = Path(__file__).parent / "bundled"


def install_bundled_skills(
    bundled_root: str | Path = DEFAULT_BUNDLED_SKILLS_ROOT,
    skills_root: str | Path = DEFAULT_SKILLS_ROOT,
) -> list[dict]:
    bundled_root = Path(bundled_root)
    skills_root = Path(skills_root)
    result = SkillStore(bundled_root).list_skills()
    records: list[dict] = []

    for error in result.errors:
        records.append(
            {
                "action": "error",
                "path": error.path,
                "error": error.error,
            }
        )

    for skill in result.skills:
        source = Path(skill.directory)
        target = skills_root / skill.name
        if target.exists():
            records.append(
                {
                    "action": "skipped",
                    "name": skill.name,
                    "path": str(target.resolve()),
                    "reason": "Skill already exists.",
                }
            )
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copytree(source, target)
        except OSError as exc:
            records.append(
                {
                    "action": "error",
                    "name": skill.name,
                    "path": str(target),
                    "error": str(exc),
                }
            )
            continue

        records.append(
            {
                "action": "installed",
                "name": skill.name,
                "path": str(target.resolve()),
            }
        )

    return records
