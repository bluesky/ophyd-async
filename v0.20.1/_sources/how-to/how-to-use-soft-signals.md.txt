# How to use soft signals

`SoftSignalBackend` provides a lightweight way to expose Python values and callables as ophyd-async signals, without implementing a full hardware backend. There are two broad usage patterns: **pure soft signals** (in-memory state only) and **callable-backed signals** (delegating to Python functions or coroutines).

---

## Case A: Pure soft signals (no callable)

**Use case**: a signal that holds a value in memory, with no hardware or external function involved. Useful for configuration parameters, simulated devices.

```python
from ophyd_async.core import soft_signal_rw

# A read/write float signal, default value 0.0
exposure_time = soft_signal_rw(float, initial_value=0.1, units="s")

# A read/write enum signal
from enum import Enum
class Mode(Enum):
    DARK = "dark"
    LIGHT = "light"

mode = soft_signal_rw(Mode, initial_value=Mode.DARK)
```

Reads always return the last value written. No polling or external calls occur.

## Case B: Single-value read/write with matching types

**Use Case**: A callable with a single argument where the input and output types match the signal's `SignalDatatypeT` (e.g., a motor position setter/getter).

**Approach**:
```python
def read_position() -> float:
    # returns current position
    ...
def move_to(position: float) -> float:
    # Move hardware and return actual position
    ...
motor_position = soft_signal_rw(
    float,
    setter=move_to,
    getter=read_position,
)
```
**Rationale**:
- Directly wrap the callable in a `SoftSignalBackend`-backed signal.
- Avoids the need for separate `Command` + `Signal` pairs when types align.
- Preserves type hints and integrates seamlessly with scans.

## Case C: Mismatched setter and getter types or multiple input types

**Use Case**: A callable where the input type differs from the output (e.g., sending a config object but receiving a string status).

```python
status = soft_signal_rw(str)

from ophyd_async.core import soft_command

async def configure_subsystem(*args, **kwargs) -> None:
    # Apply config...
    await status.set("configured")

config_cmd = soft_command(configure_subsystem)
await config_cmd.execute(...)
current_status = await status.get_value()
```
**Rationale**:
- Use a **`Command`** to handle the mismatched input/output types.
- Store the result in a separate `Signal` (here, `status`) for readability in plans.
- Ensures type safety: `Command` input (`MotorConfig`) and `Signal` output (`float`) remain distinct.

## Case D: Complex returns or multiple outputs

**Use Case**: A callable returning structured data (e.g., a diagnostic function yielding many metrics).

**Approach**:
```python
# Split outputs into individual signals
temp_signal = soft_signal_rw(float)
pressure_signal = soft_signal_rw(float)

def _diagnostics(): return 0.0, 1.0
async def run_diagnostics() -> None:
    temp, pressure = _diagnostics()
    await temp_signal.set(temp)
    await pressure_signal.set(pressure)
    
diagnostics_cmd = soft_command(run_diagnostics)
result = await diagnostics_cmd.execute()
temp = await temp_signal.read()
pressure = await pressure_signal.read()
```
**Rationale**:
- **Prefer splitting outputs** into discrete `Signal`s if they're independently useful.
- For ad-hoc use, a **`Command`** suffices, with manual extraction of results.
- Maintains separation of concerns: signals represent *state*, commands represent *actions*.

**Key Takeaways**:
1. **Prioritize `SoftSignalBackend` with callables** for simple, type-aligned read/write operations (Case B).
2. **Combine `Command` + `Signal`** when types diverge or actions yield secondary results (Cases C/D).
3. **Avoid overloading signals**: If a callable performs an action *and* returns data, model the action as a `Command` and the data as one or more `Signal`s.
4. **Polling**: Use `poll_period` in `SoftSignalBackend` for live updates (e.g., sensor readings), but ensure `getter` is lightweight.
