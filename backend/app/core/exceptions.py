class DomainException(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)


class EntityNotFoundError(DomainException):
    pass


class AuthenticationError(DomainException):
    pass


class BusinessLogicError(DomainException):
    pass


class BookResolutionError(EntityNotFoundError):
    pass


class ReadingLimitError(BusinessLogicError):
    pass


class ExternalServiceError(DomainException):
    def __init__(self, service: str, message: str):
        self.service = service
        super().__init__(f"{service}: {message}")
