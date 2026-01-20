# 12. Rewrite StandardDetector with Composition-Based Logic
Date: 2026-01-20

## Status

Accepted

## Context

The original `StandardDetector` implementation had several architectural issues:
- `DetectorController` and `DetectorWriter` combined multiple concerns (arming, triggering, and data writing), so features like arming which was common between many areaDetectors was inherited in many controllers
- Detector implementations required complex inheritance hierarchies 
- Trigger modes were inconsistently named and didn't clearly convey their behavior
- Detectors that read data from PVs were handled in a completely different way to those that wrote to files
- There was no way to read signals from devices to produce deadtime

These issues made it challenging to implement new detectors and support advanced use cases like:
- Detectors with multiple HDF writers for different ROIs
- Detectors with mixed streaming and non-streaming outputs
- Detectors that combine file writing with signal reading (e.g., stats plugins)

## Decision

We will restructure `StandardDetector` to use composition with three separate logic classes:

### New Logic Classes

1. **`DetectorTriggerLogic`** - Handles trigger configuration
   - `prepare_internal(num, livetime, deadtime)` - Setup for internal triggering
   - `prepare_edge(num, livetime)` - Setup for external edge triggering  
   - `prepare_level(num)` - Setup for external level (gate) triggering
   - `prepare_exposures_per_collection(n)` - Configure exposure averaging
   - `get_deadtime(config_values)` - Calculate detector deadtime
   - `config_sigs()` - Signals to include in `read_configuration()`

2. **`DetectorArmLogic`** - Handles detector arming/acquisition
   - `arm()` - Arm the detector
   - `wait_for_idle()` - Wait for detector to become idle
   - `disarm()` - Disarm the detector

3. **`DetectorDataLogic`** - Handles data production
   - `prepare_single(detector_name)` - Returns `ReadableDataProvider` for single-event data
   - `prepare_unbounded(detector_name)` - Returns `StreamableDataProvider` for streaming data
   - `get_hinted_fields(detector_name)` - Returns field names to hint
   - `stop()` - Stop data acquisition

### Data Provider Classes

- **`ReadableDataProvider`** - For non-streaming data (appears in event documents)
  - `make_datakeys()` - Generate DataKey descriptions
  - `make_readings()` - Read current values
  
- **`StreamableDataProvider`** - For streaming data (appears in StreamDatum documents)
  - `make_datakeys(collections_per_event)` - Generate DataKey descriptions
  - `make_stream_docs(collections_written, collections_per_event)` - Emit StreamAsset documents
  - `collections_written_signal` - Signal tracking write progress

### Detector Changes

`StandardDetector` now:
- Accepts logic components via `add_logics(*logics)` method
- Accepts configuration signals via `add_config_signals(*signals)` method
- Provides `get_trigger_deadtime()` to query supported triggers and deadtime if hardware triggerable

### Updated TriggerInfo

The `TriggerInfo` model is restructured with clearer semantics:
- `trigger`: What type of triggering (INTERNAL, EXTERNAL_EDGE, EXTERNAL_LEVEL)
- `livetime`: Exposure time (for INTERNAL and EXTERNAL_EDGE)
- `deadtime`: Time between exposures (for INTERNAL)
- `exposures_per_collection`: Number of exposures averaged per collection
- `collections_per_event`: Number of collections per bluesky event
- `number_of_events`: Number of bluesky events to emit

### Trigger Type Renaming

Trigger types renamed for clarity:
- `EDGE_TRIGGER` → `EXTERNAL_EDGE` - Rising edge starts an internally-timed exposure
- `CONSTANT_GATE` → `EXTERNAL_LEVEL` - High level duration determines exposure time  
- `VARIABLE_GATE` → `EXTERNAL_LEVEL` - Same as CONSTANT_GATE
- `INTERNAL` → `INTERNAL` - Detector generates exposures internally

## Consequences

### Benefits

1. **Separation of Concerns**: Each logic class has a single, well-defined responsibility
2. **Easier Testing**: Logic components can be tested independently
3. **Flexible Composition**: Detectors can mix and match logic components
4. **Multiple Data Streams**: Easy to add multiple data logics for different outputs
5. **Clearer Semantics**: Trigger types and timing parameters have unambiguous meanings
6. **Better Type Safety**: Concrete detector classes provide proper typing

### Breaking Changes

All detector implementations need updating:

