"""Small deterministic fault helpers; never import this module in production."""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any


class FaultInjector:
    """Raise configured exception types at exact named hit numbers."""

    def __init__(
        self,
        scenario: str,
        failures: Mapping[str, Mapping[int, type[Exception]]],
    ) -> None:
        if not scenario:
            raise ValueError("scenario must be named")
        self.scenario = scenario
        self.failures = {
            point: dict(scheduled) for point, scheduled in failures.items()
        }
        self.hits: dict[str, int] = defaultdict(int)
        self.history: list[tuple[str, int]] = []

        for point, scheduled in self.failures.items():
            if not point or not scheduled:
                raise ValueError("fault points and schedules must not be empty")
            if any(hit < 1 for hit in scheduled):
                raise ValueError("fault hit numbers must be positive")
            if any(
                not isinstance(error_type, type)
                or not issubclass(error_type, Exception)
                for error_type in scheduled.values()
            ):
                raise TypeError("scheduled faults must be exception types")

    def hit(self, point: str) -> None:
        """Record a named point and raise if this exact hit is scheduled."""
        self.hits[point] += 1
        hit_number = self.hits[point]
        self.history.append((point, hit_number))
        error_type = self.failures.get(point, {}).get(hit_number)
        if error_type is not None:
            raise error_type(
                f"Injected fault in scenario '{self.scenario}' at "
                f"'{point}' (hit {hit_number})"
            )

    def assert_complete(self) -> None:
        """Fail clearly if the code never reached a scheduled injection point."""
        missing = [
            f"{point} hit {hit_number}"
            for point, scheduled in self.failures.items()
            for hit_number in scheduled
            if self.hits[point] < hit_number
        ]
        if missing:
            raise AssertionError(
                f"Scenario '{self.scenario}' did not reach: {', '.join(missing)}"
            )


class ScriptedCall:
    """Return or raise a finite sequence for a named provider/test boundary."""

    def __init__(self, scenario: str, point: str, outcomes: Iterable[Any]) -> None:
        self.scenario = scenario
        self.point = point
        self.outcomes = list(outcomes)
        if not scenario or not point or not self.outcomes:
            raise ValueError("scripted calls need a scenario, point, and outcomes")
        self.calls = 0

    def __call__(self, *args, **kwargs):
        if self.calls >= len(self.outcomes):
            raise AssertionError(
                f"Scenario '{self.scenario}' exhausted scripted point "
                f"'{self.point}' after {self.calls} calls"
            )
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, BaseException):
            outcome.add_note(
                f"Injected by scenario '{self.scenario}' at '{self.point}' "
                f"(call {self.calls})"
            )
            raise outcome
        return outcome

    def assert_complete(self) -> None:
        if self.calls != len(self.outcomes):
            raise AssertionError(
                f"Scenario '{self.scenario}' used {self.calls} of "
                f"{len(self.outcomes)} outcomes at '{self.point}'"
            )
