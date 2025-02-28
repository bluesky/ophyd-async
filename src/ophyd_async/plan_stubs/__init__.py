"""Plan stubs for connecting, setting up and flying devices."""

from ._ensure_connected import ensure_connected
from ._fly import (
    fly_and_collect,
    prepare_static_seq_table_flyer_and_detectors_with_same_trigger,
    time_resolved_fly_and_collect_with_static_seq_table,
)
from ._nd_attributes import setup_ndattributes, setup_ndstats_sum
from ._panda import apply_panda_settings
from ._settings import (
    apply_settings,
    apply_settings_if_different,
    get_current_config_settings,
    get_current_settings,
    retrieve_config_settings,
    retrieve_settings,
    store_config_settings,
    store_settings,
)

__all__ = [
    "fly_and_collect",
    "prepare_static_seq_table_flyer_and_detectors_with_same_trigger",
    "time_resolved_fly_and_collect_with_static_seq_table",
    "ensure_connected",
    "setup_ndattributes",
    "setup_ndstats_sum",
    "apply_panda_settings",
    "apply_settings",
    "apply_settings_if_different",
    "get_current_settings",
    "get_current_config_settings",
    "retrieve_settings",
    "retrieve_config_settings",
    "store_settings",
    "store_config_settings",
]
