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


class LLMDisabledError(ApplicationError):
    """Raised when real model access is disabled for low-cost development."""

    def __init__(self) -> None:
        super().__init__(
            "真实模型已禁用，请使用本地 Mock 模式，或在配置明确预算后启用。",
            code="REAL_LLM_DISABLED",
            status_code=503,
        )


class LLMBudgetExceededError(ApplicationError):
    """Raised before a call that would exceed the configured LLM budget."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            f"模型预算已阻止本次请求：{reason}。",
            code="LLM_BUDGET_EXCEEDED",
            status_code=429,
        )

