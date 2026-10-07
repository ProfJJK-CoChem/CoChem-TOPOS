"""Search decision contracts; numerical fixtures are not engine result evidence."""
import time
from threading import Event

import pytest
from pydantic import ValidationError

from topos.models import Candidate, Molecule, RunRecord, RunRequest
from topos.workflow import Workflow


def water():
    return Molecule(symbols=["O", "H", "H"],
                    coordinates=[[0, 0, 0], [0.9572, 0, 0], [-0.23999, 0.9273, 0]])


def decisions(*energies):
    record = RunRecord(request=RunRequest(molecule=water(), energy_window_kcal_mol=1000))
    record.candidates = [Candidate(molecule=water(), energy_hartree=energy,
                                   comparison_protocol="decision-fixture-only", status="eligible",
                                   sources=[source], metadata={"observation_source": source})
                         for energy, source in zip(energies, ["INITIAL_SEED", "CREST", "JIGGLE_QUENCH"], strict=False)]
    return record


def test_same_coordinates_do_not_erase_disagreeing_energy():
    record = decisions(-5.0, -4.0)
    assert Workflow._compare(record) == "completed"
    assert [c.status for c in record.candidates] == ["eligible", "eligible"]
    comparisons = record.candidates[1].metadata["identity_comparisons"]
    assert len(comparisons) == 1 and comparisons[0]["equivalent"] is False
    assert record.metadata["deduplication"]["energy_threshold_kcal_mol"] == 0.05


def test_recomparison_resets_source_attribution_and_retains_pair_evidence():
    record = decisions(-5.0, -5.0, -5.0)
    Workflow._compare(record)
    representative = next(c for c in record.candidates if c.status == "eligible")
    assert set(representative.sources) == {"INITIAL_SEED", "CREST", "JIGGLE_QUENCH"}
    old_id = representative.candidate_id
    other = next(c for c in record.candidates if c.candidate_id != old_id)
    other.energy_hartree = -5.00001  # Comparable energy, new lowest-energy representative.
    Workflow._compare(record)
    assert other.status == "eligible"
    assert len(other.metadata["observations"]) == 2
    assert other.candidate_id not in other.metadata["observations"]
    assert set(other.sources) == {"INITIAL_SEED", "CREST", "JIGGLE_QUENCH"}
    assert all(c.metadata["identity_comparisons"] for c in record.candidates if c.status == "duplicate")


@pytest.mark.parametrize("cancel", [True, False])
def test_comparison_interruption_preserves_unmerged_observations(cancel):
    record = decisions(-5.0, -5.0)
    event = Event()
    if cancel:
        event.set()
    status = Workflow._compare(record, cancel_event=event,
                               deadline=None if cancel else time.monotonic() - 1)
    assert status == ("cancelled" if cancel else "timed-out")
    assert all(c.status == "eligible" for c in record.candidates)
    assert record.metadata["deduplication"]["pair_comparisons"] == 0


def test_energy_windows_do_not_compare_different_charge_states():
    record = decisions(-5.0, -4.0)
    record.request.energy_window_kcal_mol = 6
    record.candidates[1].molecule = Molecule(**{
        **water().model_dump(), "charge": 1, "multiplicity": 2,
    })
    Workflow._compare(record)
    assert all(c.status == "eligible" for c in record.candidates)
    assert all(c.metadata["relative_electronic_energy_kcal_mol"] == 0 for c in record.candidates)


@pytest.mark.parametrize("options", [
    {"sampler_nci": True},
    {"search_algorithm": "crest", "sampler_nci": True},
    {"search_algorithm": "crest", "sampler_profile": "crest-nci-v1"},
])
def test_nci_needs_an_explicit_search_and_fragment_partition(options):
    with pytest.raises(ValidationError):
        RunRequest(molecule=water(), **options)
