"""Composite formulas and exact protocol validation; no native engine simulation."""
import math

import pytest

from topos.energy_composite import EnergyCompositeProtocol, combine_energy_components
from topos.external_engines import ExternalProtocol


def specification(**updates):
    data = dict(template=ExternalProtocol(engine='cfour', engine_version='2.1', operation='energy',
            method='CCSD(T)', orbital_basis='PVTZ', frozen_core=True, genbas_path='/native/basis/GENBAS', genbas_sha256='a'*64),
            low_basis='PVTZ', high_basis='PVQZ', hf_exponential_alpha=1.7, correlation_inverse_power=3.,
            core_valence_basis='PCVTZ', full_triples_basis='PVDZ')
    data.update(updates)
    return EnergyCompositeProtocol(**data)


def test_explicit_energy_extrapolation_exact_for_its_declared_convergence_model():
    protocol = specification()
    hf_inf, corr_inf = -100., -.4
    hf_low, hf_high = (hf_inf + .3*math.exp(-1.7*x) for x in (3, 4))
    energies = dict(hf_low=hf_low, hf_high=hf_high,
        cc_low=hf_low+corr_inf+.2/27, cc_high=hf_high+corr_inf+.2/64,
        cv_ae=-100.45, cv_fc=-100.44, triples_full=-99.8, triples_parent=-99.797)
    result = combine_energy_components(energies, protocol)
    assert result['hf_cbs_hartree'] == pytest.approx(hf_inf, abs=1e-12)
    assert result['correlation_cbs_hartree'] == pytest.approx(corr_inf, abs=1e-12)
    assert result['electronic_energy_hartree'] == pytest.approx(-100.413, abs=1e-12)
    assert result['accuracy_claim'] is None


def test_each_component_preserves_native_identity_and_exact_core_convention():
    protocol = specification()
    native = protocol.protocols()
    assert len(native) == 8
    assert all(item.genbas_sha256 == 'a'*64 and item.engine_version == '2.1' for item in native.values())
    assert not native['cv_ae'].frozen_core and native['cv_fc'].frozen_core
    assert native['cv_ae'].orbital_basis == native['cv_fc'].orbital_basis
    assert native['triples_full'].method == 'CCSDT' and native['triples_parent'].method == 'CCSD(T)'
    assert native['triples_full'].orbital_basis == native['triples_parent'].orbital_basis


@pytest.mark.parametrize('updates', [dict(high_basis='PV5Z'), dict(low_basis='def2-TZVPP'),
    dict(core_valence_basis='PVTZ'), dict(hf_exponential_alpha=0), dict(correlation_inverse_power=-3),
    dict(hf_exponential_alpha=1e-20), dict(correlation_inverse_power=1e-20),
    dict(convention='W4-accuracy-guaranteed'), dict(full_triples_basis='bad\ncommands')])
def test_missing_or_incompatible_composite_choices_are_not_guessed(updates):
    with pytest.raises(ValueError):
        specification(**updates)


@pytest.mark.parametrize('bad', [{}, {'hf_low':-2}, {name:float('nan') for name in specification().protocols()}])
def test_composite_requires_every_finite_component(bad):
    with pytest.raises(ValueError):
        combine_energy_components(bad, specification())
