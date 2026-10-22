class ConfigurationError(RuntimeError):
    """Raised when a required local dependency is missing or invalid."""


class SearchScriptError(RuntimeError):
    """Raised when the external LlamaIndex search process fails."""


class LocationResolutionError(ValueError):
    """Base class for facility-name resolution failures."""


class LocationNotFoundError(LocationResolutionError):
    """Raised when a facility name cannot be resolved."""


class AmbiguousLocationError(LocationResolutionError):
    """Raised when a facility name resolves to multiple nodes."""


class RouteNotFoundError(RuntimeError):
    """Raised when no graph path connects two resolved facilities."""


class MapRenderError(RuntimeError):
    """Raised when the fixed route-map renderer fails."""
