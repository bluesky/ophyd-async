import asyncio
from collections.abc import Callable

from ._device import Device
from ._protocol import AsyncStageable
from ._status import AsyncStatus, AsyncStatusBase


class _StandardBase(Device, AsyncStageable):
    """Base for `Device` mix-ins that contribute to `stage()`/`unstage()`.

    `StandardReadable`, `StandardFlyable` and similar mix-ins each need to run
    something on `stage()`/`unstage()`. Rather than each defining those methods
    and shadowing the others via the MRO when combined on one `Device` (e.g. a
    motor that is Readable + Movable + Flyable), they register callables into
    `_stage_funcs`/`_unstage_funcs`, which this single base gathers.
    """

    # Immutable defaults to avoid accidental sharing between instances
    _stage_funcs: tuple[Callable[[], AsyncStatusBase], ...] = ()
    _unstage_funcs: tuple[Callable[[], AsyncStatusBase], ...] = ()

    @AsyncStatus.wrap
    async def stage(self) -> None:
        await asyncio.gather(*(func().task for func in self._stage_funcs))

    @AsyncStatus.wrap
    async def unstage(self) -> None:
        await asyncio.gather(*(func().task for func in self._unstage_funcs))
