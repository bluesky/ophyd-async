# How to choose the right base class when implementing a new Device

When writing a new Device there are several base classes to choose from that will give you certain functionality. This document details how to choose between them, and the next steps to take to implement your Device.

```{seealso}
[](../tutorials/implementing-devices.md) gives some examples of how these baseclass might be used
```

## Utility baseclasses

There are some utility baseclasses that allow you to create a Device pre-populated with the right verbs to work in bluesky plans:

- [](#StandardReadable) allows you to compose the values of child Signals and Devices together so that you can `read()` the Device during a step scan.
- [](#StandardDetector) allows file-writing detectors to be used within both step and fly scans, reporting periodic references to the data that has been written so far. An instance of a [](#DetectorController) and a [](#DetectorWriter) are required to provide this functionality.
- [](#StandardFlyer) allows actuators (like a motor controller) to be used within a fly scan. Implementing a [](#FlyerController) is required to provide this functionality.

## Adding verbs via protocols

There are some [bluesky protocols](inv:bluesky#hardware) that show the verbs you can implement to add functionality in standard plans. For example:

- [](#bluesky.protocols.Movable) to add behavior during `bps.mv` and `bps.abs_set`
- [](#bluesky.protocols.Triggerable) to add behavior before `read()` in `bps.scan`

It is not strictly required to add the protocol class as a baseclass (the presence of a method with the right signature is all that is required) but generally this is done so that the IDE gives you help when filling in the method, and the type checker knows to check that you have filled it in correctly.

## Control system specific baseclass

It is possible to create [procedural devices](../explanations/declarative-vs-procedural.md) using just [](#Device) as a baseclass, but if you wish to make a declarative Device then you need a control system specific baseclass:

- [](#EpicsDevice) for EPICS CA and PVA devices
- [](#TangoDevice) for Tango devices

If you are creating a [](#StandardDetector) then multiple inheritance of that and the control system specific baseclass makes initialization order tricky, so you should use [](#TangoDeviceConnector), [](#EpicsDeviceConnector), [](#PviDeviceConnector) or [](#fastcs_connector) and pass it into the `super().__init__` rather than using the control system specific baseclass. An example of this is [](#HDFPanda).
