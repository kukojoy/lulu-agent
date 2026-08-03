from cli.input import read_user_input
from lulu_agent.safety.approval import ApprovalProvider, ApprovalRequest


class CliApprovalProvider(ApprovalProvider):
    def request_approval(self, request: ApprovalRequest) -> bool:
        print()
        print("[approval required]")
        print(f"category: {request.category}")
        print(f"reason: {request.reason}")
        print(f"subject: {request.subject}")
        try:
            answer = read_user_input("Allow once? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt, OSError):
            return False
        return answer in {"y", "yes"}
