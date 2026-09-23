# 20. Array Signal datatype spellings

Date: 2026-08-29

## Status

Accepted

## Context

ADR 8 settled on two ways of declaring an array Signal: `Array1D[np.<dtype>]`
for a one dimensional array of known datatype, and a bare `np.ndarray` for an
array whose datatype and dimensions are read from the control system.

That leaves a fixed datatype array of more than one dimension with no spelling.
`Array1D` asserts a rank of 1, and `np.ndarray` discards the datatype, so a soft
signal holding a stack of float64 frames had to be declared as `np.ndarray` and
lost the datatype from its data key. `npt.NDArray[np.float64]`, which is
`np.ndarray[tuple[Any, ...], np.dtype[np.float64]]`, expresses exactly this, but
was rejected by every backend.

Nothing recorded the rank an annotation asked for either, so `Array1D[np.float64]`
accepted a scalar or a nested list and stored it unchanged.

## Decision

Soft signals accept `npt.NDArray[np.<dtype>]` as a fixed datatype array whose
number of dimensions is unconstrained.

The soft converter records the number of dimensions the annotation asks for and
raises `ValueError` on a write of a different rank. `Array1D[np.float64]` accepts
only 1D arrays, `np.ndarray[tuple[int, int], np.dtype[np.float64]]` only 2D, and
`npt.NDArray[np.float64]` any rank.

EPICS Signals reject any parametrized array annotation that is not one
dimensional, with a `TypeError` raised when the Signal is created rather than
when it connects. A PV always states the rank of its data: a Channel Access
waveform and a PVA `NTScalarArray` are one dimensional, and a PVA `NTNDArray` is
the varying case that a bare `np.ndarray` already describes.

`get_ndim` is public alongside `get_dtype`, and `format_datatype` prints the
spelling that was written rather than rendering every parametrized array as
`Array1D[...]`.

## Consequences

Two runtime behaviours change without a deprecation cycle, as ophyd-async is
pre 1.0:

- A write of the wrong rank to a soft signal raises `ValueError`. This reaches
  every mock connected Signal, whatever its real backend, because
  `MockSignalBackend` is built on `SoftSignalBackend`.
- `epics_signal_rw(npt.NDArray[np.float64], "PV")` and its siblings raise
  `TypeError`. This fires in mock mode too, so a Device declared with a spelling
  no PV can satisfy now fails in unit tests rather than on the beamline.

The guidance in ADR 8 to use `Array1D` rather than `npt.NDArray` still holds for
EPICS Signals. Tango is unaffected: it already uses `npt.NDArray` for an `IMAGE`
attribute and `Array1D` for a `SPECTRUM` attribute.
