class DomainException(Exception):
    """Base for all application-level errors."""
    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)


class EntityNotFoundError(DomainException):
    pass


class AuthenticationError(DomainException):
    pass


class BusinessLogicError(DomainException):
    """A business rule was violated (e.g. pages exceed book length)."""
    pass


class BookResolutionError(DomainException):
    """Could not resolve the book — title not found in DB or external APIs."""
    pass


class ReadingLimitError(BusinessLogicError):
    """User tried to log/set more pages than the book contains."""
    pass


class ExternalServiceError(DomainException):
    """An external dependency (Google Books, LLM) failed or timed out."""
    def __init__(self, service: str, message: str):
        self.service = service
        super().__init__(f"{service}: {message}")
