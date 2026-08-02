from dataclasses import dataclass


@dataclass(frozen=True)
class Plan:
    steps: list[str]

    @property
    def summary(self) -> str:
        return "\n".join(f"{index}. {step}" for index, step in enumerate(self.steps, start=1))


class Planner:
    def create_plan(self, user_message: str) -> Plan:
        message = user_message.lower()

        if any(keyword in message for keyword in ("read", "search", "find", "where", "show")):
            return Plan(
                steps=[
                    "Search the relevant project files.",
                    "Read the matching files.",
                    "Summarize the useful findings.",
                ]
            )

        if any(keyword in message for keyword in ("fix", "change", "add", "build", "implement", "create", "modify")):
            return Plan(
                steps=[
                    "Inspect the relevant files.",
                    "Make the smallest correct code change.",
                    "Run verification commands.",
                    "Summarize the changed files and results.",
                ]
            )

        if any(keyword in message for keyword in ("run", "test", "build", "lint")):
            return Plan(
                steps=[
                    "Identify the correct command for the project.",
                    "Run the command in the terminal sandbox.",
                    "Report the output and any errors.",
                ]
            )

        return Plan(
            steps=[
                "Understand the request.",
                "Gather any required context.",
                "Respond with the most useful next action.",
            ]
        )
