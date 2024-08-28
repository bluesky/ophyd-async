from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Tuple, Type

import numpy as np


@dataclass
@dataclass
class ReadableDeviceConfig:
    int_signals: Dict[str, Tuple[int, Any]] = field(default_factory=dict)
    float_signals: Dict[str, Tuple[float, Any]] = field(default_factory=dict)
    str_signals: Dict[str, Tuple[str, Any]] = field(default_factory=dict)
    bool_signals: Dict[str, Tuple[bool, Any]] = field(default_factory=dict)
    list_signals: Dict[str, Tuple[list, Any]] = field(default_factory=dict)
    tuple_signals: Dict[str, Tuple[tuple, Any]] = field(default_factory=dict)
    dict_signals: Dict[str, Tuple[dict, Any]] = field(default_factory=dict)
    set_signals: Dict[str, Tuple[set, Any]] = field(default_factory=dict)
    frozenset_signals: Dict[str, Tuple[frozenset, Any]] = field(default_factory=dict)
    bytes_signals: Dict[str, Tuple[bytes, Any]] = field(default_factory=dict)
    bytearray_signals: Dict[str, Tuple[bytearray, Any]] = field(default_factory=dict)
    complex_signals: Dict[str, Tuple[complex, Any]] = field(default_factory=dict)
    none_signals: Dict[str, Tuple[type(None), Any]] = field(default_factory=dict)
    ndarray_signals: Dict[str, Tuple[np.ndarray, Any]] = field(default_factory=dict)
    signals: Dict[Type[Any], Dict[str, Tuple[Type[Any], Any]]] = field(init=False)

    def __post_init__(self):
        self.signals = {
            int: self.int_signals,
            float: self.float_signals,
            str: self.str_signals,
            bool: self.bool_signals,
            list: self.list_signals,
            tuple: self.tuple_signals,
            dict: self.dict_signals,
            set: self.set_signals,
            frozenset: self.frozenset_signals,
            bytes: self.bytes_signals,
            bytearray: self.bytearray_signals,
            complex: self.complex_signals,
            type(None): self.none_signals,
            np.ndarray: self.ndarray_signals,
        }
        self.attr_map = dict(self.signals.items())

    class SignalAccessor:
        def __init__(self, parent: "ReadableDeviceConfig", key: str):
            self.parent = parent
            self.key = key

        def __getitem__(self, dtype: Type[Any]) -> Any:
            signals = self.parent.signals.get(dtype)
            if signals and self.key in signals:
                return signals[self.key][1]
            raise AttributeError(
                f"'{self.parent.__class__.__name__}'"
                f" object has no attribute"
                f" '{self.key}[{dtype.__name__}]'"
            )

        def __setitem__(self, dtype: Type[Any], value: Any) -> None:
            signals = self.parent.signals.get(dtype)
            if signals and self.key in signals:
                expected_type, _ = signals[self.key]
                if isinstance(value, expected_type):
                    signals[self.key] = (expected_type, value)
                else:
                    raise TypeError(
                        f"Expected value of type {expected_type}"
                        f" for attribute '{self.key}', got {type(value)}"
                    )
            else:
                raise KeyError(
                    f"Key '{self.key}' not found" f" in {self.parent.attr_map[dtype]}"
                )

    def __getattr__(self, key: str) -> "ReadableDeviceConfig.SignalAccessor":
        return self.SignalAccessor(self, key)

    def add_attribute(self, name: str, dtype: Type[Any], value: Any) -> None:
        if not isinstance(value, dtype):
            raise TypeError(
                f"Expected value of type {dtype} for attribute"
                f" '{name}', got {type(value)}"
            )
        self.signals[dtype][name] = (dtype, value)

    def __setattr__(self, key: str, value: Any) -> None:
        if "attr_map" in self.__dict__:
            raise AttributeError(
                f"Cannot set attribute '{key}'"
                f" directly. Use 'add_attribute' method."
            )
        else:
            super().__setattr__(key, value)

    def __getitem__(self, key: str) -> "ReadableDeviceConfig.SignalAccessor":
        return self.SignalAccessor(self, key)

    def items(self):
        return asdict(self).items()
