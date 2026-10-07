"""Reviewed ORCA F12D numerical geometries from genuine native energy ledgers.

The electronic Hamiltonian is explicit. Neither the finite-difference driver nor
its mathematical tests supply an electronic energy or a native analytic gradient.
"""
from __future__ import annotations

import time
from typing import Literal

import numpy as np
from pydantic import model_validator
from scipy.optimize import minimize

from .correlated import CorrelatedMethod, run_correlated
from .correlated_workflow import _publish
from .data.reviewed_matrix_v010 import RECIPES
from .higher_composite import NumericalGeometryOptions, checked_energy_gradient
from .matrix_components import run_component
from .models import Artifact, Contract, Molecule
from .science import BOHR_ANGSTROM, rotational_constants, validate_stereochemical_preservation
from .storage import IntegrityError, atomic_json, confined_file, digest_json, file_digest, read_json


class OrcaF12GeometryProtocol(Contract):
    convention: Literal['orca-f12d-numerical-geometry-dz-v1', 'orca-f12d-numerical-geometry-tz-v1']
    energy_protocol: CorrelatedMethod
    numerical: NumericalGeometryOptions

    @model_validator(mode='after')
    def exact_definition(self):
        spec, native = RECIPES[self.convention], self.energy_protocol
        if (native.method, native.operation, native.frozen_core, native.orbital_basis,
                native.cabs, native.auxiliary_c, native.scf_integrals, native.scf_convergence) != (
                'CCSD(T)-F12D/RI', 'energy', True, spec['orbital_basis'], spec['cabs'], spec['auxiliary_c'],
                'conventional', 'VeryTightSCF'):
            raise ValueError('Reviewed F12D geometry requires the exact canonical frozen-core energy/basis/CABS/fitting/conventional-HF protocol')
        if self.numerical.gradient_max_hartree_per_bohr > 1e-5 or self.numerical.gradient_rms_hartree_per_bohr > 3e-6:
            raise ValueError('Reviewed geometry requires max gradient <=1e-5 and RMS gradient <=3e-6 Eh/bohr')
        return self


class _Interrupted(Exception):
    pass


def optimize_energy_geometry(initial, energy, options, *, check_deadline, checkpoint=None, start=None):
    """Engine-independent checked numerical driver; caller supplies actual energies.

    A cached accepted coordinate may restart the optimizer; the L-BFGS history is
    deliberately not claimed preserved. Every energy is still independently bound
    to its exact geometry and protocol by the caller's durable native ledger.
    """
    from .workflow import _topology_preserved

    derivatives = {}
    def evaluate(x):
        check_deadline()
        key = digest_json(x.tolist())
        if key not in derivatives:
            derivatives[key] = checked_energy_gradient(energy, x, options)
        value, gradient, _ = derivatives[key]
        return value, gradient

    def accepted(x):
        check_deadline()
        evaluate(x)
        if checkpoint is not None:
            checkpoint(x)

    x = np.asarray(start if start is not None else initial.coordinates).ravel() / BOHR_ANGSTROM
    result = minimize(evaluate, x, jac=True, method='L-BFGS-B', callback=accepted,
        options={'maxiter': options.maximum_iterations, 'maxls':30, 'ftol':1e-15,
                 'gtol':min(options.gradient_max_hartree_per_bohr, options.gradient_rms_hartree_per_bohr) / 2})
    check_deadline()
    value, gradient = evaluate(result.x)
    max_g, rms_g = float(np.max(np.abs(gradient))), float(np.sqrt(np.mean(gradient**2)))
    sensitivity = derivatives[digest_json(result.x.tolist())][2]
    margin = sensitivity['maximum_step_disagreement_hartree_per_bohr']
    if max_g + margin > options.gradient_max_hartree_per_bohr or rms_g + margin > options.gradient_rms_hartree_per_bohr:
        raise ValueError('Numerical geometry is not stationary within both gradient thresholds plus displacement sensitivity')
    molecule = Molecule.model_validate({**initial.model_dump(), 'coordinates':(result.x.reshape(-1,3) * BOHR_ANGSTROM).tolist()})
    if not _topology_preserved(initial, molecule) or validate_stereochemical_preservation(initial, molecule)['status'] != 'preserved':
        raise ValueError('Numerical geometry changed the original topology or mapped stereochemistry')
    check_deadline()
    return molecule, {'electronic_energy_hartree':value, 'gradient_hartree_per_bohr':gradient.reshape(-1,3).tolist(),
        'max_gradient_hartree_per_bohr':max_g, 'rms_gradient_hartree_per_bohr':rms_g,
        'derivative_sensitivity':sensitivity, 'iterations':int(result.nit), 'optimizer_success':bool(result.success),
        'optimizer_message':str(result.message), 'gradient_evaluations':len(derivatives),
        'driver':'TOPOS scipy L-BFGS-B with checked h/h2 native energy derivatives',
        'native_analytic_gradient':False, 'minimum_hessian_verified':False,
        'optimizer_history_restored':False, 'restarted_from_accepted_checkpoint':start is not None,
        'options':options.model_dump(mode='json')}


