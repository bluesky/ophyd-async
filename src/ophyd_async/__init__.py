from importlib.metadata import version  # noqa

__version__ = version("ophyd-async")
del version

__all__ = ["__version__"]
