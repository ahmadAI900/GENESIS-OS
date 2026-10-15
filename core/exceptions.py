"""
Genesis OS
Core Exception Hierarchy

Task:
    21.2 — Reliability Foundation

Purpose:
    Give Genesis predictable, categorized failures.

Important:
    Exceptions represent exceptional conditions.

    GenesisResult represents normal success/failure
    communication between subsystems.
"""


class GenesisError(Exception):
    """
    Base exception for Genesis.
    """

    code = "GENESIS_ERROR"

    def __init__(
        self,
        message: str,
        *,
        recoverable: bool = True,
    ):
        super().__init__(message)

        self.message = str(message)

        self.recoverable = recoverable

    def __str__(self) -> str:

        return self.message


class ConfigurationError(GenesisError):
    """
    Invalid Genesis configuration.
    """

    code = "CONFIGURATION_ERROR"


class InitializationError(GenesisError):
    """
    Subsystem could not initialize.
    """

    code = "INITIALIZATION_ERROR"


class BrainError(GenesisError):
    """
    Core brain failure.
    """

    code = "BRAIN_ERROR"


class MemoryError(GenesisError):
    """
    Genesis memory failure.
    """

    code = "MEMORY_ERROR"


class ProviderError(GenesisError):
    """
    AI provider failure.
    """

    code = "PROVIDER_ERROR"


class AgentError(GenesisError):
    """
    Agent execution failure.
    """

    code = "AGENT_ERROR"


class WorkflowError(GenesisError):
    """
    Workflow routing failure.
    """

    code = "WORKFLOW_ERROR"


class OSError(GenesisError):
    """
    Genesis OS operation failure.

    This is intentionally named GenesisOSError rather than
    replacing Python's built-in OSError.
    """

    code = "OS_ERROR"


class ValidationError(GenesisError):
    """
    Invalid input or invalid subsystem data.
    """

    code = "VALIDATION_ERROR"