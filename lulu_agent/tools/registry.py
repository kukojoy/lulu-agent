from dataclasses import dataclass
from typing import Any

from lulu_agent.tools.tool import Tool
from lulu_agent.config import config

DEFAULT_TOOL_SAFETY_PROFILE = config.safety_profile

@dataclass(frozen=True)
class ToolRegistryIssue:
    source: str
    issue_message: str


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._issues: list[ToolRegistryIssue] = []
        self._safety_profiles: dict[str, str] = {}

    def register(self, tool: Tool, safety_profile: str = DEFAULT_TOOL_SAFETY_PROFILE):
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool
        self._safety_profiles[tool.name] = safety_profile

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def add_issue(self, source: str, issue_message: str):
        self._issues.append(ToolRegistryIssue(source=source, issue_message=issue_message))

    def get_issues(self) -> list[ToolRegistryIssue]:
        return list(self._issues)

    def set_safety_profile(self, tool_name: str, safety_profile: str):
        if tool_name not in self._tools:
            raise ValueError(f"Tool not registered: {tool_name}")
        self._safety_profiles[tool_name] = safety_profile

    def get_safety_profile(self, tool_name: str) -> str | None:
        return self._safety_profiles.get(tool_name)

    def list_mcp_tools(self) -> dict[str, Any]:
        servers: dict[str, dict[str, Any]] = {}
        for tool_name, tool in self._tools.items():
            if not tool_name.startswith("mcp:"):
                continue
            parts = tool_name.split(":", 2)
            if len(parts) != 3 or not parts[1]:
                continue

            server_name, tool_name_display = parts[1], parts[2]
            server = servers.setdefault(
                server_name,
                {
                    "name": server_name,
                    "safety_profile": self.get_safety_profile(tool.name),
                    "tools": [],
                },
            )
            server["tools"].append(
                {
                    "name": tool_name_display,
                    "description": tool.description,
                }
            )
        return {
            "servers": list(servers.values())
        }


def create_tool_registry() -> ToolRegistry:
    from lulu_agent.tools.native.list_files import list_files
    from lulu_agent.tools.native.memory import memory
    from lulu_agent.tools.native.read_file import read_file
    from lulu_agent.tools.native.replace_in_file import replace_in_file
    from lulu_agent.tools.native.run_shell import run_shell
    from lulu_agent.tools.native.search_text import search_text
    from lulu_agent.tools.native.skill_lookup import skill_lookup
    from lulu_agent.tools.native.skill_manage import skill_manage
    from lulu_agent.tools.native.task_state import task_state
    from lulu_agent.tools.native.web_extract import web_extract
    from lulu_agent.tools.native.web_search import web_search
    from lulu_agent.tools.native.write_file import write_file

    registry = ToolRegistry()

    registry.register(read_file)
    registry.register(write_file)
    registry.register(run_shell)
    registry.register(list_files)
    registry.register(search_text)
    registry.register(replace_in_file)
    registry.register(memory)
    registry.register(skill_lookup)
    registry.register(skill_manage)
    registry.register(task_state)

    if config.tavily_api_key:
        registry.register(web_search)
        registry.register(web_extract)

    try:
        from lulu_agent.mcp.registry import register_mcp_tools

        result = register_mcp_tools(registry)
        for issue in result.issues:
            source = f"mcp:{issue.server}" if issue.server else "mcp"
            registry.add_issue(source, issue.issue_message)
    except Exception as exc:
        registry.add_issue("mcp", str(exc) or exc.__class__.__name__)

    return registry
