# 20. Add a bounded `DetectorDataLogic` tier and select tiers by capability

Date: 2026-07-17

## Status

Accepted

## Context

ADR 0012 split data production out into `DetectorDataLogic`. After ADR 0021 removed the
single-event tier, one tier is left that a subclass opts into by overriding the
corresponding method:

- `prepare_unbounded(datakey_name) -> StreamableDataProvider` — any number of collections,
  feeding `collect_asset_docs()` and `describe_collect()`

Four open issues turn out to bottom out in the same two gaps.

### The data logic is not told enough at prepare time

Issue #1309 wants chunk size and flush rate configured from the scan parameters. An Xspress
running at 400 Hz with a 2 Hz flush rate wants 200 frames per chunk; the PandA wants a flush
period. Neither is expressible today, because a data logic is prepared for an *unbounded* number
of collections and so is told nothing about timing. Today's implementations paper over this:
`ADHDFDataLogic` reads `num_frames_chunks` back from the IOC and forces it to 1 if unset, the
PandA hardcodes `chunk_shape=(1024,)` behind a TODO, and Odin hardcodes `(1, *data_shape)`.

The parameter that is actually needed is the frame **period** (`livetime + deadtime`), not the
number of frames — the requirement is a flush *rate*. This matters, because the period is known
for step scans as well as fly scans, whereas the total frame count is not.

Two workarounds were considered and rejected. Subclassing `TriggerInfo` and `prepare()` to carry a
chunk size (as Malcolm did) puts a data-writing concern into the trigger path and defeats ADR
0012's rule that logic classes are handed only the fields they need. Computing the chunk size in
the `DetectorTriggerLogic` puts a data concern in the trigger logic.

### `StandardDetector` unconditionally claims to write stream assets

Issues #1248 and #888 both come from detectors that produce data but cannot write files: a Struck
SIS3820 scaler in a VME crate, a MeasComp CTR-08, a TetrAmm electrometer, an electron analyser.
These want the trigger, arm, prepare and stage machinery of `StandardDetector`, but need to emit
event pages rather than stream assets.

These are worth describing concretely, because they are not areaDetectors and they put more
pressure on the trigger/acquire/data split than an areaDetector does. A MeasComp CTR-08 exposes:

| PV | role |
|---|---|
| `MCS:EraseStart` | clears the arrays *and* starts counting — one control, no separate erase |
| `MCS:StopAll` | stop |
| `MCS:Acquiring` | idle status |
| `MCS:NuseAll` | number of channels to use — the buffer size, and the point at which it stops |
| `MCS:CurrentChannel` | how many points have been collected |
| `mca<i>.VAL` | the growing waveform arrays that hold the data |

The difference from an areaDetector is that there is no driver/plugin split in the hardware. An
areaDetector acquires with `driver.acquire` and captures with a *separate* `TSAcquire` or HDF
`capture`, so the acquire and data concerns land on different PVs and the split falls out of the
hardware. Here one control both gates acquisition and clears the data buffer, and one PV
(`NuseAll`) is both the exposure count and the buffer size.

They cannot, because `StandardDetector` inherits `WritesStreamAssets` unconditionally, and the
bluesky bundler only calls `collect_pages()` on a device that is *not* a `WritesStreamAssets`.
The two protocols are mutually exclusive by design, to avoid the case where both produce blocks
of different sizes.

