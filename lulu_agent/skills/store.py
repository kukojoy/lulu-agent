"""
skill store 模块, 用于从 global skills 库中读取和写入 skill

当前特性:
1. skills 库路径默认为: ~/.lulu/skills, 其中每个 skill 以目录形式存在
2. 每个 skill 目录下必须包含 SKILL.md 文件, 其中必须包含 YAML frontmatter (metadata), 其中至少包含 name 和 description
3. skill store 向工具层提供 skill metadata 列举和完整 skill 内容读取能力
4. skill store 向上下文管理器提供完整 skill metadata, 用于转换为 context block, 在每轮对话中提供技能上下文
"""

import fcntl
import re

from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lulu_agent.runtime.errors import ERROR_INVALID_ARGUMENTS, ERROR_NOT_FOUND, ErrorType, LuluError


DEFAULT_SKILLS_ROOT = Path.home() / ".lulu" / "skills"
SKILL_FILE_NAME = "SKILL.md"
MAX_SKILL_NAME_LENGTH = 64
MAX_SKILL_DESCRIPTION_LENGTH = 1024
SKILL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$")
ALLOWED_SUPPORT_DIRS = {"references", "templates", "scripts"}


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str
    path: str
    directory: str


@dataclass(frozen=True)
class SkillLoadIssue:
    path: str
    issue_message: str


@dataclass(frozen=True)
class SkillResult:
    root: str
    skills: list[SkillMetadata] = field(default_factory=list)
    load_issues: list[SkillLoadIssue] = field(default_factory=list)
    name: str = ""
    description: str = ""
    path: str = ""
    directory: str = ""
    content: str = ""
    content_length: int = 0

    def to_dict(self, fields: tuple[str, ...]) -> dict[str, Any]:
        return {field: getattr(self, field) for field in fields}


class SkillStoreError(LuluError):
    def __init__(self, error_message: str, error_type: ErrorType = ERROR_INVALID_ARGUMENTS):
        super().__init__(error_message, error_type)


