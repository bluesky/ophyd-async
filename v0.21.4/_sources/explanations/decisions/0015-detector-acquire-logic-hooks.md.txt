# 15. Replace `DetectorArmLogic` with `DetectorAcquireLogic` and four lifecycle hooks

Date: 2026-04-29

## Status

Accepted

## Context

`DetectorArmLogic` had three abstract methods:

- `arm()` — start acquiring, called from `prepare()`, `kickoff()`, or `trigger()`
- `wait_for_idle()` — wait for idle after the final collection
- `disarm(on_unstage: bool)` — stop acquiring; the flag distinguished `stage()`
  (reset before a new scan) from `unstage()` (end-of-scan teardown)

The `on_unstage` flag was introduced in ADR 0014 to give implementations a way
to distinguish the two call sites, but the single method still forced those two
concerns into one place. More importantly, there was no hook at `stage()` time
that could perform *different* work from `unstage()`. A detector that should be
armed once at `stage()` and then triggered multiple times (e.g. an Eiger in
step-scan mode, or a continuously-acquiring detector) had no clean way to
express this; the closest workaround was to put the arm call inside `disarm`
and branch on `on_unstage`, which was confusing.

## Decision

`DetectorArmLogic` is renamed `DetectorAcquireLogic` and its interface is
replaced with four named hooks that map directly to the `StandardDetector`
lifecycle:

| Hook | Called from | Purpose |
|---|---|---|
| `ensure_ready()` | `stage()` | Put the detector into a known idle state before a scan. |
| `start_acquiring()` | `prepare()`, `kickoff()`, `trigger()` | Start the detector acquiring. |
| `wait_for_idle()` | after final collection | Wait for the detector to return to idle. |
| `ensure_stopped()` | `unstage()` | Stop the detector and perform end-of-scan cleanup. |

`ensure_ready` has a concrete default that delegates to `ensure_stopped`. This
is correct for the common case where stage-time reset and scan-end teardown are
identical (e.g. calling `stop_busy_record`). Subclasses that need different
behaviour at stage time (such as arming the detector once and keeping it armed
across multiple kickoff/complete cycles) override `ensure_ready` independently.

`AreaDetector.__init__` renames its `arm_logic` keyword argument to
`acquire_logic` for consistency.

## Consequences

All existing `DetectorArmLogic` subclasses must be updated:
- rename the base class to `DetectorAcquireLogic`
- rename `arm()` to `start_acquiring()`
- split `disarm(on_unstage)` into `ensure_stopped()` (and optionally override
  `ensure_ready()` if stage-time behaviour differs)

This is a clean breaking change; the library is in alpha and no compatibility
shim is provided.
