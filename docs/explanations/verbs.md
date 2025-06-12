
# Bluesky Acquisition Control Verbs

This document explains the sequence and role of Bluesky device methods used during an acquisition plan, especially in the context of flyscans and step scans. It includes a mnemonic, a Mermaid.js diagram of the valid process flow, and a flowchart for common ordering errors.
In the [bluesky repo](https://github.com/bluesky/bluesky) there is a [line](https://github.com/bluesky/bluesky/blob/4fe6276e386f243e088353c146a490479071cecf/src/bluesky/run_engine.py#L538C1-L538C35) defining `self._command_registry` that lists available bluesky verbs.

We can later call the `devices` with those verbs.

## Method Reference

### `stage`

Make the device ready for data collection (e.g., reserving resources).

### `open_run`

Start the run context. This allows run hooks like filename generation to be used.

### `prepare`

Prepares the device for acquisition. This includes:

- Setting parameters such as exposure time, number of frames (for detectors), or motion extents and run-up position (for motors).
- Moves the motors to the target beginning of run-up location
- Arming detectors if hardware-triggered.

> Must be called **after `open_run`** to ensure hooks are active.

### `set`

Set the device to a target setpoint. Used in software-driven step scans.

### `trigger` - ONLY IN SOFTWARE SCANS

Ask the detector to take a measurement during a software step scan.

### `kickoff` - ONLY IN HARDWARE SCANS

Begin a flyscan:

- For **motors**, starts motion and returns once at velocity.
- For **detectors**, may do nothing if hardware-triggered, for software triggered it starts the acquisition.

### `read` - ONLY IN SOFTWARE SCANS

Collect the data after `trigger`.

### `complete` - ONLY IN HARDWARE SCANS

Wait for the flyscan to finish:

- For **detectors**, waits for frame writing.
- For **motors**, waits for ramp-down.

> Must follow `kickoff`.

### `collect` - ONLY IN HARDWARE SCANS

Collect the data after a `complete` call.

### `close_run`

End the run. Finalize metadata and file output.

### `unstage`

Return the device to its original state.

## Mnemonic

### **"Some Ordinary People Keep Collecting Cool Clean Utensils"**

This mnemonic helps remember the method sequence:

- **S** - `stage`
- **O** - `open_run`
- **P** - `prepare`
- **K** - `kickoff`
- **C** - `complete`
- **C** - `collect`
- **C** - `close_run`
- **U** - `unstage`

## Memory Frames for Correct Ordering

- “No **Prep** Before Run is Done” → `prepare()` must follow `open_run()`
- “No **Kickoff** Before Prep is Off” → `kickoff()` must follow `prepare()`
- “**Complete** Can’t Compete Without Kickoff First” → `complete()` must follow `kickoff()`

## Mermaid Process Diagram

### For Hardware Scan

```{mermaid}
    graph TD
        A[stage] --> B[open_run]
        B --> C[prepare]
        C --> D[kickoff]
        D --> E[complete]
        E --> F[collect]
        F --> G[close_run]
        G --> H[unstage]

        D:::hardware_step
        E:::hardware_step
        F:::hardware_step

        classDef hardware_step stroke:#4b8,stroke-width:2px;

```

### For Software Scan

```{mermaid}
    graph TD
        A[stage] --> B[open_run]
        B --> C[prepare]
        C --> D[trigger]
        D --> E[read]
        E --> F[close_run]
        F --> G[unstage]

        D:::software_step
        E:::software_step

        classDef software_step stroke:#36f,stroke-width:2px;
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
