"""Domain errors. The API maps these to HTTP status codes."""


class DomainError(Exception):
    """Base class for rule violations. Message is safe to show to staff (no PHI)."""

    status_code = 400

    def __init__(self, message: str, *, rule_id: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.rule_id = rule_id


class GuardViolation(DomainError):
    """A state-machine guard rule blocked the action."""

    status_code = 422


class NotFound(DomainError):
    status_code = 404


class Conflict(DomainError):
    """Optimistic concurrency failure: someone else appended an event first."""

    status_code = 409


class Forbidden(DomainError):
    status_code = 403
