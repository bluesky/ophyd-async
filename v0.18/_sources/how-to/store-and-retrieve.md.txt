# How to store and retrieve device settings

Ophyd-async has the functionality to easily store the current values of all of a [](#Device)'s [](#SignalRW)s in a fully customisable format, and to load that state to the Device during a [Bluesky plan](inv:bluesky#plans). For a plan which requires a Device to be in, or close to a known state, we can, before running an experiment plan:
1. Manually configure the Device to get it to the state which you want it be loaded to. This is done before running any experiment plans.
2. Use ophyd-async's [](#store_settings) plan to save this state.

Then, within the experiment plan:

3. Use [](#retrieve_settings) and [](#apply_settings) to set the Device back to its saved state.
4. Use [standard Bluesky plan stubs](inv:bluesky#stub_plans) to change any SignalRW which vary from the loaded state and which may change each run.

## Saving a device (steps 1-2)

Step 1 in the above can be done in whatever way is most convenient for that [](#Device), for example through a synoptic screen or a web GUI.

For step two, we first need to decide the desired format of the stored data and use an appropriate [](#SettingsProvider), which specifies how to store and retrieve [](#Settings). A common way to store Settings is in the form of a yaml file which maps every [](#SignalRW) of a device to its value at the time of saving. For this, a [](#YamlSettingsProvider) is provided already. For storing Settings in other ways, you will need to implement your own SettingsProvider. Finally, we can manually trigger the [](#store_settings) plan stub on our device.

For example, running
```
provider = YamlSettingsProvider("directory_to_save_yaml_to")
RE(store_settings(provider, "yaml_file_name", panda1))
```
using the [RunEngine](#bluesky.run_engine.RunEngine) with a connected PandA will output a yaml file mapping all of that PandA's SignalRWs to its values at the time of saving.

## Loading a device to its stored state (step 3)
To set a device to the state we saved it to in step 2, we need to use the [](#retrieve_settings) plan stub, using the same [](#SettingsProvider) and [](#Device) which were used in step 2. When using this with the YamlSettingsProvider, this will convert the saved yaml file into a Settings object which is tied to the relevant device. Then use the [](#apply_settings) plan stub to set the SignalRWs on the connected device.

Some devices require extra logic when applying settings. For example, the PandA needs to set all its PVs with suffix "_units" before all its other PVs. A plan stub which includes this extra bit of logic is included for the PandA: [](#apply_panda_settings).

Continuing from the previous example, we can load the PandA by running
```
def load_panda(panda1: HDFPanda):
    provider = YamlSettingsProvider("directory_to_save_yaml_to")
    settings = yield from retrieve_settings(provider, "yaml_file_name", panda1)
    yield from apply_panda_settings(settings)
```

In the situation where the time taken to read a set of SignalRWs of a Device is less than the time taken to set those signals, the [](#apply_settings_if_different) stub should be used instead. This will take the SignalRWs included in the Settings, read them from the connected Device, and set those that differ from the stored value:

```
def load_panda(panda1: HDFPanda):
    provider = YamlSettingsProvider("directory_to_save_yaml_to")
    settings = yield from retrieve_settings(provider, "yaml_file_name", panda1)
    yield from apply_settings_if_different(settings, apply_panda_settings)
```
