"""Explicit CBS + core-valence + full-triples frozen interaction energies.

This is a parameterized composite family, not an implementation or accuracy
claim for a named HEAT/Wn recipe. Every basis/exponent is selected explicitly.
"""
from __future__ import annotations

import math
from threading import Event

from pydantic import Field, model_validator

from .external_engines import ExternalProtocol, run_external
from .fragments import split_fragments
from .matrix_components import run_component
from .models import Contract
from .storage import IntegrityError

_BASIS_CARDINALS = {f'{prefix}{label}{suffix}': cardinal
    for prefix, suffix in [('cc-pV', 'Z'), ('PV', 'Z')]
    for label, cardinal in [('D', 2), ('T', 3), ('Q', 4), ('5', 5), ('6', 6)]}


class EnergyCompositeProtocol(Contract):
    """CFOUR protocol template supplies pinned version, native GENBAS and SCF thresholds."""
    template: ExternalProtocol
    low_basis: str
    high_basis: str
    hf_exponential_alpha: float = Field(gt=0, le=20)
    correlation_inverse_power: float = Field(gt=0, le=10)
    core_valence_basis: str
    full_triples_basis: str
    convention: str = 'explicit-CBS-CV-fT-v1'

    @model_validator(mode='after')
    def exact_variant(self):
        if (self.template.engine, self.template.method, self.template.operation, self.template.frozen_core) != ('cfour', 'CCSD(T)', 'energy', True):
            raise ValueError('Composite template must be native frozen-core CFOUR CCSD(T) single-point energy')
        if not self.template.genbas_path or not self.template.genbas_sha256:
            raise ValueError('Every composite component requires one unchanged native GENBAS and its SHA-256')
        if self.convention != 'explicit-CBS-CV-fT-v1':
            raise ValueError('No named HEAT/Wn accuracy claim is inferred from an arbitrary composite family')
        if (self.low_basis not in _BASIS_CARDINALS or self.high_basis not in _BASIS_CARDINALS
                or _BASIS_CARDINALS[self.high_basis] != _BASIS_CARDINALS[self.low_basis]+1):
            raise ValueError('CBS requires explicitly consecutive cc-pVXZ bases or documented native PVXZ aliases')
        if not self.core_valence_basis.startswith(('cc-pCV', 'cc-pwCV', 'PCV', 'PWCV')):
            raise ValueError('The same-basis ae-minus-fc core increment requires an explicit core-valence basis')
        for protocol in self.protocols().values():
            ExternalProtocol.model_validate(protocol.model_dump())
        return self

    def protocols(self) -> dict[str, ExternalProtocol]:
        specifications = {'hf_low': ('HF', self.low_basis, True), 'hf_high': ('HF', self.high_basis, True),
            'cc_low': ('CCSD(T)', self.low_basis, True), 'cc_high': ('CCSD(T)', self.high_basis, True),
            'cv_ae': ('CCSD(T)', self.core_valence_basis, False), 'cv_fc': ('CCSD(T)', self.core_valence_basis, True),
            'triples_full': ('CCSDT', self.full_triples_basis, True),
            'triples_parent': ('CCSD(T)', self.full_triples_basis, True)}
        return {role: ExternalProtocol.model_validate({**self.template.model_dump(), 'method': method,
                   'orbital_basis': basis, 'frozen_core': frozen}) for role, (method, basis, frozen) in specifications.items()}


def combine_energy_components(energies: dict[str, float], protocol: EnergyCompositeProtocol) -> dict:
    """Evaluate the explicitly declared extrapolation; no runtime/accuracy inference."""
    required = set(protocol.protocols())
    if set(energies) != required or any(isinstance(v, bool) or not math.isfinite(v) for v in energies.values()):
        raise ValueError('Every exact finite native component energy is required')
    low, high = _BASIS_CARDINALS[protocol.low_basis], _BASIS_CARDINALS[protocol.high_basis]
    ratio = math.exp(-protocol.hf_exponential_alpha * (high-low))
    hf = (energies['hf_high'] - ratio*energies['hf_low']) / (1-ratio)
    corr_low = energies['cc_low']-energies['hf_low']
    corr_high = energies['cc_high']-energies['hf_high']
    ratio_corr = (low/high)**protocol.correlation_inverse_power
    correlation = (corr_high - ratio_corr*corr_low) / (1-ratio_corr)
    cv = energies['cv_ae']-energies['cv_fc']
    triples = energies['triples_full']-energies['triples_parent']
    total = math.fsum([hf, correlation, cv, triples])
    if not all(math.isfinite(v) for v in (hf, correlation, cv, triples, total)):
        raise ValueError('Composite arithmetic is nonfinite')
    return {'electronic_energy_hartree': total, 'hf_cbs_hartree': hf, 'correlation_cbs_hartree': correlation,
            'core_valence_increment_hartree': cv, 'full_triples_increment_hartree': triples,
            'components_hartree': dict(energies), 'basis_cardinals': [low, high],
            'hf_exponential_alpha': protocol.hf_exponential_alpha,
            'correlation_inverse_power': protocol.correlation_inverse_power,
            'formula': 'HF_inf[exp(-alpha*X)] + corr_inf[X^-beta] + (ae-fc)CCSD(T) + (CCSDT-CCSD(T))fc',
            'accuracy_claim': None}


def execute_energy_composite(workflow, record, store, inputs, deadline: float, cancel_event: Event | None) -> bool:
    from .correlated_workflow import _publish

    if inputs.energy_composite is None:
        raise ValueError('T5-1w requires an explicit energy_composite with all bases, exponents and native engine identity')
    protocol = inputs.energy_composite
    molecules = [record.request.molecule, *split_fragments(record.request.molecule)]
    if len(molecules) < 3:
        raise ValueError('Composite interaction requires at least two explicit state-resolved fragments')
    results, identities = {}, set()
    for index, molecule in enumerate(molecules):
        role = 'complex' if index == 0 else f'fragment-{index-1}'
        energies = {}
        for component, native in protocol.protocols().items():
            result = run_component(workflow, record, store, f'CBS-CV-fT-{role}-{component}', molecule,
                                   native, run_external, deadline, cancel_event)
            if result is None:
                return False
            energies[component] = result.energy_hartree
            identities.add((result.engine_version, result.metadata.get('executable_sha256')))
        results[role] = combine_energy_components(energies, protocol)
    if len(identities) != 1 or not all(next(iter(identities))):
        raise IntegrityError('Composite component executable identities are inconsistent')
    interaction = results['complex']['electronic_energy_hartree'] - math.fsum(
        value['electronic_energy_hartree'] for key, value in results.items() if key != 'complex')
    _publish(record, store, 'T5-1w', {'recipe': 'explicit-CBS-CV-fT-v1', 'output_kind': 'frozen-interaction-energy',
        'definition': 'E_composite(complex) minus sum of identical-protocol frozen-inc fragment composite energies',
        'interaction_energy_hartree': interaction, 'component_details': results,
        'protocols': [protocol.model_dump(mode='json')], 'engine_identity': list(next(iter(identities))),
        'counterpoise_applied': False, 'geometry_state': 'frozen-inc', 'binding_energy_hartree': None,
        'gibbs_energy_hartree': None, 'accuracy_claim': None,
        'scope': 'Explicit family variant, not a named HEAT/Wn protocol or transfer of source benchmark accuracy'})
    return True
