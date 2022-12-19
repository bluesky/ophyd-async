from importlib.metadata import version

__version__ = version("ophyd-epics-devices")
del version

__all__ = ["__version__"]
