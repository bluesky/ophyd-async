# 21. One `logic` property per Device

Date: 2026-08-18

## Status

Accepted

Supersedes part of [](./0017-standard-movable.md), which introduced `movable_logic`.

## Context

A Device that both moves and flies had to expose the same logic object twice. `Motor`
built one `MotorFlyableMovableLogic` and returned it from a `movable_logic` property for
[](#StandardMovable) and a `flyable_logic` property for [](#StandardFlyable), plus a
private `_logic` to avoid building it twice. Every future mix-in would add another name.

The obstacle is that Python has no intersection type: there is no way to write "the logic
must be both a `MovableLogic[float]` and a `FlyableLogic[FlyMotorInfo, MotorFlyCtx]`" as a
single annotation.

[](./0017-standard-movable.md) also chose `@cached_property` stacked on `@abstractmethod` over an
`add_movable_logic()` method, on the grounds that the property is "checkable by static
analysis". That turned out not to hold. `functools.cached_property` does not forward
`__isabstractmethod__` from the function it wraps, so `StandardMovable.__abstractmethods__`
was empty, pyright reported nothing, and a Device that forgot its logic failed with
`AttributeError: 'NoneType' object has no attribute 'readback'` from inside
`Device.__init__`.

## Decision

Each mix-in declares the **same** attribute name, `logic`, with **its own**
required type:

```python
class StandardMovable(Device, ..., Generic[SignalDatatypeT]):
    @abstract_cached_property
    def logic(self) -> MovableLogic[SignalDatatypeT]: ...

class StandardFlyable(_StandardBase, ..., Generic[PrepareT, CtxT]):
    @abstract_cached_property
    def logic(self) -> FlyableLogic[PrepareT, CtxT]: ...
```

A Device inheriting both provides one implementation, and the type checker verifies it
against each base independently. The intersection is expressed by the logic class's own
MRO: `MotorFlyableMovableLogic` inherits both, so it satisfies both declarations, and the
concrete type is what callers see back.

This catches, at type-check time, a logic that satisfies one mix-in but not the other, a
wrong datatype parameter, and a Device with two mix-ins and no implementation. A Device
with a *single* mix-in and no implementation is caught at instantiation instead, by
`abstract_cached_property`, a `cached_property` that sets `__isabstractmethod__` on the
descriptor so that `Device`'s metaclass collects it. It is declared as returning
`cached_property[T]` rather than as a subclass, because a subclass breaks the covariance
check on the override and would reject the correct case too.

Because [](#StandardFlyable) is now genuinely abstract, `FlyableLogic.with_device` builds
a concrete `_EphemeralFlyable` to attach the logic to.

An alternative of a single `logics` collection searched by type was rejected: membership
cannot be proved statically, so it would reintroduce exactly the runtime-only failure
this change fixes.

## Consequences

- One property per Device however many mix-ins it combines; `Motor` loses two properties.
- Where the move and fly logic are genuinely unrelated implementations they must be
  combined into one class, since one property returns one object. Nothing in-tree pays
  this cost, as `MotorFlyableMovableLogic` was already that shape.
- Forgetting the logic now fails with `TypeError: Can't instantiate abstract class ...
  with abstract method logic` rather than an `AttributeError` on `None`.
- `movable_logic` and `flyable_logic` are removed rather than deprecated. A shim would
  only have helped code that *reads* the attribute: a subclass that still *defines*
  `movable_logic` would override the shim and leave `logic` unimplemented, so the
  Device would fail at instantiation anyway.
- The same mechanism is available to `StandardDetector` if it later inherits
  [](#StandardFlyable); its logic would need to satisfy `FlyableLogic` too.
