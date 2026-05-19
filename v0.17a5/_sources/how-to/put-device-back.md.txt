# How to use settings to put devices back in their original state

[](./store-and-retrieve.md) describes how to:
- Save the state of a Device when it is in a known good state
- Restore that state during a plan, possibly only setting the Signals that are different from the saved state

This article shows how to use the same primitives to put a Device back to how it was at the beginning of the scan, analagously to ophyd sync's `stage_sigs`.

## The plan

```python
provider = YamlSettingsProvider("directory_to_save_yaml_to")

def my_plan():
    # Get the current settings from the device
    initial_settings = yield from get_current_settings(device)
    # Retrieve a previously saved settings from the provider
    known_good_settings = yield from retrieve_settings(
        provider, "yaml_file_name", device
    )
    # Apply the settings that aren't at the right value to the device
    # using the stored initial_settings from above rather than querying
    # the device again
    yield from apply_settings_if_different(
        known_good_settings,
        apply_plan=apply_settings,
        current_settings=initial_settings,
    )
    # Do what we came here to do...
    yield from do_a_scan(device)
    yield from do_another_scan(device)
    # Put it back how we found it
    yield from apply_settings_if_different(
        initial_settings,
        apply_plan=apply_settings,
    )
```

## Variations

- If you are doing this on something like a PandA which has to apply the settings in a particular order, then pass a different `apply_plan` (like [](#apply_panda_settings) to `apply_settings_if_different`)
- If you want to apply the settings without checking if they are different in the device then call the `apply_plan` directly rather than wrapping it in `apply_settings_if_different`.
