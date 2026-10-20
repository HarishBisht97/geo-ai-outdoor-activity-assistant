from typing import Any


class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class BadRequestError(AppError):
    status_code = 400
    code = "bad_request"


class OverloadedError(AppError):
    status_code = 503
    code = "overloaded"

    def __init__(self, message: str = "Server is busy, please retry shortly.", retry_after_s: int = 15):
        super().__init__(message, {"retry_after_s": retry_after_s})
        self.retry_after_s = retry_after_s


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"


class ProviderError(Exception):
    """Raised inside adapters; always converted to a typed failure before reaching the pipeline."""

    def __init__(self, provider: str, message: str, status: int | None = None):
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.message = message
        self.status = status


class SLMUnavailableError(Exception):
    pass


class SLMTimeoutError(Exception):
    pass
