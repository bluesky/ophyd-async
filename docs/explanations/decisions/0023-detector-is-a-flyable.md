# 23. StandardDetector is a StandardFlyable

Date: 2026-08-28

## Status

Accepted

## Context

`StandardDetector` re-implemented `prepare`, `kickoff` and `complete` and threaded its own
state between them, while [](#StandardFlyable) already existed to do exactly that for every
other flyer in the tree (`Motor`, PMAC, the PandA trigger logics). Two implementations of
one lifecycle drift apart: the detector guarded its stages by checking whether a context
object was `None`, so calling a verb too early failed with `AttributeError: 'NoneType'
object has no attribute ...` rather than saying what was wrong.

`StandardFlyable` requires a single [](#FlyableLogic) in a `logic` property
([](./0021-single-logic-property.md)), and a detector had three logic objects registered on
the Device by `add_detector_logics()`.

## Decision

### The three logics become children of one `DetectorLogic`

[](#DetectorLogic) holds the trigger, acquire and data logics, and is what `logic` returns.
The orchestration moves with them: preparing the trigger logic, making the data providers,
arming, and waiting for collections are all its methods now. It holds **no** back-reference
to its Device, so [](./0017-standard-movable.md) continues to hold unqualified.

A detector builds it in `__init__` and returns it from `logic`:

```python
class MyDetector(StandardDetector):
    def __init__(self, prefix: str, name: str = "") -> None:
        self.driver = MyDriverIO(prefix)
        self._logic = DetectorLogic(
            MyTriggerLogic(self.driver),
            MyAcquireLogic(self.driver),
        )
        super().__init__(name=name)

    @cached_property
    def logic(self) -> DetectorLogic:
        return self._logic
```

`add_detector_logics()` is removed rather than kept as a forwarder: a detector's logics are
fixed for its lifetime, so there is nothing a post-construction call can do that the
constructor cannot, and keeping it would leave two ways to wire the same Device.

`StandardDetector` itself takes no `__init__` arguments, since a `Standard*` class that did
would interfere with multiple inheritance. The logic is supplied by overriding `logic`,
which `abstract_cached_property` makes a requirement checked when the Device is
instantiated. Assigning `self.logic` from `__init__` cannot serve instead: `ABCMeta` checks
`__abstractmethods__` in `__call__`, before `__init__` runs, so the class must override the
property to be concrete. For an ad-hoc detector in a plan or a test,
`DetectorLogic.with_device()` builds a Device around a logic, exactly as
`FlyableLogic.with_device()` does for any other flyer.

### One thing the logic cannot get from its own fields

Data logics name their datakeys after the Device, whose name does not exist until
`init_devices` calls `set_name` on context exit. `StandardDetector.set_name` pushes it into
`DetectorLogic.datakey_prefix` — one string, set at the moment it exists, rather than a
reference to the whole Device.

### Which collect verb to expose is the Device's business

A detector produces stream assets or event pages depending on what its data logics make for
a given scan, never both (see [](./0022-bounded-data-logic-tier.md)). The bluesky bundler
decides which to ask for from the *static* type — `collect_pages()` is called only on a
device that is not a `WritesStreamAssets` — so a detector that declared both would have its
pages silently dropped, and one that declared neither could not fly at all.

So `StandardDetector.prepare()` and `trigger()` bind whichever verb applies as a real
instance attribute, and remove the other. It is the Device that does this, from what
`DetectorLogic.data` holds after preparing; the logic reports what it made and is not told
where that goes, so it holds no back-reference.

Choosing from the static type is a bundler limitation rather than a fact about detectors: a
device knows what it produced, and the bundler could decide from *that*, erroring only if
one device reported both ways in the same run. That change is a few lines in
`RunBundler.collect`, and with it both verbs become plain methods and the binding here goes
away. Until it is released, binding per prepare is what works against a released bluesky.

### Mixing bounded and unbounded is an error unless the bounded keys are shadowed

[](./0022-bounded-data-logic-tier.md) made carrying both kinds of data logic an error, because
the bundler treats stream assets and event pages as mutually exclusive. Carrying both is still
useful, though: the same quantity can be written durably into a file *and* read from a plugin's
buffer — an areaDetector stats total, which the HDF writer pulls in as an NDAttribute.

So the rule relaxes. Where **every** datakey a finite buffer would produce is also produced
by the stream assets, the durable copy wins and the buffer sits the scan out, unarmed.
Anything a buffer would produce that the file does not cover is still an error, naming the
uncovered keys. Nothing has been started when that is decided, because
`make_data_provider` describes without acquiring (same ADR).

### A logic may report its own progress

`StandardFlyable.complete()` could produce `WatcherUpdate`s only for a `MovableLogic`, by
observing its readback against its setpoint. A detector's progress is "collections written
out of collections requested", which is neither, so a detector inheriting the base
`complete()` would have silently lost its progress reporting.

So `FlyableLogic.on_complete` returns either an `Awaitable[None]` or an
`AsyncIterator[WatcherUpdate]`, and `complete()` looks at what it got back: an iterator is
yielded straight on to watchers, anything else is awaited. A logic that only blocks stays an
ordinary `async def`. A separate `WatchableFlyableLogic` base was tried first and dropped:
it made a second class to inherit for what is a property of one method's return.

### One kickoff per prepare

The detector used to be prepared for N events and kicked off a few at a time, with an
`events_to_kickoff` signal saying how many the next kickoff covered and an `is_last_kickoff`
flag deciding when to wait for idle. Nothing in tree drove it: the RunEngine kicks off once
and completes what it kicked off, and every other flyer already worked that way.

Both go, and `kickoff()` requests the whole prepared scan. A second `kickoff()` without an
intervening `prepare()` now raises, from `StandardFlyable`, like any other flyer.

### The data providers are the logic's state, not the fly context's

`_FlyCtx` holds what `prepare()` was given — the `TriggerInfo` — plus the collections
baseline `kickoff()` took, and nothing else. The providers live on the logic instead,
because they outlive a single prepare → kickoff → complete cycle in two ways: a step scan
reuses an open file across its points, and `collect_while_completing` collects *after*
`complete()` has returned the flyer to IDLE. So the data verbs — `read`, `describe`,
`describe_collect`, `collect_asset_docs`, `collect_pages`, `get_index` — go through
`DetectorLogic.data`, which is cleared by `stage()`/`unstage()`, while the fly context
enforces the ordering of the fly verbs.

`trigger()` therefore needs no context of its own. It prepares implicitly if nothing has
been, then asks the data state to re-arm what needs re-arming: a finite buffer holds one
event at a time so it is re-made per point, while a streaming provider carries on. The
trigger logic is not re-prepared per point, so a step scan does not repeat its puts.

## Consequences

- `StandardDetector` subclasses build a `DetectorLogic` in `__init__` and return it from
  `logic`; `det.add_detector_logics(*logics)` is gone, and a logic conflict is reported when
  the detector is constructed rather than at the `add` call.
- `kickoff()` → `kickoff()` without an intervening `complete()` is rejected, and so is a
  second `kickoff()` after one. The old detector allowed both, because it only checked that
  a prepare context existed.
- `events_to_kickoff` is removed from the public API.
- Calling a verb before `prepare()` says `<name>: prepare() must be called first` instead of
  `Prepare not run`.
- A detector satisfies neither `WritesStreamAssets` nor `EventPageCollectable` until it has
  been prepared. Everything in the RunEngine that dispatches on them runs after prepare.
- `prepare`, `kickoff`, `complete`, `stage` and `unstage` are no longer implemented on
  `StandardDetector` at all, so a change to the flyer lifecycle reaches detectors too.
