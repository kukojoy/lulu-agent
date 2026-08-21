from dataclasses import asdict
from typing import Any

from lulu_agent.skills.store import SkillStore


class SkillInteractionService:
    def __init__(self, skill_store: SkillStore | None = None):
        self.skill_store = skill_store or SkillStore()

    def list_skills(self) -> dict[str, Any]:
        result = self.skill_store.list_skills()
        return {
            "root": result.root,
            "skills": [asdict(skill) for skill in result.skills],
            "load_issues": [asdict(issue) for issue in result.load_issues],
        }

    def read_skill(self, name: str) -> dict[str, Any]:
        result = self.skill_store.read_skill(name)
        return result.to_dict(("name", "description", "path", "directory", "content"))
