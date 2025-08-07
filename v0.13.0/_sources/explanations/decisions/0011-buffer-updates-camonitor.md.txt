# 11. Buffer updates when using `camonitor`

Date: 2025-07-30

## Status

Accepted

## Context

The ChannelAccess signal backend uses aioca.camonitor to subscribe to changes in PV values. By default it deals with backpressure by dropping excessive updates that it is too slow to handle. It also has a mode whereby it will buffer the updates, lagging behind if there are too many.

```python
# The following will buffer every update to the PV
aioca.camonitor(my_pv, all_updates=True)
```

## Decision

Default `all_updates` to `True` in the ChannelAccess backend, but provide a feature flag via an environment variable so it can be reverted at runtime if necessary.

```bash
# The following should restore the old behavior 
export OPHYD_ASYNC_EPICS_CA_KEEP_ALL_UPDATES=False
```

## Consequences

If backpressure is causing a problem, ophyd-async will slow down and lag behind. This is deemed to be an easier problem to spot and debug than updates being silently dropped. 

It is the responsibility of IOCs to not push updates too quickly (<=10Hz) rather than the responsibility of ophyd-async to handle them. If an IOC is pushing updates too quickly, it should be fixed.

There may be unknown bugs and race conditions exposed by this change, they can be temporarily remedied by disabling the feature (see above).
