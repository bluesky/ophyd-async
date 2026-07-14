# Test deletions / coverage moves — declarative-subdevices task

Per CLAUDE.md test-deletion invariant: every deleted test is logged here with justification.

## test_map_device_from_annotations (tests/unit_tests/epics/pvi/test_pvi.py)
- **Removed** in the same commit that reworked PVI DeviceMap handling (coretl review
  comments B + C on PR #1282).
- **Why:** it asserted a DeviceMap gained *fabricated* mock children `mock1`/`mock2` in
  mock mode. That fabrication (`mock_device_map_children`) was speculative and is removed:
  a DeviceMap is now created only from an explicit `DeviceMap[...]` annotation and filled
  from its node's normal named PVI entries (comment C). So the old assertions no longer
  describe intended behaviour.
- **Coverage fold-forward:**
  - Mock-mode behaviour (DeviceMap present but empty, no fabrication) → new unit test
    `test_device_map_is_empty_in_mock_mode` (same file).
  - Real annotation-driven fill (string keys from named entries, element-type checking,
    DeviceMap of signals and of devices) → new live-IOC system tests
    `test_device_map_of_signals`, `test_device_map_naming_and_parenting`,
    `test_device_map_of_devices` in tests/system_tests/epics/core/test_pvi_nested.py.
