import secrets
from typing import Optional


def extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token:
        return None
    return token


def token_matches(expected: Optional[str], provided: Optional[str]) -> bool:
    if not expected or not provided:
        return False
    return secrets.compare_digest(expected, provided)