#888 asks for the writer to be optional. The rewrite already made it optional in the literal
sense — `StandardDetector()` takes no writer at all. But the underlying request ("no HDF writer,
because I have PVs instead") is #1248, so #888 is a duplicate.

### These are the same gap

Both groups of devices must be told *how many* collections to expect at prepare time, because
they own a finite buffer that has to be sized before acquisition: the scaler's MCA array length
*is* the frame count, and the areaDetector stats plugin's `TSNumPoints` must be set before the
time series starts. A device with a finite buffer also naturally produces its data as pages at
the end of an event rather than as stream datums as it goes.

So one new tier serves both, and #1309's period rides along with it.

### The areaDetector stats duality

An `NDPluginStats` exposes each statistic twice: as a scalar (`Total_RBV`) and as a time series
array (`TS:TSTotal`). Only the scalar is modelled today, as a registered signal. A registered
signal is read once per event, so a detector with no file writer has no way to produce a value
per collection for a fly scan: the time series can, but nothing models it.

## Decision

### A second tier: `prepare_bounded`

```python
class DetectorDataLogic:
    async def prepare_bounded(
        self, datakey_name: str, num_collections: int, period: float
    ) -> PageableDataProvider: ...
    async def prepare_unbounded(
        self, datakey_name: str, period: float
    ) -> StreamableDataProvider: ...
```

Both tiers are told the frame period, so either can size a chunk or a buffer against it.

`num_collections` is always the **total** for the scan (`TriggerInfo.number_of_collections`),
never a per-kickoff figure. A finite buffer is fed by data callbacks and does not care how many
kickoffs span it, so per-kickoff sizing would mean resizing the buffer mid-scan.

### `PageableDataProvider`, with readings derived from pages

`prepare_bounded` returns a single provider type that emits pages. Readings are derived from
pages rather than being a separate code path: a step-scan prepare has `number_of_events == 1`, so
its page contains exactly one event, which extracts to a single reading. `collections_per_event`
appears in the datakey shape exactly as it does for `StreamableDataProvider`.

### The period is resolved in `prepare()`

`TriggerInfo.livetime` of 0 means "whatever is currently set on the detector", so the period
cannot simply be forwarded from the `TriggerInfo` — an explicit
`prepare(TriggerInfo(number_of_events=10))` would hand the data logic a period of 0.

Instead `prepare()` resolves it. `DetectorTriggerLogic.default_trigger_info()` is extended to
return the current `livetime` and `deadtime` as well as the frame count, and `prepare()` uses it
to fill in a zero `livetime` after the trigger logic has been prepared. ADR 0012 already requires
that ordering, so the hardware holds the real values by that point. Data logics therefore never
see a period of 0, and the awkward case is handled once in core rather than by every implementer.

### Tier selection is by capability, with no precedence rule

Each data logic implements exactly one tier, so core does not choose between tiers — it only
asks whether the tier a logic implements can serve the requested number of collections
`n = TriggerInfo.number_of_collections`:

| tier | serves |
|---|---|
| `prepare_unbounded` | always |
| `prepare_bounded` | `n != 0` (finite) |

A logic whose tier cannot serve `n` is dropped from the prepare context with a warning, rather
than raising, as agreed in #1364. That is what lets a detector carrying a bounded logic still be
prepared for an infinite fly scan, with only that logic dropped.

### Bounded providers are never reused

`_update_prepare_context` currently reuses providers when `collections_per_event` is unchanged,
to avoid reopening files on every step-scan point. Two changes follow.

The reuse check gains the period, since the period now determines chunk shape, and chunk shape is
baked into the `StreamResource` at provider construction. A period change therefore starts a new
file. This is inherent rather than incidental: areaDetector's `num_frames_chunks` can only be set
before `capture` starts.

Bounded providers are excluded from reuse entirely, so `trigger()` re-prepares them on every
point. This is what re-arms a finite buffer for each event, and it needs no new API: `prepare()`
and `trigger()` both call `_update_prepare_context`, and `kickoff()` does not — which is exactly
the set of places a buffer should and should not be re-armed.

Reuse consequently becomes a per-logic decision rather than an all-or-nothing branch, and
`_PrepareCtx` holds pageable providers in their own list — a re-armed bounded provider sitting at
0 alongside a monotonic HDF writer at 15 would otherwise trip the `_all_the_same` reducer.

### A bounded provider's progress baseline is zero in `trigger()`

`trigger()` takes a bounded provider's starting progress to be 0 rather than reading it back;
`kickoff()` continues to read it live.

It is tempting to derive this instead of stating it, since `_update_prepare_context` refreshes
`collections_written` after re-preparing, and an areaDetector stats time series is erased by the
`TSAcquire` write inside `prepare_bounded` — so the refreshed read already returns zero. That
derivation only holds when the data logic performs the erase itself. Where the erase belongs to
the acquire control, as with the CTR-08's `EraseStart`, it happens *after* `_update_prepare_context`
has taken its reading, so the baseline would be the stale pre-erase value; the detector would then
wait for twice the buffer's length and hang. Stating the rule keeps the framework agnostic about
which component erases.

`kickoff()` must not zero the baseline, because a fly scan erases once and accumulates across
kickoffs; zeroing there would make the second kickoff's target already satisfied and return
immediately. Since a detector may not mix bounded and unbounded logics, each call has providers of
only one kind and the rule reduces to a single choice per call site.

### Erase and start controls belong to the acquire logic

Where one control both starts acquisition and clears the data buffer, it belongs to the
`DetectorAcquireLogic`, alongside the stop control and the idle status. Nothing needs to declare
the erase to the framework: `prepare_bounded` is always called before `start_acquiring()`, so the
buffer is sized before the control fires, and the baseline rule above means the detector does not
care who erased it.

The trigger/acquire/data split therefore holds for these devices, and the three logics share one
IO device exactly as the areaDetector logics share a `driver`. The split is a split of concerns,
not of hardware, so it survives the concerns landing on a single PV.

### Logic objects fill exactly one role

`add_detector_logics()` raises if an object satisfies more than one of the three logic protocols,
directing the author to pass separate objects. This is a hazard worth catching rather than a
hypothetical: a device whose concerns all live on one control is a natural candidate for a single
combined logic object, and the registration is a chain of `isinstance` tests, so such an object
would silently register as the first protocol it matched and its other roles would be dropped
without a word.

### `collect_asset_docs` and `collect_pages` are exposed dynamically

`StandardDetector` no longer inherits `WritesStreamAssets`. Instead it binds
`collect_asset_docs` as an instance attribute only when a data logic implementing
`prepare_unbounded` is present, and `collect_pages` only when one implementing
`prepare_bounded` is present. Because bluesky's protocols are `runtime_checkable`, an absent
attribute is enough to make the isinstance check fail, and the bundler then does the right
thing. It has to be a real attribute rather than a `__getattr__` hook, because Python 3.12+
resolves those checks with `inspect.getattr_static`, which never calls `__getattr__`.

This keys off the data logics, which are fixed when the detector is constructed, rather than off
the prepare context, which does not exist until `prepare()` runs.

This keeps a single detector class able to be either kind depending on its `__init__` arguments —
one `AravisDetector`, configured for files or for pages — which was the original requirement, and
it needs no change to bluesky.

### Mixing bounded and unbounded logics raises

`add_detector_logics()` raises if a detector is given both a bounded and an unbounded data logic,
since that is the one combination where both `collect_asset_docs` and `collect_pages` would be
exposed and both would produce data in a fly scan.

### Stats with a file writer go via NDAttributes

It follows that an areaDetector with an HDF writer does not use the stats time series. It does
not need to: `ADHDFDataLogic` already pulls NDAttribute datasets into the file, which is
areaDetector's own mechanism for exactly this. The time series tier is for detectors with no
writer at all.

Registering the scalar with `set_readable_format` therefore remains the right choice for a
detector that writes files and wants a stats value in a step scan, and a stats time series data
logic is the right choice for one that writes no files.

### One stats data logic for many arrays

An `NDPluginStats` has one time series control (`TSControl`, `TSNumPoints`, `TSAcquire`) shared
across roughly twenty arrays. A stats data logic therefore covers *many* arrays with the control
embedded, rather than one logic per array with a shared control object.

This follows the grain of the existing design — a provider already emits many datakeys, as
`ADHDFDataLogic` does for the main dataset plus its NDAttributes — and it avoids the coordination
problem, since the detector prepares each data logic independently and several logics contending
over one `TSAcquire` would need reference counting or an ordering guarantee. Which statistics are
wanted becomes a constructor argument.

## Consequences

`DetectorDataLogic` implementations that override `prepare_unbounded` must take the new `period`
argument. This is a breaking change for out-of-tree data logics; the library is in alpha and no
compatibility shim is provided. In-tree, `ADHDFDataLogic` and `PandaHDFDataLogic` can then
compute chunk size and flush period from the rate, replacing the TODOs and hardcoded values that
stand in for it today.

`DetectorTriggerLogic.default_trigger_info()` implementations should return the current
`livetime` and `deadtime` alongside the frame count. Those that do not will still work, but their
detectors will fall back to today's behaviour of reading the chunk size back from hardware.

Detectors that cannot write files become expressible: a data logic implementing `prepare_bounded`
gives them `collect_pages()` and the whole of `StandardDetector` besides. This closes #1248 and
#888.

Fly scanning an areaDetector that carries an HDF writer plus a single-tier data logic starts
working, with the single-tier logic dropped and a warning, closing #1364.

Mixing bounded and unbounded data logics on one detector is not supported. If a use case appears
that genuinely needs a file *and* pages in one fly scan, it needs the bluesky bundler to allow
both protocols and error only on a size mismatch — a larger change, deliberately deferred.

A device whose exposure count and buffer size are the same PV will have it written twice: once by
the trigger logic as `number_of_exposures`, and once by the data logic as `num_collections`. The
two agree only when `exposures_per_collection` is 1. This is latent rather than live, because such
devices do not average exposures and so cannot ask for anything else, but a detector that could do
both would need its data logic to read the value back rather than set it. It is the same
one-PV-two-concerns shape as the combined erase-and-start control, and the same answer applies:
the split is of concerns, not of PVs.
