# Deterministic fault injection

Fault injection belongs under `tests/`; production code must never import these
helpers or expose a fault flag.

Use `FaultInjector` when code can call a named boundary directly. Point names use
`component.operation.phase`, and schedules identify the exact hit plus the
exception type:

```python
faults = FaultInjector(
    "queue-running-write",
    {"queue.persist.running": {1: OSError}},
)
faults.hit("queue.persist.running")
faults.assert_complete()
```

Use `ScriptedCall` for a finite provider response sequence such as
`429 → 429 → OK`. Always call `assert_complete()` so a test cannot pass without
reaching every intended fault. Prefer events or explicit gates to timing sleeps,
temporary directories to real library paths, and assertions about the protected
invariant (durable state, publication, identity, or retry count), not just the
raised exception.

To add a point, name the exact existing boundary in the test wrapper, schedule the
smallest useful failure, and include the scenario and point in assertion messages.
Do not add hooks to application code solely for fault injection.
