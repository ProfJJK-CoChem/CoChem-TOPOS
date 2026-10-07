"""Analytic rotor invariants and authentic public parser evidence, not native execution."""
from pathlib import Path

import numpy as np
import pytest
from scipy import constants
from scipy.spatial.transform import Rotation

from topos.anharmonic import parse_orca_vpt2, parse_orca_vpt2_geometry
from topos.engines import EngineResult
from topos.models import Molecule
from topos.rotational_transfer import (
    RotationalTransferOptions,
    calculate_rotational_transfer,
    proper_alignment,
    rotate_cartesian_hessian,
    transfer_rotational_correction,
)


@pytest.fixture
def public_rotor():
    root = Path(__file__).parents[1] / 'fixtures'
    geometry = parse_orca_vpt2_geometry((root/'orca61-vpt2-public-geometry.txt').read_text(), natoms=9)
    parsed = parse_orca_vpt2((root/'orca61-vpt2-public-furan.txt').read_text(), vibrational_modes=21)
    molecule = Molecule(symbols=geometry['symbols'], coordinates=geometry['coordinates_angstrom'])
    return molecule, geometry, parsed['rotational_constants_cm1']


def evaluate(target, reference, geometry, values, **options):
    return calculate_rotational_transfer(target, reference, geometry, values['B_e'], values['B_0'],
                                         RotationalTransferOptions(semirigid_same_basin=True, **options))


def test_public_native_masses_and_same_geometry_transfer_formula(public_rotor):
    molecule, geometry, values = public_rotor
    report = evaluate(molecule, molecule, geometry, values)
    assert geometry['masses_amu'] == [12.,12.,15.994915,12.,12.,1.007825,1.007825,1.007825,1.007825]
    assert report['native_execution_verified'] is False
    assert report['formula'] == 'B0_approx = B_R2 + (B0_DFT - Be_DFT)'
    assert np.allclose(np.asarray(report['constants_ghz'])-report['target_equilibrium_constants_ghz'],
                       (np.asarray(values['B_0'])-values['B_e'])*constants.c/1e7, atol=1e-13)
    assert report['axis_correspondence']['native_axis_for_sorted_reference'] == [0,1,2]


def test_independent_rigid_rotations_translations_and_native_axis_reordering(public_rotor):
    molecule, geometry, values = public_rotor
    expected = evaluate(molecule, molecule, geometry, values)
    r1, r2 = Rotation.from_rotvec([.3,-.6,.8]).as_matrix(), Rotation.from_rotvec([-.7,.2,.3]).as_matrix()
    reference = molecule.model_copy(update={'coordinates':(np.asarray(molecule.coordinates)@r1+[7,9,-4]).tolist()})
    target = molecule.model_copy(update={'coordinates':(np.asarray(molecule.coordinates)@r2+[-3,2,6]).tolist()})
    perm = [2,0,1]
    swapped = {key:np.asarray(val)[perm].tolist() for key,val in values.items()}
    actual = evaluate(target, reference, geometry, swapped)
    assert np.allclose(actual['constants_ghz'],expected['constants_ghz'],atol=1e-11)
    assert actual['axis_correspondence']['native_axis_for_sorted_reference'] == [1,2,0]
    assert actual['geometry_diagnostics']['target_reference_alignment']['determinant'] == pytest.approx(1.)


def test_distinct_target_keeps_its_equilibrium_geometry_and_native_correction(public_rotor):
    molecule, geometry, values = public_rotor
    target = molecule.model_copy(update={'coordinates':(np.asarray(molecule.coordinates)*1.005).tolist()})
    report = evaluate(target,molecule,geometry,values)
    assert np.allclose(report['target_equilibrium_constants_ghz'],
                       np.asarray(report['reference_equilibrium_constants_ghz'])/1.005**2)
    assert report['target_molecule']['coordinates'] != report['reference_molecule']['coordinates']


@pytest.mark.parametrize('change', [{'charge':2}, {'multiplicity':3}, {'isotopes':[13,None,None,None,None,None,None,None,None]},
                                    {'atom_ids':['relabelled']+[f'atom-{i}' for i in range(1,9)]},
                                    {'bonds':[{'atom1':0,'atom2':1,'order':2,'kind':'covalent'}]}])
def test_identity_change_rejected(public_rotor,change):
    molecule,geometry,values=public_rotor
    target=Molecule.model_validate({**molecule.model_dump(),**change})
    with pytest.raises(ValueError,match='identities'):
        evaluate(target,molecule,geometry,values)