def execute_orca_numerical_geometry(workflow, record, store, inputs, deadline, cancel_event):
    protocol = inputs.orca_numerical_geometry
    if protocol is None or inputs.source_resolution != protocol.convention:
        raise ValueError('An exact reviewed source_resolution and orca_numerical_geometry protocol are required')
    protocol = OrcaF12GeometryProtocol.model_validate(protocol.model_dump())
    if RECIPES[protocol.convention]['row_id'] != record.request.matrix_row_id:
        raise ValueError('Reviewed numerical geometry variant does not match the selected row')
    if record.request.constraints:
        raise ValueError('This full-molecule numerical geometry protocol does not implement constraints')
    geometry_cap = record.request.per_geometry_budget_seconds
    if geometry_cap is not None:
        deadline = min(deadline, time.monotonic()+geometry_cap)
    initial = record.request.molecule
    identity = digest_json({'molecule':initial.model_dump(mode='json'), 'protocol':protocol.model_dump(mode='json')})
    values, identities = {}, set()

    def check_deadline():
        cancelled = cancel_event is not None and cancel_event.is_set()
        if cancelled or time.monotonic() >= deadline:
            record.status = 'cancelled' if cancelled else 'timed-out'
            record.metadata['termination_reason'] = 'Numerical ORCA geometry interrupted; completed native energies retained'
            store.commit(record)
            raise _Interrupted()

    def energy(x):
        check_deadline()
        molecule = Molecule.model_validate({**initial.model_dump(), 'coordinates':(x.reshape(-1,3)*BOHR_ANGSTROM).tolist()})
        key = digest_json(molecule.model_dump(mode='json'))
        if key not in values:
            result = run_component(workflow, record, store, 'orca-f12-geometry-'+identity+'-'+key, molecule,
                                   protocol.energy_protocol, run_correlated, deadline, cancel_event)
            if result is None:
                raise _Interrupted()
            check_deadline()
            if result.energy_hartree is None:
                raise IntegrityError('A numerical derivative requires an actual native electronic energy')
            native_identity = (result.engine_version, result.metadata.get('executable_sha256'))
            if not all(native_identity):
                raise IntegrityError('Numerical ORCA geometry lacks native executable identity')
            identities.add(native_identity)
            if len(identities) != 1:
                raise IntegrityError('Numerical geometry energies used different native executables')
            values[key] = result.energy_hartree
        return values[key]

    def checkpoint(x):
        check_deadline()
        payload = {'protocol_sha256':identity, 'coordinates_angstrom':(x.reshape(-1,3)*BOHR_ANGSTROM).tolist(),
                   'stage':'accepted-optimizer-iteration', 'optimizer_history_restored':False}
        path = store.run_dir / 'numerical-geometry-checkpoints' / (digest_json(payload)+'.json')
        atomic_json(path, payload)
        artifact = Artifact(path=path.relative_to(store.run_dir).as_posix(), sha256=file_digest(path),
                            size_bytes=path.stat().st_size, role='accepted-numerical-geometry')
        if not any(a.path == artifact.path for a in record.artifacts):
            record.artifacts.append(artifact)
        record.metadata['orca_numerical_geometry_checkpoint'] = artifact.model_dump(mode='json')
        store.commit(record)

    try:
        check_deadline()
        start = None
        saved = record.metadata.get('orca_numerical_geometry_checkpoint')
        if saved is not None:
            artifact = Artifact.model_validate(saved)
            path = confined_file(store.run_dir, artifact.path)
            if path.stat().st_size != artifact.size_bytes or file_digest(path) != artifact.sha256:
                raise IntegrityError('Accepted numerical geometry checkpoint changed')
            payload = read_json(path)
            if payload.get('protocol_sha256') != identity:
                raise IntegrityError('Accepted numerical geometry checkpoint belongs to another protocol')
            start = Molecule.model_validate({**initial.model_dump(), 'coordinates':payload['coordinates_angstrom']}).coordinates
        molecule, report = optimize_energy_geometry(initial, energy, protocol.numerical,
            check_deadline=check_deadline, checkpoint=checkpoint, start=start)
        check_deadline()
        from .method_matrix import reviewed_revision

        _publish(record, store, record.request.matrix_row_id, {
            'recipe':protocol.convention, 'definition':RECIPES[protocol.convention]['title'],
            'output_kind':'stationary-geometry', 'molecule':molecule.model_dump(mode='json'),
            'electronic_energy_hartree':report['electronic_energy_hartree'],
            'stationary_geometry_rotational_constants_mhz':[v*1000 if v is not None else None for v in rotational_constants(molecule)['constants_ghz']],
            'equilibrium_geometry_claim':False, 'equilibrium_rotational_constants_mhz':None,
            'geometry_optimized':True, 'minimum_hessian_verified':False, 'vibrational_correction_applied':False,
            'numerical_optimization':report, 'energy_geometries_in_invocation':len(values),
            'protocols':[protocol.energy_protocol.model_dump(mode='json')],
            'reviewed_revision':reviewed_revision(protocol.convention), 'accuracy_claim':None,
            'native_engine_identity':list(next(iter(identities))),
        })
        check_deadline()
        return True
    except _Interrupted:
        return False
    except ValueError as exc:
        record.status = 'partial' if record.attempts else 'unsupported'
        record.metadata['termination_reason'] = str(exc)
        store.commit(record)
        return False
