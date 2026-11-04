"""Typed errors used at OpsPilot module boundaries."""


class OpsPilotError(Exception):
    """Base class for expected application errors."""


class ConfigurationError(OpsPilotError):
    """Raised when a configuration file is missing or invalid."""


class SimulationError(OpsPilotError):
    """Raised when a simulation cannot be completed safely."""


class KnowledgeBaseError(OpsPilotError):
    """Raised when knowledge documents, indexes, or retrieval inputs are invalid."""

