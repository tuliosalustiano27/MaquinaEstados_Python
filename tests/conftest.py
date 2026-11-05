import pytest


class FakeClock:
    """Relógio controlado: ``clock()`` devolve o tempo; ``clock.advance(s)`` avança."""

    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()
