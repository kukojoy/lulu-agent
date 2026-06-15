from lulu_agent.agent_loop import AgentLoop
from lulu_agent.config import OPENAI_MODEL


def main():
    agent = AgentLoop()
    print(f"lulu-agent started. model={OPENAI_MODEL}")
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

        response = agent.run(user_input)
        print('[agent response:]', response)


if __name__ == "__main__":
    main()
