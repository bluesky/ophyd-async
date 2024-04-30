# Decision Flowchart for Creating a New ophyd_async Device

This document contains a decision flowchart designed to guide developers through the process of creating a new ophyd_async device in the Ophyd library. It outlines a series of decisions based on the device's capabilities, such as file writing, reading values from process variables (PVs), and mobility within scans. The flowchart helps in determining the appropriate class inheritance and methods to override for optimal device functionality and integration into the system.

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
