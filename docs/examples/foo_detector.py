import asyncio

from bluesky.protocols import HasHints, Hints

from ophyd_async.core import (
    AsyncStatus,
    DetectorController,
    DetectorTrigger,
    PathProvider,
    StandardDetector,
)
from ophyd_async.epics import adcore
from ophyd_async.epics.signal import epics_signal_rw_rbv


class FooDriver(adcore.ADBaseIO):
    def __init__(self, prefix: str, name: str = "") -> None:
        self.trigger_mode = epics_signal_rw_rbv(str, prefix + "TriggerMode")
        super().__init__(prefix, name)


class FooController(DetectorController):
    def __init__(self, driver: FooDriver) -> None:
        self._drv = driver

    def get_deadtime(self, exposure: float) -> float:
        # FooDetector deadtime handling
        return 0.001

    async def arm(
        self,
        num: int,
        trigger: DetectorTrigger = DetectorTrigger.internal,
        exposure: float | None = None,
    ) -> AsyncStatus:
        await asyncio.gather(
            self._drv.num_images.set(num),
            self._drv.image_mode.set(adcore.ImageMode.multiple),
            self._drv.trigger_mode.set(f"FOO{trigger}"),
        )
        if exposure is not None:
            await self._drv.acquire_time.set(exposure)
        return await adcore.start_acquiring_driver_and_ensure_status(self._drv)

    async def disarm(self):
        await adcore.stop_busy_record(self._drv.acquire, False, timeout=1)


class FooDetector(StandardDetector, HasHints):
    _controller: FooController
    _writer: adcore.ADHDFWriter

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix="cam1:",
        hdf_suffix="HDF1:",
        name="",
    ):
        # Must be children to pick up connect
        self.drv = FooDriver(prefix + drv_suffix)
        self.hdf = adcore.NDFileHDFIO(prefix + hdf_suffix)

        super().__init__(
            FooController(self.drv),
            adcore.ADHDFWriter(
                self.hdf,
                path_provider,
                lambda: self.name,
                adcore.ADBaseDatasetDescriber(self.drv),
            ),
            config_sigs=(self.drv.acquire_time,),
            name=name,
        )

    @property
    def hints(self) -> Hints:
        return self._writer.hints
