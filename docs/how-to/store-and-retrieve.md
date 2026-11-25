# How to store and retrieve device settings

Ophyd-async has the functionality to easily store the current values of all of a [](#Device)'s [](#SignalRW)s in a fully customisable format, and to load that state to the Device during a [Bluesky plan](inv:bluesky#plans). For a plan which requires a Device to be in, or close to a known state, we can, before running an experiment plan:
1. Manually configure the Device to get it to the state which you want it be loaded to. This is done before running any experiment plans.
2. Use ophyd-async's [](#store_snapshot) plan to save this state.

Then, within the experiment plan:

3. Use [](#retrieve_snapshot), [](#apply_settings) and [](#apply_readable_formats) to set the Device back to its saved state.
4. Use [standard Bluesky plan stubs](inv:bluesky#stub_plans) to change any SignalRW which vary from the loaded state and which may change each run.

## Saving a device (steps 1-2)

Step 1 in the above can be done in whatever way is most convenient for that [](#Device), for example through a synoptic screen or a web GUI.

For step two, we first need to decide the desired format of the stored data and use an appropriate [](#SettingsProvider), which specifies how to store and retrieve [](#Settings). A common way to store Settings is in the form of a yaml file which maps every [](#SignalRW) of a device to its value at the time of saving. For this, a [](#YamlSettingsProvider) is provided already. For storing Settings in other ways, you will need to implement your own SettingsProvider. Finally, we can manually trigger the [](#store_snapshot) plan stub on our device.

For example, running
```
provider = YamlSettingsProvider("directory_to_save_yaml_to")
RE(store_snapshot(provider, "yaml_file_name", panda1))
```
using the [RunEngine](#bluesky.run_engine.RunEngine) with a connected PandA will output a yaml file mapping all of that PandA's SignalRWs to its values at the time of saving.

## Loading a device to its stored state (step 3)
To set a device to the state we saved it to in step 2, we need to use the [](#retrieve_snapshot) plan stub, using the same [](#SettingsProvider) and [](#Device) which were used in step 2. When using this with the YamlSettingsProvider, this will convert the saved yaml file into a [](#DeviceSnapshot) which is tied to the relevant device. Then use the [](#apply_settings) plan stub on `snapshot.settings` to set the SignalRWs on the connected device, and [](#apply_readable_formats) on `snapshot.device` and `snapshot.readable_formats` to restore the readable formats.

[](#DeviceSnapshot.settings) gives a [](#Settings) of the signal values, resolved against the Device, and [](#DeviceSnapshot.readable_formats) gives the readable formats (see below). Each access gives a new copy. The paths are resolved when the snapshot is made, so a path in the file that no longer names anything in the Device raises a `NameError` from [](#retrieve_snapshot), before anything is written, and a format that is not a `StandardReadableFormat` raises a `ValueError`.

Some devices require extra logic when applying settings. For example, the PandA needs to set all its PVs with suffix "_units" before all its other PVs. A plan stub which includes this extra bit of logic is included for the PandA: [](#apply_panda_settings).

Continuing from the previous example, we can load the PandA by running
```
def load_panda(panda1: HDFPanda):
    provider = YamlSettingsProvider("directory_to_save_yaml_to")
    snapshot = yield from retrieve_snapshot(provider, "yaml_file_name", panda1)
    yield from apply_panda_settings(snapshot.settings)
```

In the situation where the time taken to read a set of SignalRWs of a Device is less than the time taken to set those signals, the [](#apply_settings_if_different) stub should be used instead. This will take the SignalRWs included in the Settings, read them from the connected Device, and set those that differ from the stored value:

```
def load_panda(panda1: HDFPanda):
    provider = YamlSettingsProvider("directory_to_save_yaml_to")
    snapshot = yield from retrieve_snapshot(provider, "yaml_file_name", panda1)
    yield from apply_settings_if_different(snapshot.settings, apply_panda_settings)
```

## Storing readable formats too

[](#store_snapshot) also records how readable formats have changed since construction (see [](./change-readable-format.md)), and [](#apply_readable_formats) restores them. A `readable_formats` of `None`, from a file with no `<READABLE_FORMATS>` key, leaves them alone. They go under the reserved `<READABLE_FORMATS>` key, as `owner:child`, where `owner` is the path of the [](#StandardReadable) that owns the child, and `child` is the child's path from that owner. The `owner:` is left out when the Device you stored is the owner:

```yaml
energy: 7.0
temperature: 20.0
<READABLE_FORMATS>:
  energy: HINTED_SIGNAL
  temperature: null
  mirror:pitch: CONFIG_SIGNAL
```

A null drops the child. Applying first resets the tree to its class defaults, so `<READABLE_FORMATS>: {}` restores them. A file with no `<READABLE_FORMATS>` key changes no formats, and a file with only that key changes formats without writing any values. With `only_config=True`, [](#store_snapshot) stores only the configuration values but still stores the formats.

To apply only the formats, give [](#apply_readable_formats) the `snapshot.readable_formats`.
