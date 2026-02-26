"""Domain exceptions for gotg — raised by non-adapter layers."""


class GotgError(Exception):
    """Base for all gotg domain errors."""


class ConfigError(GotgError):
    """Configuration loading/validation failure."""


class ModelError(GotgError):
    """Model/provider communication failure."""


class GroomingError(GotgError):
    """Grooming session lifecycle error."""
