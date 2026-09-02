# 22. Add a bounded `DetectorDataLogic` tier

Date: 2026-07-17

## Status

Accepted

## Context

[](./0012-detector-rewrite.md) split data production out into `DetectorDataLogic`. After
[](./0020-runtime-readable-format.md) removed the single-event tier, one tier was left: a
logic prepared for an unbounded number of collections, feeding `collect_asset_docs()` and
`describe_collect()` and doing its own writes as it went.

Four open issues bottom out in two gaps.

### The data logic is not told enough at prepare time

Issue #1309 wants chunk size and flush rate configured from the scan parameters. An Xspress
running at 400 Hz with a 2 Hz flush rate wants 200 frames per chunk; the PandA wants a flush
period. Neither is expressible, because an unbounded logic is told nothing about timing:
`ADHDFDataLogic` reads `num_frames_chunks` back from the IOC and forces it to 1 if unset, the
PandA hardcodes `chunk_shape=(1024,)` behind a TODO, and Odin hardcodes `(1, *data_shape)`.

The parameter actually needed is the frame **period** (`livetime + deadtime`), not the number
of frames, since the requirement is a flush *rate* — and the period is known for step scans as
well as fly scans, where the total frame count is not.

Two workarounds were rejected: subclassing `TriggerInfo` and `prepare()` to carry a chunk size
(as Malcolm did) puts a data-writing concern in the trigger path, against
[](./0012-detector-rewrite.md)'s rule that a logic is handed only the fields it needs;
computing it in the `DetectorTriggerLogic` puts a data concern in the trigger logic.

### Detectors that produce data but cannot write files