#### Detector Controller → Trigger Logic + Arm Logic
```python
# old
class SimController(DetectorController):
    def __init__(self, driver: ADBaseIO):
        self.driver = driver
        
    async def prepare(self, trigger_info: TriggerInfo):
        assert trigger_info.trigger == TriggerInfo.INTERNAL, "Can only do internal"
        await self.driver.num_images.set(trigger_info.number_of_events)
        
    async def arm(self):
        await self.driver.acquire.set(True)
        
    async def wait_for_idle(self):
        await wait_for_value(self.driver.acquire, False, timeout=DEFAULT_TIMEOUT)
        
    async def disarm(self):
        await self.driver.acquire.set(False)

# new  
class SimTriggerLogic(DetectorTriggerLogic):
    def __init__(self, driver: ADBaseIO):
        self.driver = driver
        
    # Also prepare_edge and prepare_level if hardware triggering supported
    async def prepare_internal(self, num: int, livetime: float, deadtime: float):
        await self.driver.num_images.set(num)

# if ADArmLogic is not suitable
class SimArmLogic(DetectorArmLogic):
    def __init__(self, driver: ADBaseIO):
        self.driver = driver
        
    async def arm(self):
        await self.driver.acquire.set(True)
        
    async def wait_for_idle(self):
        await wait_for_value(self.driver.acquire, False, timeout=DEFAULT_TIMEOUT)
        
    async def disarm(self):
        await self.driver.acquire.set(False)
```

#### Detector Writer → Data Logic
```python
# old
class ADHDFWriter(DetectorWriter):
    async def open(self, name: str, exposures_per_event: int = 1):
        # Setup file writing
        return describe_dict
        
# new
class ADHDFDataLogic(DetectorDataLogic):
    async def prepare_unbounded(self, detector_name: str):
        # Setup file writing  
        return StreamResourceDataProvider(...)
```

#### TriggerInfo Updates
```python
# old
TriggerInfo(
    number_of_events=10,
    trigger=DetectorTrigger.EDGE_TRIGGER,
    livetime=0.1,
    deadtime=0.01,
)

# new  
TriggerInfo(
    number_of_events=10,
    trigger=DetectorTrigger.EXTERNAL_EDGE,
    livetime=0.1,
    deadtime=0.01,
)
```

#### Complete SimDetector Example
```python
# old - controller and writer_cls.with_io

from ophyd_async.epics import adcore

class SimDetector(adcore.AreaDetector[SimController]):
    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix="cam1:",
        writer_cls: type[adcore.ADWriter] = adcore.ADHDFWriter,
        fileio_suffix: str | None = None,
        name="",
        config_sigs: Sequence[SignalR] = (),
        plugins: dict[str, adcore.NDPluginBaseIO] | None = None,
    ):
        driver = adcore.ADBaseIO(prefix + drv_suffix)
        controller = SimController(driver)        
        writer = writer_cls.with_io(
            prefix,
            path_provider,
            dataset_source=driver,
            fileio_suffix=fileio_suffix,
            plugins=plugins,
        )        
        super().__init__(
            controller=controller,
            writer=writer,
            plugins=plugins,
            name=name,
            config_sigs=config_sigs,
        )

# new - handled by the baseclass
from ophyd_async.epics import adcore

class SimDetector(adcore.AreaDetector[adcore.ADBaseIO]):
    """Create an ADSimDetector AreaDetector instance."""
    
    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider | None = None,
        driver_suffix="cam1:",
        writer_type: ADWriterType | None = ADWriterType.HDF,
        writer_suffix: str | None = None,
        plugins: dict[str, NDPluginBaseIO] | None = None,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
    ) -> None:
        driver = adcore.ADBaseIO(prefix + driver_suffix)
        super().__init__(
            prefix=prefix,
            driver=driver,
            arm_logic=adcore.ADArmLogic(driver),
            trigger_logic=SimDetectorTriggerLogic(driver),
            path_provider=path_provider,
            writer_type=writer_type,
            writer_suffix=writer_suffix,
            plugins=plugins,
            config_sigs=config_sigs,
            name=name,
        )
```

#### Reading Stats Without Files
```python
# old - not easily supported

# new - use PluginSignalDataLogic
detector = SimDetector(prefix, writer_type=None)
detector.add_logics(PluginSignalDataLogic(driver, stats.total))
# Now stats.total appears in read() without file writing
```

#### Multiple Data Streams  
```python
# old - required complex inheritance

# new - add multiple data logics
detector = AreaDetector(
    driver=driver,
    arm_logic=ADArmLogic(driver),
    writer_type=None,  # Don't create default writer
)
# Add separate HDF writers for different ROIs
detector.add_logics(
    ADHDFDataLogic(..., datakey_suffix="-roi1"),
    ADHDFDataLogic(..., datakey_suffix="-roi2"),
)
```

### Migration Path

1. Update detector controller classes to separate trigger and arm logic
2. Update detector writer classes to data logic classes  
3. Update detector instantiation to use new composition API
4. Update trigger type enums in scan plans
5. Test with representative detectors before deploying widely

### Future Enhancements Enabled

- Pedestal mode for Jungfrau (special prepare logic with validation)
- Lambda "event mode" with multiple data streams
- Easy addition of NDStats outputs alongside file writing
- Better support for continuous acquisition detectors
- Simplified testing with mock logic components
