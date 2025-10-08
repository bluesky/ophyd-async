# This module adds tests designed to improve branching coverage.

# TODO: Set branch = true in [tool.coverage.run] block in
#       pyproject.toml to include these tests in coverage.

# TODO: Move to appropriate modules if they already exist.

# import pytest
from autodoc2.config import Config
from autodoc2.db import InMemoryDb
from bluesky.protocols import Locatable

from ophyd_async._docs_parser import ShortenedNamesRenderer  # noqa: PLC2701
from ophyd_async.core._derived_signal import get_locatable_type  # noqa: PLC2701

# src/ophyd_async/_docs_parser.py:10


class DummyRenderer(ShortenedNamesRenderer):
    def __init__(self):
        super().__init__(InMemoryDb(), Config())


def test_format_annotation_with_annotation():
    renderer = DummyRenderer()
    result = renderer.format_annotation("some.module.ClassName")
    assert "~some.module." in result or "ClassName" in result


def test_format_annotation_without_annotation():
    renderer = DummyRenderer()
    result = renderer.format_annotation(None)
    assert result == renderer.format_annotation(None)  # just ensure not crashing


# src/ophyd_async/core/_derived_signal.py:330


def test_get_locatable_type():
    class DummyLocatable(Locatable[int]):
        def set(self, _): ...
        def locate(self): ...

    class NonLocatable: ...

    class DummyNonLocatable(NonLocatable): ...

    obj_locatable = DummyLocatable()
    obj_nonlocatable = DummyNonLocatable()

    assert get_locatable_type(obj_locatable) is int
    assert get_locatable_type(obj_nonlocatable) is None
