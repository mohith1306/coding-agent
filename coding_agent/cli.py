import logging
import os
from pathlib import Path


EXIT_COMMANDS = {"exit", "quit", ":q"}
CONFIRM_YES = {"yes", "y"}


def _build_agent_graph(root: Path):
    """Build an AgentGraph with all dependencies wired up."""
    from .context import ContextBuilder
    from .intent import IntentParser
    from .llm import create_llm
    from .memory import MemoryStore
    from .planner import Planner
    from .tools.registry import ToolRegistry
    from .verifier import Verifier
    from .graph import AgentGraph

    memory = MemoryStore()
    intent_parser = IntentParser()
    context_builder = ContextBuilder(memory, root=root)
    planner = Planner()
    tool_registry = ToolRegistry(root)
    verifier = Verifier(root=root, terminal=tool_registry.terminal)

    try:
        llm = create_llm()
    except RuntimeError as error:
        logger.warning("LLM unavailable: %s. Falling back to old agent.", error)
        return None

    return AgentGraph(
        root=root,
        llm=llm,
        tool_registry=tool_registry,
        intent_parser=intent_parser,
        context_builder=context_builder,
        planner=planner,
        verifier=verifier,
        memory=memory,
    )


def _build_legacy_agent(root: Path):
    """Build the legacy CodingAgent (fallback)."""
    from .agent import CodingAgent
    return CodingAgent(root=root)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    logger = logging.getLogger(__name__)

    root = Path.cwd().resolve()
    use_graph = os.getenv("CODING_AGENT_USE_GRAPH", "true").lower() == "true"

    agent_graph = None
    legacy_agent = None

    if use_graph:
        agent_graph = _build_agent_graph(root)
        if agent_graph:
            print("Coding Agent CLI (LangGraph runtime)")
        else:
            logger.info("Graph unavailable; using legacy agent")
            legacy_agent = _build_legacy_agent(root)
            print("Coding Agent CLI (legacy runtime)")
    else:
        legacy_agent = _build_legacy_agent(root)
        print("Coding Agent CLI (legacy runtime)")

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
            print("\nExiting.")
            if agent_graph:
                agent_graph.close()
            return

        if agent_graph:
            result = agent_graph.invoke(user_input)
            response = result.get("final_response", "") or ""
            print(f"\nAgent: {response}")
        else:
            from .agent import CONFIRMATION_MARKER
            response = legacy_agent.handle(user_input)

            if response.startswith(CONFIRMATION_MARKER):
                print(f"\nAgent: {response}")
                try:
                    confirm = input("\nProceed? (yes/no): ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print("\nCancelled.")
                    continue

                if confirm in CONFIRM_YES:
                    response = legacy_agent.handle(user_input, confirmed=True)
                    print(f"\nAgent: {response}")
                else:
                    print("\nAgent: Cancelled.")
                continue

            print(f"\nAgent: {response}")


if __name__ == "__main__":
    main()
