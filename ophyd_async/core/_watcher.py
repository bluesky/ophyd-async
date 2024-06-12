from typing import Any, Generic, Protocol, TypeVar

C = TypeVar("C", contravariant=True)


class Watcher(Protocol, Generic[C]):
    @staticmethod
    def __call__(
        *,
        current: C,
        initial: C,
        target: C,
        name: str | None,
        unit: str | None,
        precision: float | None,
        fraction: float | None,
        time_elapsed: float | None,
        time_remaining: float | None,
    ) -> Any: ...
