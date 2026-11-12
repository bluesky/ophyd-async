# Changelog

## Unreleased

### Added

- `plugins_with_proc()` adds the process plugin made from a `proc_suffix` to a detector's `plugins`, and raises `ValueError` if `plugins` already has a `"proc"`. Every areaDetector vendor detector and `ContAcqDetector` uses it, so `"proc"` is reserved: pass `proc_suffix` instead.