class SkillStore:
    def __init__(self, root: str | Path = DEFAULT_SKILLS_ROOT):
        self.root = Path(root)

    # === 对外接口 ===
    def list_skills(self) -> SkillResult:
        """列举所有技能, 返回 skill metadata 列表和加载问题列表"""
        root = self.root.resolve()

        # root 不存在时, 不返回错误信息
        if not root.exists():
            return self._result(
                root=str(root),
                skills=[],
                load_issues=[],
            )

        if not self.root.is_dir():
            return self._result(
                root=str(root),
                skills=[],
                load_issues=[
                    SkillLoadIssue(
                        path=str(root),
                        issue_message="Skills root is not a directory",
                    )
                ],
            )

        skills: list[SkillMetadata] = []
        load_issues: list[SkillLoadIssue] = []

        seen_names: set[str] = set()
        for directory in sorted(self.root.iterdir(), key=lambda path: path.name):
            if not directory.is_dir():
                continue

            skill_path = directory / SKILL_FILE_NAME
            if not skill_path.exists():
                load_issues.append(
                    SkillLoadIssue(
                        path=str(skill_path.resolve()),
                        issue_message=f"Missing {SKILL_FILE_NAME}.",
                    )
                )
                continue

            try:
                metadata = self._load_skill_metadata(skill_path, directory)
            except SkillStoreError as exc:
                load_issues.append(
                    SkillLoadIssue(
                        path=str(skill_path.resolve()),
                        issue_message=exc.error_message,
                    )
                )
                continue

            if metadata.name in seen_names:
                load_issues.append(
                    SkillLoadIssue(
                        path=metadata.path,
                        issue_message=f"Duplicate skill name: {metadata.name}.",
                    )
                )
                continue

            seen_names.add(metadata.name)
            skills.append(metadata)

        return self._result(
            root=str(root),
            skills=sorted(skills, key=lambda skill: skill.name),
            load_issues=load_issues,
        )

    def read_skill(self, name: str) -> SkillResult:
        """读取指定名称 skill 全文"""
        name = name.strip()
        self._validate_name(name)

        result = self.list_skills()
        matches = [skill for skill in result.skills if skill.name == name]
        if not matches:
            raise SkillStoreError(f"Skill not found: {name}", ERROR_NOT_FOUND)

        if len(matches) > 1:
            raise SkillStoreError(f"Multiple skills matched name: {name}")

        skill = matches[0]
        path = Path(skill.path)
        content = path.read_text(encoding="utf-8")

        return self._result(
            name=skill.name,
            description=skill.description,
            path=skill.path,
            directory=skill.directory,
            content=content,
        )

    def create_skill(self, name: str, description: str) -> SkillResult:
        """按指定 name 和 description 创建 skill 模版"""
        name = name.strip()
        description = description.strip()

        with self._file_lock():
            skill_dir = self._skill_dir(name)
            skill_path = skill_dir / SKILL_FILE_NAME

            if skill_dir.exists():
                raise SkillStoreError(f"Skill already exists: {name}")
            self._validate_description(description)

            skill_dir.mkdir(parents=True, exist_ok=False)
            content = self._render_skill_template(name, description)
            skill_path.write_text(content, encoding="utf-8")

            return self._result(
                name=name,
                path=str(skill_path.resolve()),
                content_length=len(content),
            )

    def update_skill(self, name: str, content: str) -> SkillResult:
        """更新 skill 正文 (全覆盖)"""
        name = name.strip()

        with self._file_lock():
            skill_path = self._existing_skill_path(name)
            self._validate_content(name, content)
            skill_path.write_text(content, encoding="utf-8")

            return self._result(
                name=name,
                path=str(skill_path.resolve()),
                content_length=len(content),
            )

    def patch_skill(self, name: str, old_text: str, new_text: str) -> SkillResult:
        """替换 skill 正文指定内容"""
        name = name.strip()

        if not old_text:
            raise SkillStoreError("old_text must not be empty.")
        if old_text == new_text:
            raise SkillStoreError("old_text and new_text are identical; no changes made.")

        with self._file_lock():
            skill_path = self._existing_skill_path(name)
            content = skill_path.read_text(encoding="utf-8")
            count = content.count(old_text)
            
            if count == 0:
                raise SkillStoreError("old_text not found in SKILL.md.")
            if count > 1:
                raise SkillStoreError(
                    f"old_text appears {count} times in SKILL.md; provide more context."
                )

            new_content = content.replace(old_text, new_text, 1)
            self._validate_content(name, new_content)
            skill_path.write_text(new_content, encoding="utf-8")

            return self._result(
                name=name,
                path=str(skill_path.resolve()),
                content_length=len(new_content),
            )

    def write_file(self, name: str, file_path: str, content: str) -> SkillResult:
        """写入 skill 支持文件 (references, templates, scripts)"""
        name = name.strip()
        with self._file_lock():
            target = self._support_file_path(name, file_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

            return self._result(
                name=name,
                path=str(target.resolve()),
                content_length=len(content),
            )

    def remove_file(self, name: str, file_path: str) -> SkillResult:
        """删除 skill 支持文件 (references, templates, scripts)"""
        name = name.strip()
        with self._file_lock():
            target = self._support_file_path(name, file_path)
            if not target.exists():
                raise SkillStoreError(f"File not found: {file_path}", ERROR_NOT_FOUND)
            if not target.is_file():
                raise SkillStoreError(f"Path is not a file: {file_path}")

            path = str(target.resolve())
            target.unlink()

            return self._result(
                name=name,
                path=path,
            )

    # === validate ===
    def _validate_name(self, name: str) -> None:
        """校验 skill 名称合法性

        规则:
        - 名称不能为空, 且要以字母或数字开头和结尾
        - 名称长度不能超过 64 个字符
        - 名称只能包含 ASCII 字母、数字或连字符
        """

        if not name:
            raise SkillStoreError("Skill name must not be empty.")

        if len(name) > MAX_SKILL_NAME_LENGTH:
            raise SkillStoreError(
                f"Skill name exceeds {MAX_SKILL_NAME_LENGTH} characters."
            )

        if not SKILL_NAME_PATTERN.fullmatch(name):
            raise SkillStoreError(
                "Skill name must use only ASCII letters, numbers, or hyphens."
            )
    
    def _validate_description(self, description: str) -> None:
        if not description:
            raise SkillStoreError("description is required for create.")
        if len(description) > MAX_SKILL_DESCRIPTION_LENGTH:
            raise SkillStoreError(
                f"Skill description exceeds {MAX_SKILL_DESCRIPTION_LENGTH} characters."
            )
        
    def _validate_content(self, name: str, content: str) -> None:
        frontmatter = self._parse_frontmatter(content)
        declared_name = frontmatter["name"]
        description = frontmatter["description"]

        self._validate_name(declared_name)
        if declared_name != name:
            raise SkillStoreError(
                f"Skill name must match directory name: {declared_name} != {name}"
            )
        if not description:
            raise SkillStoreError("Missing required field: description")
        if len(description) > MAX_SKILL_DESCRIPTION_LENGTH:
            raise SkillStoreError(
                f"Skill description exceeds {MAX_SKILL_DESCRIPTION_LENGTH} characters."
            )

    # === parse === 
    def _load_skill_metadata(self, skill_path: Path, directory: Path) -> SkillMetadata:
        """加载 skill metadata"""
        content = skill_path.read_text(encoding="utf-8")
        frontmatter = self._parse_frontmatter(content)
        name = frontmatter.get("name", "")
        description = frontmatter.get("description", "")

        self._validate_name(name)
        if name != directory.name:
            raise SkillStoreError(
                f"Skill name must match directory name: {name} != {directory.name}"
            )
        if not description:
            raise SkillStoreError("Missing required field: description")

        if len(description) > MAX_SKILL_DESCRIPTION_LENGTH:
            raise SkillStoreError(
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
            raise SkillStoreError("Missing YAML frontmatter delimited by ---.")

        end_index = None
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                end_index = index
                break
        if end_index is None:
            raise SkillStoreError("Missing YAML frontmatter closing delimiter ---.")

        values: dict[str, str] = {}
        for line in lines[1:end_index]:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if ":" not in stripped:
                raise SkillStoreError(f"Invalid frontmatter line: {stripped}")
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                raise SkillStoreError(f"Invalid frontmatter line: {stripped}")
            values[key] = self._unquote_scalar(value)

        if "name" not in values:
            raise SkillStoreError("Missing required field: name")
        if "description" not in values:
            raise SkillStoreError("Missing required field: description")

        return values

    def _unquote_scalar(self, value: str) -> str:
        """去除 YAML frontmatter 中的字符串值的引号

        Example:
            '"example"' -> "example"
        """
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            return value[1:-1]
        return value
    
    # === build ===
    def _skill_dir(self, name: str) -> Path:
        """构造 skill 目录路径"""
        self._validate_name(name)
        return self.root / name

    def _existing_skill_path(self, name: str) -> Path:
        """获取 skill 的 SKILL.md 文件路径并验证"""
        skill_dir = self._skill_dir(name)
        skill_path = skill_dir / SKILL_FILE_NAME

        if not skill_path.exists():
            raise SkillStoreError(f"Skill not found: {name}", ERROR_NOT_FOUND)
        if not skill_path.is_file():
            raise SkillStoreError(f"Skill path is not a file: {skill_path}")
        
        return skill_path

    def _support_file_path(self, name: str, file_path: str) -> Path:
        """获取 skill 支持文件的完整路径并验证"""
        self._existing_skill_path(name)
        relative = Path(file_path)

        if not file_path or relative.is_absolute():
            raise SkillStoreError("file_path must be a relative path.")
        if ".." in relative.parts:
            raise SkillStoreError("file_path must not contain '..'.")
        if not relative.parts or relative.parts[0] not in ALLOWED_SUPPORT_DIRS:
            allowed = ", ".join(sorted(ALLOWED_SUPPORT_DIRS))
            raise SkillStoreError(f"file_path must start with one of: {allowed}.")
        if len(relative.parts) == 1:
            raise SkillStoreError("file_path must include a file name.")

        skill_dir = self._skill_dir(name)
        target = skill_dir / relative
        try:
            target.resolve().relative_to(skill_dir.resolve())
        except ValueError:
            raise SkillStoreError("file_path resolves outside the skill directory.")
        
        return target

    def _render_skill_template(self, name: str, description: str) -> str:
        """渲染 skill 模版内容"""
        title = name.replace("-", " ").title()
        
        return (
            "---\n"
            f"name: {name}\n"
            f"description: {description}\n"
            "---\n\n"
            f"# {title}\n\n"
            "## When to use\n\n"
            "## Core principles\n\n"
            "## Workflow\n\n"
            "## Support files\n"
        )

    def _result(
        self,
        root: str = "",
        skills: list[SkillMetadata] | None = None,
        load_issues: list[SkillLoadIssue] | None = None,
        name: str = "",
        description: str = "",
        path: str = "",
        directory: str = "",
        content: str = "",
        content_length: int = 0,
    ) -> SkillResult:
        return SkillResult(
            root=root,
            skills=list(skills or []),
            load_issues=list(load_issues or []),
            name=name,
            description=description,
            path=path,
            directory=directory,
            content=content,
            content_length=content_length,
        )
    
    @contextmanager
    def _file_lock(self):
        lock_path = self.root / ".lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
