"""
skill 加载器模块, 用于从 skills 库中读取 skill metadata 以及完整内容

当前特性:
1. skills 库路径为: cwd/.lulu/skills, 其中每个 skill 以目录形式存在
2. 每个 skill 目录下必须包含 SKILL.md 文件, 其中必须包含 YAML frontmatter (metadata), 其中至少包含 name 和 description
3. skill 加载器向工具层提供 skill metadata 列举和完整 skill 内容读取能力
4. skill 加载器向上下文管理器提供完整 skill metadata, 用于转换为 context block, 在每轮对话中提供技能上下文
"""

import re
from dataclasses import dataclass
from pathlib import Path


DEFAULT_SKILLS_ROOT = ".lulu/skills"
SKILL_FILE_NAME = "SKILL.md"
MAX_SKILL_NAME_LENGTH = 64
MAX_SKILL_DESCRIPTION_LENGTH = 1024
SKILL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$")


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str
    path: str
    directory: str


@dataclass(frozen=True)
class SkillLoadError:
    path: str
    error: str


@dataclass(frozen=True)
class SkillListResult:
    root: str
    skills: list[SkillMetadata]
    errors: list[SkillLoadError]


@dataclass(frozen=True)
class SkillDocument:
    name: str
    description: str
    path: str
    directory: str
    content: str


class SkillLoaderError(ValueError):
    pass


class SkillLoader:
    def __init__(self, root: str | Path = DEFAULT_SKILLS_ROOT):
        self.root = Path(root)

    def list_skills(self) -> SkillListResult:
        """列举所有技能, 返回 skill metadata 列表和错误消息列表"""
        root = self.root.resolve()

        # root 不存在时, 不返回错误信息
        if not root.exists():
            return SkillListResult(
                root=str(root), 
                skills=[],
                errors=[]
            )
        
        if not self.root.is_dir():
            return SkillListResult(
                root=str(root), 
                skills=[],
                errors=[
                    SkillLoadError(
                        path=str(root),
                        error="Skills root is not a directory",
                    )
                ]
            )

        skills: list[SkillMetadata] = []
        errors: list[SkillLoadError] = []
        seen_names: set[str] = set()

        for directory in sorted(self.root.iterdir(), key=lambda path: path.name):
            if not directory.is_dir():
                continue

            skill_path = directory / SKILL_FILE_NAME
            if not skill_path.exists():
                errors.append(
                    SkillLoadError(
                        path=str(skill_path.resolve()),
                        error=f"Missing {SKILL_FILE_NAME}.",
                    )
                )
                continue

            try:
                metadata = self._load_metadata(skill_path, directory)
            except SkillLoaderError as exc:
                errors.append(
                    SkillLoadError(
                        path=str(skill_path.resolve()),
                        error=str(exc),
                    )
                )
                continue

            if metadata.name in seen_names:
                errors.append(
                    SkillLoadError(
                        path=metadata.path,
                        error=f"Duplicate skill name: {metadata.name}.",
                    )
                )
                continue

            seen_names.add(metadata.name)
            skills.append(metadata)

        return SkillListResult(
            root=str(root),
            skills=sorted(skills, key=lambda skill: skill.name),
            errors=errors,
        )

    def read_skill(self, name: str) -> SkillDocument:
        """读取指定名称 skill 全文"""
        name = name.strip()
        self._validate_name(name)

        result = self.list_skills()
        matches = [skill for skill in result.skills if skill.name == name]
        if not matches:
            raise SkillLoaderError(f"Skill not found: {name}")
        
        if len(matches) > 1:
            raise SkillLoaderError(f"Multiple skills matched name: {name}")

        skill = matches[0]
        path = Path(skill.path)
        content = path.read_text(encoding="utf-8")
        return SkillDocument(
            name=skill.name,
            description=skill.description,
            path=skill.path,
            directory=skill.directory,
            content=content,
        )

    def _load_metadata(self, skill_path: Path, directory: Path) -> SkillMetadata:
        """加载 skill metadata"""
        content = skill_path.read_text(encoding="utf-8")
        frontmatter = self._parse_frontmatter(content)
        name = frontmatter.get("name", "")
        description = frontmatter.get("description", "")

        self._validate_name(name)
        if name != directory.name:
            raise SkillLoaderError(
                f"Skill name must match directory name: {name} != {directory.name}"
            )
        if not description:
            raise SkillLoaderError("Missing required field: description")
        
        if len(description) > MAX_SKILL_DESCRIPTION_LENGTH:
            raise SkillLoaderError(
                f"Skill description exceeds {MAX_SKILL_DESCRIPTION_LENGTH} characters."
            )

        return SkillMetadata(
            name=name,
            description=description,
            path=str(skill_path.resolve()),
            directory=str(directory.resolve()),
        )

    def _parse_frontmatter(self, content: str) -> dict[str, str]:
        """从 SKILL.md 完整内容中解析 YAML frontmatter
        
        Returns:
            dict[str, str]: 包含 frontmatter 键值对 (name, description 等)
        """
        lines = content.splitlines()
        if not lines or lines[0].strip() != "---":
            raise SkillLoaderError("Missing YAML frontmatter delimited by ---.")

        end_index = None
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                end_index = index
                break
        if end_index is None:
            raise SkillLoaderError("Missing YAML frontmatter closing delimiter ---.")

        values: dict[str, str] = {}
        for line in lines[1: end_index]:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if ":" not in stripped:
                raise SkillLoaderError(f"Invalid frontmatter line: {stripped}")
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                raise SkillLoaderError(f"Invalid frontmatter line: {stripped}")
            values[key] = self._unquote_scalar(value)

        if "name" not in values:
            raise SkillLoaderError("Missing required field: name")
        if "description" not in values:
            raise SkillLoaderError("Missing required field: description")
        
        return values

    def _validate_name(self, name: str) -> None:
        """校验 skill 名称合法性
        规则: 
        - 名称不能为空, 且要以字母或数字开头和结尾
        - 名称长度不能超过 64 个字符
        - 名称只能包含 ASCII 字母、数字或连字符
        """

        if not name:
            raise SkillLoaderError("Skill name must not be empty.")
        
        if len(name) > MAX_SKILL_NAME_LENGTH:
            raise SkillLoaderError(
                f"Skill name exceeds {MAX_SKILL_NAME_LENGTH} characters."
            )
        
        if not SKILL_NAME_PATTERN.fullmatch(name):
            raise SkillLoaderError(
                "Skill name must use only ASCII letters, numbers, or hyphens."
            )

    def _unquote_scalar(self, value: str) -> str:
        """去除 YAML frontmatter 中的字符串值的引号
        
        Example:
            '"example"' -> "example"
        """
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            return value[1: -1]
        return value
