from collections.abc import Callable
from typing import Any, Generic, get_type_hints

from ._derived_signal_backend import (
    DerivedSignalBackend,
    SignalTransformer,
    Transform,
    TransformT,
)
from ._device import Device
from ._signal import SignalR, SignalRW, SignalT, SignalW
from ._signal_backend import SignalDatatypeT
from ._status import AsyncStatus


class DerivedSignalCreator(Generic[TransformT]):
    def __init__(
        self,
        transform_cls: type[TransformT],
        set_derived: Callable[..., AsyncStatus] | None = None,
        **raw_and_transform_devices,
    ):
        self._set_derived = set_derived
        self._transformer = SignalTransformer(
            transform_cls, set_derived, **raw_and_transform_devices
        )

    def _make_signal(
        self,
        signal_cls: type[SignalT],
        datatype: type[SignalDatatypeT],
        name: str,
        set_name: str | None = None,
        units: str | None = None,
        precision: int | None = None,
    ) -> SignalT:
        # Check up front the raw_devices are of the right type for what the signal_cls
        # supports
        if issubclass(signal_cls, SignalR):
            self._transformer.raw_and_transform_readables  # noqa: B018
            self._transformer.raw_and_transform_subscribables  # noqa: B018
        if issubclass(signal_cls, SignalW) and not self._set_derived:
            msg = (
                f"Must define a set_derived method to support derived "
                f"{signal_cls.__name__}s"
            )
            raise ValueError(msg)
        if issubclass(signal_cls, SignalRW):
            self._transformer.raw_locatables  # noqa: B018
        self._transformer.register_derived(name, set_name)
        backend = DerivedSignalBackend(
            datatype, name, self._transformer, units, precision
        )
        return signal_cls(backend)

    def derived_signal_r(
        self,
        datatype: type[SignalDatatypeT],
        name: str,
        set_name: str | None = None,
        units: str | None = None,
        precision: int | None = None,
    ) -> SignalR[SignalDatatypeT]:
        return self._make_signal(SignalR, datatype, name, set_name, units, precision)

    def derived_signal_w(
        self,
        datatype: type[SignalDatatypeT],
        name: str,
        set_name: str | None = None,
        units: str | None = None,
        precision: int | None = None,
    ) -> SignalW[SignalDatatypeT]:
        return self._make_signal(SignalW, datatype, name, set_name, units, precision)

    def derived_signal_rw(
        self,
        datatype: type[SignalDatatypeT],
        name: str,
        set_name: str | None = None,
        units: str | None = None,
        precision: int | None = None,
    ) -> SignalRW[SignalDatatypeT]:
        return self._make_signal(SignalRW, datatype, name, set_name, units, precision)

    async def get_transform(self) -> TransformT:
        return await self._transformer.get_transform()


def _get_return_datatype(func: Callable[..., SignalDatatypeT]) -> type[SignalDatatypeT]:
    args = get_type_hints(func)
    if "return" not in args:
        msg = f"{func} does not have a type hint for it's return value"
        raise TypeError(msg)
    return args["return"]


def _get_first_arg_datatype(
    func: Callable[[SignalDatatypeT], Any],
) -> type[SignalDatatypeT]:
    args = get_type_hints(func)
    args.pop("return", None)
    if not args:
        msg = f"{func} does not have a type hinted argument"
        raise TypeError(msg)
    return list(args.values())[0]


def _make_creator(
    raw_to_derived: Callable[..., SignalDatatypeT] | None = None,
    set_derived: Callable[[SignalDatatypeT], AsyncStatus] | None = None,
    raw_devices: dict[str, Device] | None = None,
) -> DerivedSignalCreator:
    class DerivedTransform(Transform):
        def raw_to_derived(self, **kwargs) -> dict[str, SignalDatatypeT]:
            if raw_to_derived is None:
                msg = "raw_to_derived not defined"
                raise RuntimeError(msg)
            return {"value": raw_to_derived(**kwargs)}

        def derived_to_raw(self, value: SignalDatatypeT):
            msg = "derived_to_raw not implemented for a single derived_signal"
            raise RuntimeError(msg)

    raw_devices = raw_devices or {}
    return DerivedSignalCreator(
        DerivedTransform, set_derived=set_derived, **raw_devices
    )


def derived_signal_r(
    raw_to_derived: Callable[..., SignalDatatypeT],
    derived_units: str | None = None,
    derived_precision: int | None = None,
    **raw_devices: Device,
) -> SignalR[SignalDatatypeT]:
    creator = _make_creator(raw_to_derived=raw_to_derived, raw_devices=raw_devices)
    return creator.derived_signal_r(
        datatype=_get_return_datatype(raw_to_derived),
        name="value",
        units=derived_units,
        precision=derived_precision,
    )


def derived_signal_rw(
    raw_to_derived: Callable[..., SignalDatatypeT],
    set_derived: Callable[[SignalDatatypeT], AsyncStatus],
    derived_units: str | None = None,
    derived_precision: int | None = None,
    **raw_devices: Device,
) -> SignalRW[SignalDatatypeT]:
    raw_to_derived_datatype = _get_return_datatype(raw_to_derived)
    set_derived_datatype = _get_first_arg_datatype(set_derived)
    if raw_to_derived_datatype != set_derived_datatype:
        msg = (
            f"{raw_to_derived} has datatype {raw_to_derived_datatype} "
            f"!= {set_derived_datatype} dataype {set_derived_datatype}"
        )
        raise TypeError(msg)

    creator = _make_creator(
        raw_to_derived=raw_to_derived, set_derived=set_derived, raw_devices=raw_devices
    )
    return creator.derived_signal_rw(
        datatype=raw_to_derived_datatype,
        name="value",
        units=derived_units,
        precision=derived_precision,
    )


def derived_signal_w(
    set_derived: Callable[[SignalDatatypeT], AsyncStatus],
    derived_units: str | None = None,
    derived_precision: int | None = None,
) -> SignalW[SignalDatatypeT]:
    creator = _make_creator(set_derived=set_derived)
    return creator.derived_signal_w(
        datatype=_get_first_arg_datatype(set_derived),
        name="value",
        units=derived_units,
        precision=derived_precision,
    )