Issues #1248 and #888 come from a Struck SIS3820 scaler in a VME crate, a MeasComp CTR-08, a
TetrAmm electrometer, an electron analyser. They want the trigger, arm, prepare and stage
machinery of `StandardDetector` but must emit event pages, and `StandardDetector` inherited
`WritesStreamAssets` unconditionally — the bundler calls `collect_pages()` only on a device
that is *not* one. (#888 asks for the writer to be optional, which the rewrite already did;
its real request is #1248, so it is a duplicate.)

These are not areaDetectors, and they put more pressure on the trigger/acquire/data split. A
CTR-08 has no driver/plugin split in the hardware: `MCS:EraseStart` both clears the arrays and
starts counting, and `MCS:NuseAll` is both the exposure count and the buffer size, where an
areaDetector acquires with `driver.acquire` and captures with a separate `TSAcquire` or HDF
`capture`.

### These are the same gap

Both groups must be told *how many* collections to expect at prepare time, because they own a
finite buffer that has to be sized before acquisition: the scaler's MCA array length *is* the
frame count, and the stats plugin's `TSNumPoints` must be set before the time series starts. A
device with a finite buffer also naturally produces its data as pages at the end of an event
rather than as stream datums as it goes.

So one new tier serves both, and #1309's period rides along with it.

### The areaDetector stats duality

An `NDPluginStats` exposes each statistic twice: as a scalar (`Total_RBV`) and as a time
series array (`TSTotal`). Only the scalar was modelled, as a registered signal read once per
event, so a detector with no file writer had no way to produce a value per collection for a
fly scan.

## Decision

### One method that describes, and one that starts

```python
class DetectorDataLogic:
    async def make_data_provider(
        self, datakey_name: str, num_collections: int, period: float
    ) -> StreamableDataProvider | PageableDataProvider | None: ...
    async def start(self) -> None: ...
```

`make_data_provider` says what this logic *would* produce for this scan without starting
anything; `start` does the writes that make it happen, and is called only for the providers
the detector will use. So the detector asks every logic what it would make, decides which ones
it wants, and starts only those.

One `prepare_*` per tier, doing both jobs, was tried first. It forces the detector to arm
hardware to find out what it would get, so a provider it then decides not to use has to be
stopped again — wasteful with a `TSAcquire` erase, and impossible to justify once the choice
depends on what the providers produce.

`num_collections` is the **total** for the scan (`TriggerInfo.number_of_collections`), and
both tiers are told the period, so either can size a chunk or a buffer against it.

### The tier is the type of the provider returned

There is no declaration of which tier a logic implements and no override detection: a logic
returning a [](#StreamableDataProvider) is unbounded for this scan, one returning a
[](#PageableDataProvider) is bounded, and one may return either depending on what it is asked
for. Returning `None` means "not this scan" — how a finite buffer declines an unbounded one,
or a plugin that is switched off declines any. It is neither an error nor warned about, as
agreed in #1364: the point is that a detector may carry more logics than one scan uses.

### `PageableDataProvider`, with readings derived from pages

The bounded tier returns one provider type, which emits pages. Readings are derived from those
pages rather than being a separate code path: a step-scan prepare has `number_of_events == 1`,
so its page holds exactly one event, which extracts to a single reading.
`collections_per_event` appears in the datakey shape exactly as for a
`StreamableDataProvider`.

### The period is resolved in `prepare()`

`TriggerInfo.livetime` of 0 means "whatever is currently set on the detector", so the period
cannot simply be forwarded: an explicit `prepare(TriggerInfo(number_of_events=10))` would hand
the data logic a period of 0. Instead `DetectorTriggerLogic.default_trigger_info()` is extended
to return the current `livetime` and `deadtime`, and `prepare()` fills a zero `livetime` in
from it *after* preparing the trigger logic, which [](./0012-detector-rewrite.md) already
requires to come first, so the hardware holds the real values by then. Data logics therefore
never see a period of 0.

### Streaming providers are reused, finite buffers are re-made

Providers are reused while the scan they were made for is unchanged, so a step scan does not
reopen its file on every point. The reuse key is `collections_per_event` *and* the period,
because both are baked into a `StreamResource` when it is made — the shape from the first, the
chunking from the second — and areaDetector's `num_frames_chunks` can only be set before
`capture` starts. A period change therefore starts a new file.

A finite buffer is re-made on every `prepare()` and `trigger()` regardless, because re-making
it is what re-arms it, and `kickoff()` never re-makes one: exactly the set of places a buffer
should and should not be re-armed. A re-armed buffer sitting at 0 alongside a monotonic HDF
writer at 15 would trip the `_all_the_same` reducer, so the two kinds are tracked separately.

### A bounded provider's progress baseline is zero in `trigger()`

`trigger()` takes a bounded provider's starting progress to be 0 rather than reading it back,
while `kickoff()` reads it live.

It is tempting to derive this instead of stating it, since re-arming refreshes
`collections_written`, and a stats time series is erased by the `TSAcquire` write in its
`start` — so the refreshed read already returns zero. That only holds when the data logic
performs the erase. Where the erase belongs to the acquire control, as with the CTR-08's
`EraseStart`, it happens after that read, so the baseline would be the stale pre-erase value
and the detector would wait for twice the buffer's length and hang. Stating the rule keeps the
framework agnostic about which component erases.

### Erase and start controls belong to the acquire logic

Where one control both starts acquisition and clears the data buffer, it belongs to the
`DetectorAcquireLogic`, alongside the stop control and the idle status. Nothing needs to
declare the erase to the framework: a data logic's `start` always runs before
`start_acquiring()`, so the buffer is sized before the control fires, and the baseline rule
above means the detector does not care who erased it.

The trigger/acquire/data split therefore survives these devices, with the three logics sharing
one IO device exactly as the areaDetector logics share a `driver`. The split is of concerns,
not of hardware.

### Logic objects fill exactly one role

Building a `DetectorLogic` raises if an object satisfies more than one of the three logic
roles, directing the author to pass separate objects. A device whose concerns all live on one
control is a natural candidate for a single combined object, and registration is a chain of
`isinstance` tests, so such an object would silently register as the first role it matched and
have the others dropped without a word.

### A detector produces stream assets or event pages, never both

The two bluesky protocols are mutually exclusive by design, to avoid a device producing blocks
of two different sizes, so a detector whose logics would produce both raises. How the
applicable verb is exposed, and the one case where the two may be carried together, are in
[](./0023-detector-is-a-flyable.md).

Which kind a detector produces is decided per prepare, so a single detector class can be either
depending on its `__init__` arguments — one `AravisDetector`, configured for files or for pages
— which was the original requirement. That it can also change *between runs*, when a file
writer is switched off and a stats time series takes over, is documented rather than enforced:
a run's descriptor is emitted at its start, so switching part way through would leave
`describe_collect()` and the documents disagreeing, and a Device cannot see run boundaries.

### Stats with a file writer go via NDAttributes

An areaDetector with an HDF writer does not need the stats time series: `ADHDFDataLogic`
already pulls NDAttribute datasets into the file, which is areaDetector's own mechanism for
exactly this. So registering the scalar with `set_readable_format` remains right for a
detector that writes files and wants a stats value in a step scan, and a stats time series is
right for one that writes none.

### One stats data logic for many arrays

An `NDPluginStats` has one time series control (`TSNumPoints`, `TSAcquire`, `TSAcquireMode`)
shared across roughly twenty arrays, so one stats data logic covers *many* arrays with the
control embedded, rather than one logic per array with a shared control object. This follows
the existing grain — a provider already emits many datakeys, as `ADHDFDataLogic` does for the
main dataset plus its NDAttributes — and avoids the coordination problem of several logics
contending over one `TSAcquire`. Which statistics are wanted becomes a constructor argument.

## Consequences

`DetectorDataLogic` implementations must be rewritten onto `make_data_provider` and `start`,
and take the new `period` argument. This is a breaking change for out-of-tree data logics; the
library is in alpha and no shim is provided. Splitting them is usually mechanical — describe in
one, write in the other — but a logic that cannot describe its data without starting (in tree,
`OdinDataLogic`, whose frame shape is only readable once the file processor is writing) has to
do its writes in `make_data_provider` and leave `start` empty, which is safe only while such a
logic is never the one a detector drops. In-tree, `ADHDFDataLogic` and `PandaHDFDataLogic` can
compute chunk size and flush period from the rate, replacing the TODOs that stand in for it.

`DetectorTriggerLogic.default_trigger_info()` implementations should return the current
`livetime` and `deadtime` alongside the frame count. Those that do not still work, but their
detectors fall back to reading the chunk size back from hardware.

Detectors that cannot write files become expressible: a data logic returning a
`PageableDataProvider` gives them `collect_pages()` and the whole of `StandardDetector`
besides. This closes #1248 and #888. Fly scanning an areaDetector that carries an HDF writer
plus a finite-buffer data logic starts working, closing #1364.

A data logic may decline a scan for reasons of its own: `ADHDFDataLogic` and
`StatsTimeSeriesDataLogic` take an `enable_callbacks` flag, defaulting to today's behaviour of
switching the plugin on, which when `False` makes them follow whatever the plugin is set to
and produce nothing when it is off.

A device whose exposure count and buffer size are the same PV has it written twice: by the
trigger logic as `number_of_exposures`, and by the data logic as `num_collections`. The two
agree only when `exposures_per_collection` is 1. This is latent rather than live, because such
devices do not average exposures and so cannot ask for anything else, but a detector that could
do both would need its data logic to read the value back rather than set it.
