# Where should Device logic live?

As ophyd-async is a layer built on top of Control Systems, the question arises: where should the Device logic live? This article gives some opinions about where it is best to write that logic

## What lives in the Control System

The Control System should be used to provide a consistent engineering interface to all hardware it monitors, abstracting away details like wire protocols. For EPICS and Tango this means creating a series of PVs or Attributes, each of which has a:
- strongly typed value
- timestamp when that value changed
- alarm severity when something goes wrong

This allows engineering screens and archiving to be made against this lower level interface, which is very useful for debugging and recording when something goes wrong, as well as working out how the hardware behaves under specific circumstances.

## What lives in ophyd-async Devices

The ophyd-async Device is good for assembling information from various PVs or Attributes into a higher level user focussed interface. For instance a motor might have dozens of parameters, but when you use it in a scan you typically want to `bps.mv(motor, 42.1)`, and the logic of what you need to set on the hardware to make this happens should live in the Device.

## What lives in bluesky plans

The plan level is best for doing cross-device logic, and setting Devices up to their initial state. It allows Devices to be used in many plans, and customized within that particular plan for the settings of that experiment. It should be composed of standard plan stubs like `bps.mv` though, if you have to write your own low level plan stubs then maybe the logic should be pushed down to the Device.

## Where it's a judgement call

The above sections dealt with the extremes of the system, the user facing interface and the hardware facing interface, but in the middle it's not so easy to decide. 

Take for instance an EPICS Device for with a `parameter1` and a `parameter2`. Each of these parameters is backed by a pair of PVs, one to change the setpoint and one to readback the value. What behavior would you expect when `bps.mv(device.parameter1, value1)` completes? Probably you would expect the device to have taken the value of the parameter and acted on it, so that if you `bps.rd(device.parameter1)` it would give you back that same value.

In this case you could put the logic in a few places:
- You could make the EPICS PV support caput complete (using device support or a busy record) so that when you sent the value down to EPICS it didn't return until the value had been applied to the hardware and readback had been updated.
- You could make `parameter1` be a `Device` with a `set()` method that put to a setpoint and waited until the readback matched using [](#set_and_wait_for_value)
- You could put the logic of waiting in a plan, and use that instead `bps.mv`

For most cases we should prefer pushing down to the Control System, but if that is difficult to do then putting it in the Device is also possible. For this particular case then it's not a good idea to put the logic in a plan, as that stops people using the standard `bps.mv` plan with this Device.
