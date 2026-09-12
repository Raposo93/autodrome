import secrets
import time
from collections import OrderedDict
from typing import Callable, Optional


class WebSocketTicketCapacityError(RuntimeError):
    pass


class WebSocketTicketStore:
    DEFAULT_TTL_SECONDS = 45
    DEFAULT_MAX_PENDING = 1024
    TOKEN_BYTES = 32

    def __init__(
        self,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        max_pending: int = DEFAULT_MAX_PENDING,
        clock: Callable[[], float] = time.monotonic,
        token_factory: Optional[Callable[[], str]] = None,
    ):
        if ttl_seconds <= 0:
            raise ValueError("WebSocket ticket TTL must be positive")
        if max_pending <= 0:
            raise ValueError("WebSocket ticket capacity must be positive")
        self.ttl_seconds = ttl_seconds
        self.max_pending = max_pending
        self._clock = clock
        self._token_factory = token_factory or (
            lambda: secrets.token_urlsafe(self.TOKEN_BYTES)
        )
        self._tickets = OrderedDict()

    def issue(self) -> str:
        now = self._clock()
        self._discard_expired(now)
        if len(self._tickets) >= self.max_pending:
            raise WebSocketTicketCapacityError(
                "Too many pending WebSocket tickets"
            )

        for _ in range(10):
            ticket = self._token_factory()
            if ticket and ticket not in self._tickets:
                self._tickets[ticket] = now + self.ttl_seconds
                return ticket
        raise RuntimeError("Could not generate a unique WebSocket ticket")

    def consume(self, ticket: Optional[str]) -> bool:
        now = self._clock()
        self._discard_expired(now)
        if not ticket:
            return False
        return self._tickets.pop(ticket, None) is not None

    @property
    def pending_count(self) -> int:
        self._discard_expired(self._clock())
        return len(self._tickets)

    def _discard_expired(self, now: float) -> None:
        while self._tickets:
            ticket, expires_at = next(iter(self._tickets.items()))
            if expires_at > now:
                return
            del self._tickets[ticket]
