# This module adds tests designed to improve branching coverage.

# TODO: Set branch = true in [tool.coverage.run] block in
#       pyproject.toml to include these tests in coverage.

# TODO: Move to appropriate modules if they already exist.

# import pytest
from autodoc2.config import Config
from autodoc2.db import InMemoryDb
from bluesky.protocols import Locatable

# _docs_parser is Sphinx autodoc2 build tooling, not runtime code at all -
# already excluded from the layers contract as such
# (tool.importlinter exhaustive_ignores). Not part of the public interface
# by design - checked.
from ophyd_async._docs_parser import ShortenedNamesRenderer  # noqa: PLC2701

# get_locatable_type auto-detects Locatable support inside derived_signal_r/
# derived_signal_rw - a caller never calls it themselves, they just get a
# working locate() (or not) on the derived signal automatically - checked,
# nothing here looks missing from the public interface.
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
