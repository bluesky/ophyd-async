from pytest import fixture

from ophyd_async.core import DeviceCollector, get_mock_put, set_mock_value
from ophyd_async.epics.eiger._eiger_io import PhotonEnergy


@fixture
def photon_energy(RE):
    with DeviceCollector(mock=True):
        photon_energy = PhotonEnergy("")
    return photon_energy


async def test_given_energy_within_tolerance_when_photon_energy_set_then_pv_unchanged(
    photon_energy,
):
    initial_energy = 10
    set_mock_value(photon_energy._photon_energy, initial_energy)
    await photon_energy.set(10.002)
    get_mock_put(photon_energy._photon_energy).assert_not_called()
    assert (await photon_energy._photon_energy.get_value()) == initial_energy


async def test_given_energy_outside_tolerance_when_photon_energy_set_then_pv_changed(
    photon_energy,
):
    initial_energy = 10
    new_energy = 15
    set_mock_value(photon_energy._photon_energy, initial_energy)
    await photon_energy.set(new_energy)
    get_mock_put(photon_energy._photon_energy).assert_called_once()
    assert (await photon_energy._photon_energy.get_value()) == new_energy
