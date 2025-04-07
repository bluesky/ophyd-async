from collections.abc import Awaitable, Callable
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


class DerivedSignalFactory(Generic[TransformT]):
    """A factory that makes Derived Signals using a many-many Transform.

    :param transform_cls:
        The Transform subclass that will be filled in with parameters in order to
        transform raw to derived and derived to raw.
    :param set_derived:
        An optional async function that takes the output of
        `transform_cls.raw_to_derived` and applies it to the raw devices.
    :param raw_and_transform_devices:
        Devices whose values will be passed as parameters to the `transform_cls`,
        and as arguments to `transform_cls.raw_to_derived`.
    """

    def __init__(
        self,
        transform_cls: type[TransformT],
        set_derived: Callable[..., Awaitable[None]] | None = None,
        **raw_and_transform_devices,
    ):
        self._set_derived = set_derived
        # Check the raw and transform devices match the input arguments of the Transform
        if transform_cls is not Transform:
            expected = {
                k: v
                for k, v in get_type_hints(transform_cls.raw_to_derived).items()
                if k not in {"self", "return"}
            }

            received = {k: v.datatype for k, v in raw_and_transform_devices.items()}

            if expected != received:
                msg = (
                    f"Expected devices to be passed as keyword arguments "
                    f"{expected}, got {received}"
                )
                raise TypeError(msg)

        set_derived_datatype = (
            _get_first_arg_datatype(set_derived) if set_derived else None
        )
        self._transformer = SignalTransformer(
            transform_cls,
            set_derived,
            set_derived_datatype,
            **raw_and_transform_devices,
        )

    def _make_signal(
        self,
        signal_cls: type[SignalT],
        datatype: type[SignalDatatypeT],
        name: str,
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
        backend = DerivedSignalBackend(
            datatype, name, self._transformer, units, precision
        )
        return signal_cls(backend)

    def derived_signal_r(
        self,
        datatype: type[SignalDatatypeT],
        name: str,
        units: str | None = None,
        precision: int | None = None,
    ) -> SignalR[SignalDatatypeT]:
        """Create a read only derived signal.

        :param datatype: The datatype of the derived signal value
        :param name:
            The name of the derived signal. Should be a key within the
            return value of `transform_cls.raw_to_derived()`.
        :param units: Engineering units for the derived signal
        :param precision: Number of digits after the decimal place to display
        """
        return self._make_signal(SignalR, datatype, name, units, precision)

    def derived_signal_w(
        self,
        datatype: type[SignalDatatypeT],
        name: str,
        units: str | None = None,
        precision: int | None = None,
    ) -> SignalW[SignalDatatypeT]:
        """Create a write only derived signal.

        :param datatype: The datatype of the derived signal value
        :param name:
            The name of the derived signal. Should be a key within the
            return value of `transform_cls.raw_to_derived()`.
        :param units: Engineering units for the derived signal
        :param precision: Number of digits after the decimal place to display
        """
        return self._make_signal(SignalW, datatype, name, units, precision)

    def derived_signal_rw(
        self,
        datatype: type[SignalDatatypeT],
        name: str,
        units: str | None = None,
        precision: int | None = None,
    ) -> SignalRW[SignalDatatypeT]:
        """Create a read-write derived signal.

        :param datatype: The datatype of the derived signal value
        :param name:
            The name of the derived signal. Should be a key within the
            return value of `transform_cls.raw_to_derived()`.
        :param units: Engineering units for the derived signal
        :param precision: Number of digits after the decimal place to display
        """
        return self._make_signal(SignalRW, datatype, name, units, precision)

    async def transform(self) -> TransformT:
        """Return an instance of `transform_cls` with all the parameters filled in."""
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


def _make_factory(
    raw_to_derived: Callable[..., SignalDatatypeT] | None = None,
    set_derived: Callable[[SignalDatatypeT], Awaitable[None]] | None = None,
    raw_devices: dict[str, Device] | None = None,
) -> DerivedSignalFactory:
    if raw_to_derived:

        class DerivedTransform(Transform):
            def raw_to_derived(self, **kwargs) -> dict[str, SignalDatatypeT]:
                return {"value": raw_to_derived(**kwargs)}

        # Update the signature for raw_to_derived to match what we are passed as this
        # will be checked in DerivedSignalFactory
        DerivedTransform.raw_to_derived.__annotations__ = get_type_hints(raw_to_derived)

        return DerivedSignalFactory(
            DerivedTransform, set_derived=set_derived, **(raw_devices or {})
        )
    else:
        return DerivedSignalFactory(Transform, set_derived=set_derived)


def derived_signal_r(
    raw_to_derived: Callable[..., SignalDatatypeT],
    derived_units: str | None = None,
    derived_precision: int | None = None,
    **raw_devices: Device,
) -> SignalR[SignalDatatypeT]:
    """Create a read only derived signal.

    :param raw_to_derived:
        A function that takes the raw values as individual keyword arguments and
        returns the derived value.
    :param derived_units: Engineering units for the derived signal
    :param derived_precision: Number of digits after the decimal place to display
    :param raw_devices:
        A dictionary of Devices to provide the values for raw_to_derived. The names
        of these arguments must match the arguments of raw_to_derived.
    """
    factory = _make_factory(raw_to_derived=raw_to_derived, raw_devices=raw_devices)
    return factory.derived_signal_r(
        datatype=_get_return_datatype(raw_to_derived),
        name="value",
        units=derived_units,
        precision=derived_precision,
    )


def derived_signal_rw(
    raw_to_derived: Callable[..., SignalDatatypeT],
    set_derived: Callable[[SignalDatatypeT], Awaitable[None]],
    derived_units: str | None = None,
    derived_precision: int | None = None,
    **raw_devices: Device,
) -> SignalRW[SignalDatatypeT]:
    """Create a read-write derived signal.

    :param raw_to_derived:
        A function that takes the raw values as individual keyword arguments and
        returns the derived value.
    :param set_derived:
        A function that takes the derived value and sets the raw signals. It can
        either be an async function, or return an [](#AsyncStatus)
    :param derived_units: Engineering units for the derived signal
    :param derived_precision: Number of digits after the decimal place to display
    :param raw_devices:
        A dictionary of Devices to provide the values for raw_to_derived. The names
        of these arguments must match the arguments of raw_to_derived.
    """
    raw_to_derived_datatype = _get_return_datatype(raw_to_derived)
    set_derived_datatype = _get_first_arg_datatype(set_derived)
    if raw_to_derived_datatype != set_derived_datatype:
        msg = (
            f"{raw_to_derived} has datatype {raw_to_derived_datatype} "
            f"!= {set_derived_datatype} dataype {set_derived_datatype}"
        )
        raise TypeError(msg)

    factory = _make_factory(
        raw_to_derived=raw_to_derived, set_derived=set_derived, raw_devices=raw_devices
    )
    return factory.derived_signal_rw(
        datatype=raw_to_derived_datatype,
        name="value",
        units=derived_units,
        precision=derived_precision,
    )


def derived_signal_w(
    set_derived: Callable[[SignalDatatypeT], Awaitable[None]],
    derived_units: str | None = None,
    derived_precision: int | None = None,
) -> SignalW[SignalDatatypeT]:
    """Create a write only derived signal.

    :param set_derived:
        A function that takes the derived value and sets the raw signals. It can
        either be an async function, or return an [](#AsyncStatus)
    :param derived_units: Engineering units for the derived signal
    :param derived_precision: Number of digits after the decimal place to display
    """
    factory = _make_factory(set_derived=set_derived)
    return factory.derived_signal_w(
        datatype=_get_first_arg_datatype(set_derived),
        name="value",
        units=derived_units,
        precision=derived_precision,
    )
