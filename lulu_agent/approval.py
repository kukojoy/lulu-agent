from lulu_agent.safety import SafetyDecision
from lulu_agent.cli_input import read_user_input

def request_cli_approval(decision: SafetyDecision, command: str) -> bool:
    """请求用户在 CLI 中批准操作
    
    Returns:
        bool: 用户是否批准操作 (输入y/yes)
    """
    print()
    print("[approval required]")
    print(f"category: {decision.category}")
    print(f"reason: {decision.reason}")
    print(f"command: {command}")
    try:
        answer = read_user_input("Allow once? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt, OSError):
        return False
    return answer in {"y", "yes"}
