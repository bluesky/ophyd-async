# 18. Typed Command to replace SignalX

Date: 2026-04-10

## Status

Accepted

## Context

`SignalX` was the existing mechanism for triggering hardware actions with no input and no return
value.  It was implemented as a thin wrapper around `SignalBackend` — the wrong base class:
a command is not a readable signal and has no `get`/`subscribe` semantics.  More importantly,
`SignalX` could never represent typed commands (those taking arguments or returning values),
which are needed for Tango device commands and future EPICS PVA RPC support.

## Decision

### `Command` extends `Device`, not a separate hierarchy

`Device` already provides named tree nodes, parent/child traversal, connection lifecycle, logging,
and the entire mock infrastructure.  As a `Device` subclass, commands are discovered by
`DeviceFiller` annotation scanning automatically, appear in device trees, and participate in mock
mode without extra machinery.

### `TriggerableCommand` is a separate subclass, not a conditional method on `Command`

`Command[P, T].execute()` returns `AsyncStatus[T]` — a typed remote procedure call.
`TriggerableCommand.trigger()` returns `AsyncStatus[None]` and satisfies the bluesky
`Triggerable` protocol used by scan machinery.

These are distinct protocols consumed by distinct callers: a `StandardDetector` trigger loop calls
`.trigger()` and assumes `Triggerable`; a user invoking a typed command calls `.execute()` and
expects a typed return.  They cannot be merged onto one class: putting `trigger()` on `Command`
would force every `Command[int, float]` author to decide what `trigger()` means, and making it
conditional on `P == []` cannot be expressed in Python's type system.  `TriggerableCommand` is a
concrete subclass that resolves this cleanly: only void/void commands satisfy `Triggerable`.

### `SignalX` is deprecated, not removed

`SignalX` is widely used in existing deployed device code.  Removing it would silently break user
devices on upgrade.  A `DeprecationWarning` guides migration to `TriggerableCommand` while
preserving backward compatibility.

### EPICS is intentionally restricted to void/void commands

CA has no native typed RPC mechanism; the conventional trigger is a plain `caput` to an integer
PROC field.  PVA has an RPC mechanism in principle but it is not yet standardized enough for
production device code.  Annotating a typed `Command[int, float]` on an EPICS device raises
`TypeError` at device-construction time; the alternative — silently ignoring the type parameters
— would let the command appear to work but drop its arguments at runtime.

`CaCommandBackend.connect()` additionally rejects float and double DBR types intentionally:
PROC fields on process records are always integer-typed, so a float PV indicates the wrong record
being used as a trigger rather than a signal.

### Concurrent `SoftCommandBackend` calls are serialised, not rejected

An `asyncio.Lock` ensures a second concurrent `execute()` call waits for the first to complete
rather than running alongside it.  This matches the exclusive-access semantics expected for
hardware commands.  Raising on concurrent access would transfer the locking responsibility to
every caller.

### Mock mode calls the original `SoftCommandBackend` function by default

When a `soft_command` device is connected in mock mode, `MockCommandBackend` calls the original
Python callable by default, so tests see the same side effects and return values as production
without any extra setup.  This is parallel to `MockSignalBackend`, which has the same behavior in real and mock mode of storing the supplied value.

Use `callback_on_mock_execute` to
suppress the original function for tests that need to isolate the caller from the callee.

## Consequences

- `SignalX` is retained but deprecated; existing code continues to work.
- Typed `Command[P, T]` on an EPICS device raises `TypeError` at construction.
- EPICS CA command PVs must be integer scalar types; float PVs raise `TypeError` at connect.
- PVA RPC with typed arguments is deferred to a future PR via a `call_spec` field on
  `PvaCommandBackend`.
