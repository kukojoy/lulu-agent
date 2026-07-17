from typing import Any

from lulu_agent.tools.tool import Tool
from lulu_agent.config import config

class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

def create_tool_registry() -> ToolRegistry:
    from lulu_agent.tools.native.list_files import list_files
    from lulu_agent.tools.native.memory import memory
    from lulu_agent.tools.native.read_file import read_file
    from lulu_agent.tools.native.replace_in_file import replace_in_file
    from lulu_agent.tools.native.run_shell import run_shell
    from lulu_agent.tools.native.search_text import search_text
    from lulu_agent.tools.native.skill import skill
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
    registry.register(skill)
    registry.register(task_state)

    if config.tavily_api_key:
        registry.register(web_search)
        registry.register(web_extract)

    try:
        from lulu_agent.mcp.registry import register_mcp_tools

        register_mcp_tools(registry)
    except Exception:
        pass

    return registry
