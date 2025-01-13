- tutorials
  x installation
  x using existing devices - soft device, init_devices, using verbs
  x implementing devices - EPICS, Tango, FastCS mover, implementing verbs, types, Hinted signal and standard readable
  x writing tests for devices - EPICS/Tango/FastCS demo, mock, assert, system tests
  - implementing filewriting detectors - pattern detector, file writing, documents
- how-to
  x Contribute
  - How to choose the right base class when implementing a new Device
  - How to reimplement an ophyd sync device in ophyd-async
  - How to interact with signals while implementing bluesky verbs
  - How to store and retrieve device settings
  - How to use settings to put devices back in their original state
  - How to implement a device for an EPICS areaDetector
- explanations
  - design goals - differences to ophyd sync
  - devices, signals and their backends
  x declarative vs procedural devices
  - where should device logic live
  - device connection strategies


We should also document the various permutations of TriggerInfo and provide any common helpers like the one defined in #401. The cases we need to document:

    trigger=internal, livetime=deadtime=None: Internal trigger mode, with exposure and period untouched. The default for trigger() if prepare() not called
    trigger=any, livetime=float: Exposure set to livetime and period set to livetime+get_deadtime(livetime)
    trigger=any, livetime=float, deadtime=float: Exposure set to livetime and period set to deadtime
    num=0: Go until disarmed, if detector supports it
    num=+ve: Arm for this many frames
