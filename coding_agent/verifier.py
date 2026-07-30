from dataclasses import dataclass


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    message: str


class Verifier:
    def verify_no_changes(self) -> VerificationResult:
        return VerificationResult(
            passed=True,
            message="No file changes were made in this basic chat step.",
        )
