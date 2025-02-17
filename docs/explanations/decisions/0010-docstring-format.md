# 10. Decide on docstring format

Date: 2025-02-13

## Status

Accepted

## Context

After spending 2 weeks with sphinx autodoc and autosummary I have failed to get it to document typevars properly, which means a bunch of unclickable links in the docs everytime you write `SignalDatatypeT`. This is annoying as it happens in hundreds of places, and the user generally would like to know at this point "which datatypes could I pass here?" so really needs that link.

To fix, we could:
1. Manually link to the datatypes documentation in every docstring
2. [Fix autodoc](https://github.com/sphinx-doc/sphinx/pull/13277)
3. Switch to [`sphinx-autodoc2`](https://github.com/sphinx-extensions2/sphinx-autodoc2)

I think 1. is too manual and error prone, I failed at 2. after 2 days of hacking, so I suggest 3.

It is almost working, but there is one decision to make, what format should the docstrings be?

Given that prose documents are written in markdown and look like this:
```md
# Connecting the Device
Rather than calling [](#Device.connect) yourself which would use the wrong event loop you can 
use [](#init_devices) at startup or the equivalent [plan stub](#ensure_connected). Remember to 
pass `mock=True` during testing.
```
We can either write the docstring in markdown or RST, and we can format the arguments using param list, google style or numpy style. I've included a sample docstring below that we can comment on:

## Numpy style with RST links
```python
    def create_devices_from_annotations(
        self,
        filled=True,
    ) -> Iterator[tuple[DeviceConnectorT, list[Any]]]:
        """Create all Signals from annotations

        Parameters
        ----------
        filled
            If ``True`` then the Devices created should be considered already filled
            with connection data. If ``False`` then `fill_child_device` needs
            calling at parent device connection time before the child `Device` can
            be connected.

        Yields
        ------
        (connector, extras):
            The `DeviceConnector` that has been created for this Signal, and the list of
            extra annotations that could be used to customize it.
        """
```
## Google style with RST links
```python
    def create_devices_from_annotations(
        self,
        filled=True,
    ) -> Iterator[tuple[DeviceConnectorT, list[Any]]]:
        """Create all Signals from annotations

        Args:
            filled: If ``True`` then the Devices created should be considered
                already filled with connection data. If ``False`` then
                `fill_child_device` needs calling at parent device connection
                time before the child `Device` can be connected.

        Yields:
            (connector, extras): The `DeviceConnector` that has been created for this
                Signal, and the list of extra annotations that could be used to
                customize it.
        """
```
## Param list with markdown links
```python
    def create_devices_from_annotations(
        self,
        filled=True,
    ) -> Iterator[tuple[DeviceConnectorT, list[Any]]]:
        """Create all Signals from annotations

        :param filled: If `True` then the Devices created should be considered
            already filled with connection data. If `False` then
            [](#fill_child_device) needs calling at parent device connection
            time before the child [](#Device) can be connected.

        :yields: `(connector, extras)`: the [](#DeviceConnector) that has been
            created for this Signal, and the list of extra annotations that
            could be used to customize it.
        """
```

Or any combination of the above.

## Decision

We decided that markdown links are better as there is only one style of linking within the code base, and that param lists are the least amount of work to support as sphinx-autodoc2 already supports them.

## Consequences

We will update the docstrings in the whole codebase to match this convention and add ruff rules to ensure docstrings are written.
