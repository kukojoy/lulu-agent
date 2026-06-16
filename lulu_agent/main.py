from lulu_agent.agent_loop import AgentLoop
from lulu_agent.config import ConfigError
from lulu_agent.llm_client import LLMClientError


def main():
    try:
        agent = AgentLoop()
    except ConfigError as exc:
        print(f"Config error: {exc}")
        return

    print(f"lulu-agent started. model={agent.llm_client.model}")
    print("Type /exit or /quit to exit.")

    while True:
        try:
            user_input = input("\nlulu-agent> ").strip()
            print('[user query:]', user_input)
        except EOFError:
            print('[EOFError] bye')
            break
        
        if not user_input:
            continue
        if user_input in {"/exit", "/quit"}:
            print("bye")
            break

        try:
            response = agent.run(user_input)
        except LLMClientError as exc:
            print(f"LLM error: {exc}")
            continue
        print('[agent response:]', response)


if __name__ == "__main__":
    main()
