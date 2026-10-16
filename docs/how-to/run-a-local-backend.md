# Run against a real, locally-installed backend

Most of this repo's tutorials and tests spin a backend up and tear it down
automatically, hidden behind a fixture or a demo script. Sometimes it's more
useful to run a genuine `softIoc` or Tango device server yourself in one
terminal, and connect to it with `ophyd-async` from a second terminal's
[ipython](https://ipython.org) session -- for example when reproducing an
issue, or exploring `get_value()`/`set()` against real network traffic rather
than a mocked backend.

This guide uses the fixed test-only backends that `ophyd-async` itself ships
for its own system tests. They're plain scripts with a `__main__` entry
point that (deliberately) don't import anything from `ophyd_async` -- so the
terminal hosting the backend can be a bare EPICS or PyTango install with no
`ophyd-async` package at all, exactly as a real IOC or device server would be
in production. The second terminal is where the `ophyd-async` client-side
code lives; it needs a full `ophyd-async` install.

No git clone is needed for either terminal -- everything below works against
a plain `pip install`.

## Install `ophyd-async`

The second (client) terminal needs `ophyd-async` plus the extra for whichever
transport you're using, and `ipython` to drive it interactively:

::::{tab-set}
:sync-group: cs

:::{tab-item} EPICS
:sync: epics
```
$ python3 -m pip install ophyd-async[ca,pva,demo]
```
:::

:::{tab-item} Tango
:sync: tango
```
$ python3 -m pip install ophyd-async[tango,demo]
```
:::

::::

```{note}
The `demo` extra is what pulls in `ipython` here -- but it also happens to be
the only extra that installs `pytest`. That matters more than it looks:
constructing *any* Device from `ophyd_async.epics.testing` or
`ophyd_async.tango.testing` (not just calling an assert helper) transitively
imports `ophyd_async.testing`, whose `__init__.py` imports `pytest` at module
level. Installing only `ophyd-async[ca]` (or `[pva]`/`[tango]`) will get you
an `ImportError` for `pytest` the moment you construct one of these testing
Devices below -- `demo` (or installing `pytest` yourself) avoids it.
```

## Start the backend

Do this in a first terminal. See [](../tutorials/installation.md) if this
terminal needs its own from-scratch EPICS or PyTango environment.

::::{tab-set}
:sync-group: cs

:::{tab-item} EPICS
:sync: epics

`ophyd_async.epics.testing` ships a standalone IOC-launcher script
(`_ioc.py`) that depends on nothing but the standard library, plus whichever
executable ends up hosting the IOC database. Resolve its path with any
Python that has `ophyd-async` installed, and run it with a PV prefix of your
choosing, e.g. `example:`:

```
$ python "$(python -c 'from ophyd_async.epics.testing import IOC; print(IOC)')" example:
```

By default it hosts the database with the bundled `epicscorelibs.ioc`
module, so the command above works with nothing installed beyond
`ophyd-async[ca,pva]` -- no separate EPICS install required. It serves
`ca:`, `pva:` and `nested:` sub-topologies under the prefix you gave it, so
with `example:` above, PVs live under `example:ca:`, `example:pva:` and
`example:nested:`.

Leave this terminal running -- the IOC exits when its stdin closes (Ctrl-D).

```{note}
If your site already has a real EPICS installation with its own `softIoc`
binary on `PATH`, use that instead of the bundled one with `--softioc`:

    $ python "$(python -c 'from ophyd_async.epics.testing import IOC; print(IOC)')" example: --softioc softIoc

This is the more realistic scenario if EPICS is already installed
system-wide rather than only pulled in as a Python dependency.
```

:::

:::{tab-item} Tango
:sync: tango

`ophyd_async.tango.testing` ships a standalone device-server script
(`_tango_device_servers.py`) that depends on nothing but `tango`/
`tango.server`, numpy and the standard library -- no `ophyd_async` import at
all. It takes a device-name prefix and a TCP port, and serves two devices
with no Tango database needed: `TestDevice` at `<prefix>/basic` and
`OneOfEverythingTangoDevice` at `<prefix>/everything`.

```
$ python "$(python -c 'from ophyd_async.tango.testing import DEVICE_SERVERS; print(DEVICE_SERVERS)')" test/example 12345
```

It prints a `TANGO_DEVICE_SERVERS_READY` marker once serving, then blocks
until its stdin closes (Ctrl-D) -- leave this terminal running.

```{note}
Because the script is standalone, you can run the exact same file under a
*different* PyTango installation's interpreter -- e.g. a separate venv with a
different PyTango version than the one `pip install ophyd-async[tango]`
gave you. Resolve the path with a Python that has `ophyd-async` installed
(as above), then hand that path to the other venv's interpreter instead:

    $ /path/to/other/tango-venv/bin/python "$(python -c 'from ophyd_async.tango.testing import DEVICE_SERVERS; print(DEVICE_SERVERS)')" test/example 12345

This is the realistic scenario for testing against a site's own,
already-installed PyTango stack.
```

:::

::::

## Connect from a client session

In the second terminal, start `ipython` and construct the matching testing
Device against the same prefix/port you gave the backend above:

::::{tab-set}
:sync-group: cs

:::{tab-item} EPICS
:sync: epics

```
$ ipython
```

```python
In [1]: from ophyd_async.epics.testing import EpicsTestCaDevice, EpicsTestPvaDevice

In [2]: ca_device = EpicsTestCaDevice("ca://example:ca:")

In [3]: pva_device = EpicsTestPvaDevice("pva://example:pva:")

In [4]: await ca_device.connect()

In [5]: await pva_device.connect()

In [6]: await ca_device.a_int.get_value()
Out[6]: 0

In [7]: await pva_device.a_int.get_value()
Out[7]: 0
```

`a_int` round-trips against the live IOC's `example:ca:int`/`example:pva:int`
records -- it defaults to `0` because the underlying `.db` doesn't set an
initial `VAL`. Try `await ca_device.a_int.set(5)`, then `get_value()` it
again from either device, to see this is a genuine round trip over the
network rather than a mocked value.

:::

:::{tab-item} Tango
:sync: tango

```
$ ipython
```

```python
In [1]: from ophyd_async.tango.testing import TangoTestDevice

In [2]: device = TangoTestDevice("tango://127.0.0.1:12345/test/example/everything#dbase=no")

In [3]: await device.connect()

In [4]: await device.a_str.get_value()
Out[4]: 'test_string'
```

`a_str` round-trips against the live `OneOfEverythingTangoDevice` server's
`a_str` attribute, which defaults to `"test_string"`. Try
`await device.a_str.set("hello")`, then `get_value()` it again, to see this
is a genuine round trip rather than a mocked value.

:::

::::

```{seealso}
[](../how-to/interact-with-signals.md) for more on `get_value()`/`set()` and
the other ways to interact with Signals and Commands once connected.
```
