class SailhouseError(Exception):
    """Base exception for Sailhouse errors"""
    pass


class AuthenticationError(SailhouseError):
    """Raised when authentication fails"""
    pass


class PublishError(SailhouseError):
    """Raised when publishing fails"""
    pass
