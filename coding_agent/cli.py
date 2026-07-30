import logging

from .agent import CodingAgent


EXIT_COMMANDS = {"exit", "quit", ":q"}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

    agent = CodingAgent()

    print("Coding Agent CLI")
    print("Type your request. Use 'exit', 'quit', or ':q' to stop.")

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            return

        if not user_input:
            continue

        if user_input.lower() in EXIT_COMMANDS:
            print("Exiting.")
            return

        response = agent.handle(user_input)
        print(f"\nAgent: {response}")
