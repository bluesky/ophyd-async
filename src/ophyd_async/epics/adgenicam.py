"""Common GenICam camera deadtime values and utilities."""

# Map model number to maximum deadtime in any pixel mode
# TODO: put back in the pixel format calcs from
# https://github.com/bluesky/ophyd-async/pull/190
_camera_deadtimes = {
    # cite: https://cdn.alliedvision.com/fileadmin/content/documents/products/cameras/Manta/techman/Manta_TechMan.pdf retrieved 2024-04-05  # noqa: E501
    "Manta G-125": 63e-6,
    "Manta G-145": 106e-6,
    "Manta G-235": 390e-6,
    "Manta G-895": 822e-6,
    "Manta G-2460": 1961e-6,
    # cite: https://cdn.alliedvision.com/fileadmin/content/documents/products/cameras/various/appnote/GigE/GigE-Cameras_AppNote_PIV-Min-Time-Between-Exposures.pdf retrieved 2024-04-05  # noqa: E501
    "Manta G-609": 47e-6,
    # cite: https://cdn.alliedvision.com/fileadmin/content/documents/products/cameras/Mako/techman/Mako_TechMan_en.pdf retrieved 2024-04-05  # noqa: E501
    "Mako G-040": 217e-6,
    "Mako G-125": 70e-6,
    "Mako G-234": 726e-6,
    "Mako G-507": 554e-6,
}


def get_camera_deadtime(model: str, override_deadtime: float | None = None) -> float:
    """Get the deadtime for a given camera model, or use an override value.

    :param model: The camera model string.
    :param override_deadtime:
        If provided, this value is returned instead of looking up the model.
    :returns: The deadtime in seconds.
    """
    if override_deadtime is not None:
        return override_deadtime
    elif model in _camera_deadtimes:
        return _camera_deadtimes[model]
    else:
        raise ValueError(f"Unknown camera model '{model}' for deadtime lookup.")