def test_reject_mass_be_and_geometry_mismatch(public_rotor):
    molecule,geometry,values=public_rotor
    for bad in ({**geometry,'masses_amu':[13]+geometry['masses_amu'][1:]},
                {**geometry,'coordinates_angstrom':(np.asarray(molecule.coordinates)*1.001).tolist()}):
        with pytest.raises(ValueError,match='masses|reference'):
            evaluate(molecule,molecule,bad,values)
    with pytest.raises(ValueError,match='native Be'):
        evaluate(molecule,molecule,geometry,{**values,'B_e':(np.asarray(values['B_e'])*1.01).tolist()})


def test_basin_degeneracy_and_perturbative_limits(public_rotor):
    molecule,geometry,values=public_rotor
    with pytest.raises(ValueError,match='same-basin|connectivity'):
        evaluate(molecule.model_copy(update={'coordinates':(np.asarray(molecule.coordinates)*1.3).tolist()}),molecule,geometry,values)
    with pytest.raises(ValueError,match='near-degenerate'):
        evaluate(molecule,molecule,geometry,values,min_relative_moment_gap=.03)
    with pytest.raises(ValueError,match='perturbative'):
        evaluate(molecule,molecule,geometry,values,max_correction_fraction=.001)
    invalid=RotationalTransferOptions(semirigid_same_basin=True).model_copy(update={'min_axis_overlap':0})
    with pytest.raises(ValueError):
        calculate_rotational_transfer(molecule,molecule,geometry,values['B_e'],values['B_0'],invalid)


def test_small_deformation_with_large_principal_axis_rotation_is_rejected(public_rotor):
    molecule,geometry,values=public_rotor
    xyz=np.asarray(molecule.coordinates)
    xyz[:,0]+=.01*xyz[:,1]
    target=molecule.model_copy(update={'coordinates':xyz.tolist()})
    # Close principal moments amplify this small shear: geometric proximity
    # alone is insufficient justification for transferring axis corrections.
    with pytest.raises(ValueError,match='principal-axis correspondence'):
        evaluate(target,molecule,geometry,values)


@pytest.mark.parametrize('old,new', [('15.994915','-15.994915'), ('Mass [u]','Unknown mass'),
                                    ('C       0.989159345','Unknown       0.989159345')])
def test_native_geometry_mass_table_rejects_missing_or_invalid_rows(old,new):
    raw=(Path(__file__).parents[1]/'fixtures'/'orca61-vpt2-public-geometry.txt').read_text()
    assert old in raw
    with pytest.raises(ValueError):
        parse_orca_vpt2_geometry(raw.replace(old,new),natoms=9)


def test_proper_alignment_cannot_accept_reflected_tetrahedron():
    xyz=np.asarray([[.2,.3,.4],[1.1,0,.1],[0,1.3,.2],[.1,.2,1.5]])
    reflected=xyz*np.asarray([-1,1,1])
    alignment=proper_alignment(xyz,reflected,[12,13,14,15])
    assert alignment['determinant']==pytest.approx(1.)
    assert alignment['rmsd_angstrom']>.1


def test_cartesian_hessian_rotation_preserves_energy_and_gradient_quadratic_form():
    # Analytic coupled quadratic potential; no electronic-structure execution.
    rng=np.random.default_rng(1234)
    factor=rng.normal(size=(9,9))
    h=factor.T@factor
    rotation=Rotation.from_rotvec([.3,.7,-.2]).as_matrix()
    displacement=rng.normal(size=(3,3))
    moved=displacement@rotation
    transformed=rotate_cartesian_hessian(h,rotation)
    assert moved.ravel()@transformed@moved.ravel()==pytest.approx(displacement.ravel()@h@displacement.ravel())
    assert np.allclose((transformed@moved.ravel()).reshape(3,3),(h@displacement.ravel()).reshape(3,3)@rotation)
    with pytest.raises(ValueError,match='proper'):
        rotate_cartesian_hessian(h,np.diag([-1,1,1]))


def test_pure_math_and_public_grammar_cannot_claim_native_execution(public_rotor):
    molecule,_,_=public_rotor
    with pytest.raises(ValueError,match='completed native'):
        transfer_rotational_correction(molecule,EngineResult(status='unavailable',engine='orca',method='B3LYP',operation='anharmonic'),
                                       RotationalTransferOptions(semirigid_same_basin=True))
