# 19. SoftSignalBackend Wrapping Arbitrary Callables

## **Status**
Accepted


## **Context**
Users working outside of EPICS/Tango ecosystems such as those wrapping third-party Python APIs, calling analysis scripts, or interfacing with devices with their own Python drivers, currently have no supported path to create signals without writing a full custom `SignalBackend`. This was identified as a friction point for smaller lab-based groups during the Bluesky community workshop.

To address this, `SoftSignalBackend` was extended to support arbitrary callables for getting, setting, and polling values. This allows users to integrate external systems without implementing a full backend, reducing boilerplate and improving usability.

## **Decision**

### **Extend `SoftSignalBackend` with Callable Support**
`SoftSignalBackend` was augmented with three new **keyword-only** parameters:
1. **`getter`**: A callable (`Callable[[], T | Awaitable[T]]`) invoked during `get_value()` and `get_reading()` to fetch the current value from an external source. If `poll_period` is set, the `getter` is called periodically while a subscription is active.
2. **`setter`**: A callable (`Callable[[SignalDatatypeT], SignalDatatypeT | None | Awaitable[SignalDatatypeT | None]]`) invoked during `put()`. It may return a `SignalDatatypeT`; if it returns `None`, the `getter` (if configured) is called immediately to refresh the cache.
3. **`poll_period`**: A float representing the interval (in seconds) at which the `getter` is polled while a subscription is active. Requires `getter` to be set.

### **Design Choices**
- All three parameters are **optional**. If none are provided, behavior remains identical to the existing `SoftSignalBackend`.
- The internal `self._reading` store remains the **single source of truth**. The `getter` updates this store rather than bypassing it, preserving coherence for subscriptions and cached reads.
- The `put` method accepts `SignalDatatypeT` (the same type as the signal's stored value) to maintain type safety and consistency.
- Polling tasks are used for subscriptions, starting in `set_callback` and canceling when subscriptions end.
- `get_setpoint()` **does not invoke the `getter`**; it returns the last value written to the `setter` or the initial value of.

### **Factory Function Updates**
The convenience functions `soft_signal_rw` and `soft_signal_r_and_setter` were updated to accept `getter`, and `poll_period` arguments. `soft_signal_rw` additionally accepts a `setter` argument. These additional arguments are passed to `SoftSignalBackend`.

## **Consequences**
**Improved Usability**:
   Non-EPICS/Tango users can now easily integrate external systems (e.g., Python APIs, scripts) without writing full backends.

**No Breaking Changes**:
   Existing code continues to work unchanged since all new parameters are optional.

**Consistent Behavior**:
   Polling, caching, and subscriptions align with EPICS/Tango backend patterns.
