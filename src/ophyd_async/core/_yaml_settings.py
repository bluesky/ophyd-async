import warnings
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import yaml

from ._settings import SettingsProvider
from ._utils import ConfinedModel


def ndarray_representer(dumper: yaml.Dumper, array: npt.NDArray[Any]) -> yaml.Node:
    return dumper.represent_sequence(
        "tag:yaml.org,2002:seq", array.tolist(), flow_style=True
    )


def pydantic_model_abstraction_representer(
    dumper: yaml.Dumper, model: ConfinedModel
) -> yaml.Node:
    return dumper.represent_data(model.model_dump(mode="python"))


def enum_representer(dumper: yaml.Dumper, enum: Enum) -> yaml.Node:
    return dumper.represent_data(enum.value)


class YamlSettingsProvider(SettingsProvider):
    """For providing settings from yaml to signals."""

    def __init__(self, directory: Path | str):
        self._directory = Path(directory)

    def _file_path(self, name: str) -> Path:
        return self._directory / (name + ".yaml")

    async def store(self, name: str, data: dict[str, Any]):
        yaml.add_representer(np.ndarray, ndarray_representer, Dumper=yaml.Dumper)
        yaml.add_multi_representer(
            ConfinedModel,
            pydantic_model_abstraction_representer,
            Dumper=yaml.Dumper,
        )
        yaml.add_multi_representer(Enum, enum_representer, Dumper=yaml.Dumper)
        with open(self._file_path(name), "w") as file:
            yaml.dump(data, file)

    async def retrieve(self, name: str) -> dict[str, Any]:
        with open(self._file_path(name)) as file:
            data = yaml.full_load(file)
        if isinstance(data, list):
            warnings.warn(
                DeprecationWarning(
                    "Found old save file. Re-save your yaml settings file "
                    f"{self._file_path(name)} using "
                    "ophyd_async.plan_stubs.store_settings"
                ),
                stacklevel=2,
            )
            merge = {}
            for d in data:
                merge.update(d)
            return merge
        return data
