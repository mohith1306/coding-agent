import logging

from .agent import CONFIRMATION_MARKER, CodingAgent


EXIT_COMMANDS = {"exit", "quit", ":q"}
CONFIRM_YES = {"yes", "y"}


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

        if response.startswith(CONFIRMATION_MARKER):
            print(f"\nAgent: {response}")
            try:
                confirm = input("\nProceed? (yes/no): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nCancelled.")
                continue

            if confirm in CONFIRM_YES:
                response = agent.handle(user_input, confirmed=True)
                print(f"\nAgent: {response}")
            else:
                print("\nAgent: Cancelled.")
            continue

        print(f"\nAgent: {response}")


if __name__ == "__main__":
    main()
