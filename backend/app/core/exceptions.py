"""Application exceptions that map safely to HTTP errors."""


class ApplicationError(Exception):
    """Base class for expected application failures."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status_code: int,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class ConfigurationError(ApplicationError):
    """Raised when a required runtime setting is missing."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            code="CONFIGURATION_ERROR",
            status_code=503,
        )


class LLMTimeoutError(ApplicationError):
    """Raised when the model provider does not respond in time."""

    def __init__(self, message: str = "The language model request timed out.") -> None:
        super().__init__(
            message,
            code="LLM_TIMEOUT",
            status_code=504,
        )


class LLMConnectionError(ApplicationError):
    """Raised when the model provider cannot be reached."""

    def __init__(
        self,
        message: str = "Could not connect to the language model provider.",
    ) -> None:
        super().__init__(
            message,
            code="LLM_CONNECTION_ERROR",
            status_code=502,
        )


class LLMUpstreamError(ApplicationError):
    """Raised for provider-side API failures."""

    def __init__(
        self,
        message: str = "The language model provider returned an error.",
    ) -> None:
        super().__init__(
            message,
            code="LLM_UPSTREAM_ERROR",
            status_code=502,
        )

