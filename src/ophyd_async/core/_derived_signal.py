from collections.abc import Awaitable, Callable
from typing import Any, Generic, get_args, get_origin, get_type_hints, is_typeddict

from bluesky.protocols import Locatable

from ._derived_signal_backend import (
    DerivedSignalBackend,
    SignalTransformer,
    Transform,
    TransformT,
)
from ._device import Device
from ._signal import Signal, SignalR, SignalRW, SignalT, SignalW
from ._signal_backend import Primitive, SignalDatatypeT


class DerivedSignalFactory(Generic[TransformT]):
    """A factory that makes Derived Signals using a many-many Transform.

    :param transform_cls:
        The Transform subclass that will be filled in with parameters in order to
        transform raw to derived and derived to raw.
    :param set_derived:
        An optional async function that takes the output of
        `transform_cls.raw_to_derived` and applies it to the raw devices.
    :param raw_and_transform_devices_and_constants:
        Devices and Constants whose values will be passed as parameters
        to the `transform_cls`, and as arguments to `transform_cls.raw_to_derived`.
    """

    def __init__(
        self,
        transform_cls: type[TransformT],
        set_derived: Callable[..., Awaitable[None]] | None = None,
        **raw_and_transform_devices_and_constants,
    ):
        self._set_derived = set_derived
        _raw_and_transform_devices, _raw_and_transform_constants = (
            {
                k: v
                for k, v in raw_and_transform_devices_and_constants.items()
                if isinstance(v, Device)
            },
            {
                k: v
                for k, v in raw_and_transform_devices_and_constants.items()
                if isinstance(v, Primitive)
            },
        )

        # Check the raw and transform devices match the input arguments of the Transform
        if transform_cls is not Transform:
            # Populate expected parameters and types
            expected = {
                **{k: f.annotation for k, f in transform_cls.model_fields.items()},
                **{
                    k: v
                    for k, v in get_type_hints(transform_cls.raw_to_derived).items()
                    if k not in {"self", "return"}
                },
            }

            # Populate received parameters and types
            # Use Primitive's type, Signal's datatype,
            # Locatable's datatype, or set type as None
            received = {
                **{
                    k: v.datatype if isinstance(v, Signal) else get_locatable_type(v)
                    for k, v in _raw_and_transform_devices.items()
                },
                **{k: type(v) for k, v in _raw_and_transform_constants.items()},
            }

            if expected != received:
                msg = (
                    f"Expected the following to be passed as keyword arguments "
                    f"{expected}, got {received}"
                )
                raise TypeError(msg)
        self._set_derived_takes_dict = (
            is_typeddict(_get_first_arg_datatype(set_derived)) if set_derived else False
        )

        _raw_constants, _transform_constants = _partition_by_keys(
            _raw_and_transform_constants, set(transform_cls.model_fields)
        )

        _raw_devices, _transform_devices = _partition_by_keys(
            _raw_and_transform_devices, set(transform_cls.model_fields)
        )

        self._transformer = SignalTransformer(
            transform_cls,
            set_derived,
            self._set_derived_takes_dict,
            _raw_devices,
            _raw_constants,
            _transform_devices,
            _transform_constants,
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
        if issubclass(signal_cls, SignalRW) and self._set_derived_takes_dict:
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
    raw_devices_and_constants: dict[str, Device | Primitive] | None = None,
) -> DerivedSignalFactory:
    if raw_to_derived:

        class DerivedTransform(Transform):
            def raw_to_derived(self, **kwargs) -> dict[str, SignalDatatypeT]:
                return {"value": raw_to_derived(**kwargs)}

        # Update the signature for raw_to_derived to match what we are passed as this
        # will be checked in DerivedSignalFactory
        DerivedTransform.raw_to_derived.__annotations__ = get_type_hints(raw_to_derived)

        return DerivedSignalFactory(
            DerivedTransform,
            set_derived=set_derived,
            **(raw_devices_and_constants or {}),
        )
    else:
        return DerivedSignalFactory(Transform, set_derived=set_derived)


def derived_signal_r(
    raw_to_derived: Callable[..., SignalDatatypeT],
    derived_units: str | None = None,
    derived_precision: int | None = None,
    **raw_devices_and_constants: Device | Primitive,
) -> SignalR[SignalDatatypeT]:
    """Create a read only derived signal.

    :param raw_to_derived:
        A function that takes the raw values as individual keyword arguments and
        returns the derived value.
    :param derived_units: Engineering units for the derived signal
    :param derived_precision: Number of digits after the decimal place to display
    :param raw_devices_and_constants:
        A dictionary of Devices and Constants to provide the values for raw_to_derived.
        The names of these arguments must match the arguments of raw_to_derived.
    """
    factory = _make_factory(
        raw_to_derived=raw_to_derived,
        raw_devices_and_constants=raw_devices_and_constants,
    )
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
    **raw_devices_and_constants: Device | Primitive,
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
    :param raw_devices_and_constants:
        A dictionary of Devices and Constants to provide the values for raw_to_derived.
        The names of these arguments must match the arguments of raw_to_derived.
    """
    raw_to_derived_datatype = _get_return_datatype(raw_to_derived)
    set_derived_datatype = _get_first_arg_datatype(set_derived)
    if raw_to_derived_datatype != set_derived_datatype:
        msg = (
            f"{raw_to_derived} has datatype {raw_to_derived_datatype} "
            f"!= {set_derived_datatype} datatype {set_derived_datatype}"
        )
        raise TypeError(msg)

    factory = _make_factory(
        raw_to_derived=raw_to_derived,
        set_derived=set_derived,
        raw_devices_and_constants=raw_devices_and_constants,
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


def get_locatable_type(obj: object) -> type | None:
    """Extract datatype from Locatable parent class.

    :param obj: Object with possible Locatable inheritance
    :return: Type hint associated with Locatable, or None if not found.
    """
    for base in getattr(obj.__class__, "__orig_bases__", []):
        if get_origin(base) is Locatable:
            args = get_args(base)
            if args:
                return args[0]
    return None


def _partition_by_keys(data: dict, keys: set) -> tuple[dict, dict]:
    group_excluded, group_included = {}, {}
    for k, v in data.items():
        if k in keys:
            group_included[k] = v
        else:
            group_excluded[k] = v
    return group_excluded, group_included
