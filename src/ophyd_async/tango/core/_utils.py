import re


def get_full_attr_trl(device_trl: str, attr_name: str):
    device_parts = device_trl.split("#", 1)
    # my/device/name#dbase=no splits into my/device/name and dbase=no
    full_trl = device_parts[0] + "/" + attr_name
    if len(device_parts) > 1:
        full_trl += "#" + device_parts[1]
    return full_trl


def get_device_trl_and_attr(name: str):
    # TODO put example of what the attr_name could look like here...
    re_str = (
        r"([\.a-zA-Z0-9_-]*://)?([\.a-zA-Z0-9_-]+:[0-9]+/)?"
        r"([^#/]+/[^#/]+/[^#/]+/)([^#/]+)(#dbase=[a-z]+)?"
    )
    search = re.search(re_str, name)
    if not search:
        raise ValueError(f"Could not parse device and attribute from trl {name}")
    groups = [part if part else "" for part in search.groups()]
    attr = groups.pop(3)  # extract attr name from groups
    groups[2] = groups[2].removesuffix("/")  # remove trailing slash from device name
    device = "".join(groups)
    return device, attr
