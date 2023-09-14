from typing import Dict, TypedDict

from p4p.client.asyncio import Context


class PVIEntry(TypedDict, total=False):
    d: str
    r: str
    rw: str
    w: str
    x: str


async def pvi_get(pv: str, ctxt: Context, timeout: float = 5.0) -> Dict[str, PVIEntry]:
    pv_info = ctxt.get(pv, timeout=timeout).get("pvi").todict()

    result = {}

    for attr_name, attr_info in pv_info.items():
        result[attr_name] = PVIEntry(**attr_info)  # type: ignore

    return result
