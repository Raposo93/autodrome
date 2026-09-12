import unittest

from autodrome.services.websocket_tickets import (
    WebSocketTicketCapacityError,
    WebSocketTicketStore,
)


class TestWebSocketTicketStore(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.next_ticket = 0

        def token_factory():
            self.next_ticket += 1
            return f"ticket-{self.next_ticket}"

        self.store = WebSocketTicketStore(
            ttl_seconds=45,
            max_pending=2,
            clock=lambda: self.now,
            token_factory=token_factory,
        )

    def test_ticket_is_valid_once(self):
        ticket = self.store.issue()

        self.assertTrue(self.store.consume(ticket))
        self.assertFalse(self.store.consume(ticket))

    def test_unknown_ticket_is_rejected(self):
        self.assertFalse(self.store.consume("unknown"))
        self.assertFalse(self.store.consume(None))

    def test_expired_ticket_is_rejected_and_removed(self):
        ticket = self.store.issue()

        self.now += 45

        self.assertFalse(self.store.consume(ticket))
        self.assertEqual(self.store.pending_count, 0)

    def test_pending_tickets_are_bounded_and_expired_entries_free_capacity(self):
        self.store.issue()
        self.store.issue()

        with self.assertRaises(WebSocketTicketCapacityError):
            self.store.issue()

        self.now += 45
        replacement = self.store.issue()
        self.assertEqual(replacement, "ticket-3")
        self.assertEqual(self.store.pending_count, 1)

    def test_default_tokens_have_cryptographic_entropy(self):
        store = WebSocketTicketStore()

        tickets = {store.issue() for _ in range(10)}

        self.assertEqual(len(tickets), 10)
        self.assertTrue(all(len(ticket) >= 40 for ticket in tickets))

    def test_new_store_does_not_recognize_pending_ticket(self):
        ticket = self.store.issue()
        restarted_store = WebSocketTicketStore(
            ttl_seconds=45,
            clock=lambda: self.now,
        )

        self.assertFalse(restarted_store.consume(ticket))


if __name__ == "__main__":
    unittest.main()
