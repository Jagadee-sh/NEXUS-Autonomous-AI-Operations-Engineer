"""Domain exceptions."""

from __future__ import annotations


class NexusError(Exception):
    """Base error; carries an HTTP-friendly code."""

    def __init__(self, message: str, code: str = "nexus_error", status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class NotFoundError(NexusError):
    def __init__(self, message: str = "Resource not found"):
        super().__init__(message, code="not_found", status_code=404)


class PermissionDeniedError(NexusError):
    def __init__(self, message: str = "Permission denied"):
        super().__init__(message, code="permission_denied", status_code=403)


class ValidationError(NexusError):
    def __init__(self, message: str = "Validation failed"):
        super().__init__(message, code="validation_error", status_code=422)


class SecurityError(NexusError):
    def __init__(self, message: str = "Security violation"):
        super().__init__(message, code="security_violation", status_code=400)


class TimeoutError_(NexusError):
    def __init__(self, message: str = "Operation timed out"):
        super().__init__(message, code="timeout", status_code=504)


class ApprovalRequiredError(NexusError):
    def __init__(self, message: str = "Human approval required", approval_id: str | None = None):
        super().__init__(message, code="approval_required", status_code=202)
        self.approval_id = approval_id


class ProviderError(NexusError):
    def __init__(self, message: str = "LLM provider error"):
        super().__init__(message, code="provider_error", status_code=502)
