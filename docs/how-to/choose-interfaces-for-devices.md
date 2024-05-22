# Decision Flowchart for Creating a New ophyd_async Device

This document contains decision flowcharts designed to guide developers through the process of creating a new ophyd_async device in the Ophyd library. These flowcharts help in determining the appropriate class inheritance, methods to override, and testing procedures for optimal device functionality and integration into the system.

## High-Level Development Flowchart

This high-level flowchart guides the overall process of creating a new ophyd_async device, from testing PVs to overriding methods and determining state enums.

```{mermaid}


  flowchart TD
    highLevelStart([Start]) --> scoutUsers[Scout current and potential users of the device, tag them in the draft PR]
    scoutUsers --> testPVs[Test PVs to get the right values]
    testPVs --> decideStateEnums[Decide on State Enums: extend str, Enum]
    decideStateEnums --> chooseMethods[Choose which superclass methods to override]
    chooseMethods --> finalizeDevice[Finalize Device Implementation]
    finalizeDevice --> requestFeedback[Request feedback from tagged users]
    requestFeedback --> rebaseOnMain[Rebase on main -> make sure tests pass still]
    rebaseOnMain --> coordinateMerges[Coordinate merges with other codebase updates]
    coordinateMerges --> markPRReady[Mark PR as ready]

```

## Interface Selection Flowchart

This flowchart assists in selecting the appropriate interfaces based on the device's capabilities, such as file writing, reading values from process variables (PVs), and mobility within scans.

```{mermaid}

  flowchart TD
    start([Start]) --> isFileWriting{Is it a File Writing Detector?}
    isFileWriting -- Yes --> useStandardDetector[Use StandardDetector]
    isFileWriting -- No --> producesPVValue{Does it produce a value from a PV you want to read in a scan?}
    producesPVValue -- Yes --> isMovable{Is it something that you move in a scan?}
    isMovable -- Yes --> useReadableMovable[Use StandardReadable + AsyncMovable + Override set method]
    isMovable -- No --> useReadable[Use StandardReadable]
    producesPVValue -- No --> useDevice[Use Device]
```

## Testing Flowchart

This flowchart outlines the testing procedure for the new ophyd_async device, from creating fixtures to testing state transitions and hardware integration.

```{mermaid}

  flowchart TD
    testStart([Start Testing]) --> createFixtures[Create fixtures for various states of the device]
    createFixtures --> createMockReactions[Create mock reactions to signals]
    createMockReactions --> testStateTransitions[Test each device state transition]
    testStateTransitions --> testAgainstHardware[Test against hardware]
    testAgainstHardware --> testingComplete[Testing Complete]

```

## Additional Notes:

  - `with self.add_children_as_readables():` Ensure this context manager is used appropriately in the device implementation to add child components as readable properties, but not Movables.

    
