
Bluesky Acquisition Control Verbs
================================

This document explains the sequence and role of Bluesky device methods used during an acquisition plan, especially in the context of flyscans and step scans. It includes a mnemonic, a Mermaid.js diagram of the valid process flow, and a flowchart for common ordering errors.

Method Reference
----------------

### `stage`

Make the device ready for data collection (e.g., reserving resources).

### `open_run`

Start the run context. This allows run hooks like filename generation to be used.

### `prepare`

Prepares the device for acquisition. This includes:

- Setting parameters such as exposure time, number of frames (for detectors), or motion extents and run-up position (for motors).
- Arming detectors if hardware-triggered.

> Must be called **after `open_run`** to ensure hooks are active.

### `set`

Set the device to a target setpoint. Used in software-driven step scans.

### `trigger`

Ask the detector to take a measurement during a software step scan.

### `kickoff`

Begin a flyscan:

- For **motors**, starts motion and returns once at velocity.
- For **detectors**, may do nothing if hardware-triggered.

### `collect`

Collect the data after a `trigger` or `kickoff`.

### `complete`

Wait for the flyscan to finish:

- For **detectors**, waits for frame writing.
- For **motors**, waits for ramp-down.

> Must follow `kickoff`.

### `close_run`

End the run. Finalize metadata and file output.

### `unstage`

Return the device to its original state.

Mnemonic
--------

### **"Some Ordinary People Keep Collecting Cool Clean Utensils"**

This mnemonic helps remember the method sequence:

- **S** - `stage`
- **O** - `open_run`
- **P** - `prepare`
- **K** - `kickoff`
- **C** - `collect`
- **C** - `complete`
- **C** - `close_run`
- **U** - `unstage`

## Memory Frames for Correct Ordering

- “No **Prep** Before Run is Done” → `prepare()` must follow `open_run()`
- “No **Kickoff** Before Prep is Off” → `kickoff()` must follow `prepare()`
- “**Complete** Can’t Compete Without Kickoff First” → `complete()` must follow `kickoff()`

Mermaid Process Diagram
------------------------

```{mermaid}
graph TD
    A[stage] --> B[open_run]
    B --> C[prepare]
    C --> D[kickoff]
    D --> E[collect]
    E --> F[complete]
    F --> G[close_run]
    G --> H[unstage]

    C:::hook_sensitive
    style C stroke:#f66,stroke-width:2px,stroke-dasharray: 5 5

```

Mermaid Error Flowchart

```{mermaid}
flowchart TD
    Start[[Start of Plan]] --> X1{stage called?}
    X1 -- No --> E1[Exception: Device not staged]
    X1 -- Yes --> X2{open_run called before prepare?}
    X2 -- No --> E2[Exception: Hooks not available in prepare]
    X2 -- Yes --> X3{prepare called before kickoff?}
    X3 -- No --> E3[Exception: kickoff called before prepare]
    X3 -- Yes --> X4{kickoff called before complete?}
    X4 -- No --> E4[Exception: complete called before kickoff]
    X4 -- Yes --> Done[[Valid Acquisition Sequence]]
```
