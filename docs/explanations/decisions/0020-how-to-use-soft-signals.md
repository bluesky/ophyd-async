# 20. How to use soft signals

The introduction of callable-backed `SoftSignalBackend` enables users to integrate non-EPICS/Tango systems (e.g., Python APIs, scripts, or custom hardware drivers) into ophyd-async without writing full `SignalBackend` implementations. Below are idiomatic patterns for common scenarios, balancing simplicity and type safety.

### **Case A: Single-Value Read/Write with Matching Types**
**Use Case**: A callable with a single argument where the input and output types match the signal’s `SignalDatatypeT` (e.g., a motor position setter/getter).
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

#### **Case B: Mismatched setter and getter types or multiple input types**
**Use Case**: A callable where the input type differs from the output (e.g., sending a config object but receiving a string status).

```python
status = soft_signal_rw(str)

def configure_subsystem(*args, **kwargs) -> None:
    # Apply config...
    await status.set("configured")

config_cmd = soft_command(configure_subsystem)

await config_cmd.execute(...)

current_status = await status.read()
```
**Rationale**:
- Use a **`Command`** to handle the mismatched input/output types.
- Store the result in a separate `Signal` (here, `status`) for readability in plans.
- Ensures type safety: `Command` input (`MotorConfig`) and `Signal` output (`float`) remain distinct.

#### **Case C: Complex returns or multiple outputs**
**Use Case**: A callable returning structured data (e.g., a diagnostic function yielding many metrics).
**Approach**:
```python
# Split outputs into individual signals
temp_signal = soft_signal_rw(float, getter=lambda: run_diagnostics()["temperature"])
pressure_signal = soft_signal_rw(float, getter=lambda: run_diagnostics()["pressure"])
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
- **Prefer splitting outputs** into discrete `Signal`s if they’re independently useful.
- For ad-hoc use, a **`Command`** suffices, with manual extraction of results.
- Maintains separation of concerns: signals represent *state*, commands represent *actions*.

**Key Takeaways**:
1. **Prioritize `SoftSignalBackend` with callables** for simple, type-aligned read/write operations (Case A).
2. **Combine `Command` + `Signal`** when types diverge or actions yield secondary results (Cases B/C).
3. **Avoid overloading signals**: If a callable performs an action *and* returns data, model the action as a `Command` and the data as one or more `Signal`s.
4. **Polling**: Use `poll_period` in `SoftSignalBackend` for live updates (e.g., sensor readings), but ensure `getter` is lightweight.
