"""Actual retained echo/coordinate grammar only; never a successful CP run."""
import os
import re
from pathlib import Path

import numpy as np
import pytest

from topos.cfour_counterpoise import (
    _GEOMETRY,
    BasisCenter,
    CfourCounterpoiseLeg,
    _native_basis_geometry,
    _native_counterpoise_control,
    _native_zmat_echo,
)
from topos.engines import EngineParseError
from topos.science import BOHR_ANGSTROM

FIXTURES = Path(os.environ.get('TOPOS_FIXTURE_ROOT', Path(__file__).parent / 'fixtures'))
SOURCES = {'1.2': FIXTURES/'cfour_counterpoise/historical-1.2-ghost.stdout',
           '2.1': FIXTURES/'cfour_provider_2_1/output.stdout'}


@pytest.mark.parametrize('version', SOURCES)
def test_unchanged_genuine_echo_framing(version):
    raw = SOURCES[version].read_text()
    echo = _native_zmat_echo(raw)
    assert len(re.findall(r'(?m)\s*\*CFOUR\(', echo)) == 1
    assert 'CFOUR Control Parameters' not in echo
    if version == '2.1':
        expected = (FIXTURES/'cfour_provider_2_1/native-ZMAT.inp').read_text()
        assert [line.rstrip() for line in echo.strip().splitlines()] == [line.rstrip() for line in expected.strip().splitlines()]
        assert 'SPHERICAL=OFF' in echo and 'CALC=HF' in echo
    else:
        assert 'CALC_LEVEL=MP2' in echo and 'SPHERICAL=0' in echo
        assert len(re.findall(r'(?m)^\s*[A-Z]+:P4_[1-6]\s*$', echo)) == 6


@pytest.mark.parametrize('version', SOURCES)
@pytest.mark.parametrize('mutation', ['missing-title', 'duplicate-echo', 'missing-control-title', 'duplicate-control-title',
    'missing-top-border', 'missing-lower-border', 'wrong-title-border', 'missing-input-control', 'duplicate-input-control'])
def test_missing_ambiguous_or_malformed_echo_is_rejected(version, mutation):
    raw = SOURCES[version].read_text()
    lines = raw.splitlines()
    title = next(i for i, line in enumerate(lines) if 'Input from ZMAT file' in line)
    control = next(i for i, line in enumerate(lines) if 'CFOUR Control Parameters' in line)
    if mutation == 'missing-title':
        lines[title] = ''
    elif mutation == 'duplicate-echo':
        lines += lines[title-1:control+2]
    elif mutation == 'missing-control-title':
        lines[control] = ''
    elif mutation == 'duplicate-control-title':
        lines.append(lines[control])
    elif mutation == 'missing-top-border':
        lines[title-1] = ''
    elif mutation == 'missing-lower-border':
        lines[title+1] = ''
    elif mutation == 'wrong-title-border':
        lines[title] += ' unsupported suffix'
    elif mutation == 'missing-input-control':
        lines = [line.replace('*CFOUR(', '*MISSING(') for line in lines]
    else:
        lines.insert(title+2, '*CFOUR(BASIS=SPECIAL)')
    with pytest.raises(EngineParseError):
        _native_zmat_echo('\n'.join(lines))


def test_missing_starred_footer_is_rejected():
    raw = SOURCES['2.1'].read_text()
    lines = raw.splitlines()
    control = next(i for i, line in enumerate(lines) if 'CFOUR Control Parameters' in line)
    assert set(lines[control-2]) == {'*'}
    lines[control-2] = ''
    with pytest.raises(EngineParseError, match='closing delimiter'):
        _native_zmat_echo('\n'.join(lines))


@pytest.mark.parametrize('version', SOURCES)
def test_actual_control_rows_cannot_be_missing_or_duplicated(version):
    raw = SOURCES[version].read_text()
    assert _native_counterpoise_control(raw, 'REFERENCE') == 'RHF'
    row = re.search(r'(?m)^[ \t]*REFERENCE[ \t]+\w+[ \t]+[^\n]+', raw)[0]
    with pytest.raises(EngineParseError, match='Missing/ambiguous native control'):
        _native_counterpoise_control(raw.replace(row, ''), 'REFERENCE')
    with pytest.raises(EngineParseError, match='Missing/ambiguous native control'):
        _native_counterpoise_control(raw+'\n'+row, 'REFERENCE')


def test_actual_2_1_coordinate_transport_rejects_duplicate_missing_and_wrong_rows():
    raw = SOURCES['2.1'].read_text()
    table = list(_GEOMETRY.finditer(raw))
    assert len(table) == 1
    rows = [line.split() for line in table[0]['rows'].splitlines()]
    centers = [BasisCenter(symbol=row[0], atom_id=str(i), coordinates=(np.array(list(map(float,row[-3:]))) * BOHR_ANGSTROM).tolist(), physical=True)
               for i,row in enumerate(rows)]
    # Method is deliberately unvalidated here: this pure reader tests the
    # authentic HF Cartesian table, not CCSD(T), ghost physics or CP completion.
    protocol = CfourCounterpoiseLeg(engine='cfour', engine_version='2.1', operation='energy', method='CCSD(T)',
        orbital_basis='6-31G**', frozen_core=False, basis_centers=centers, dropped_core_orbitals=0,
        genbas_path='/unexecuted/grammar-only/GENBAS', genbas_sha256='a'*64)
    xyz, _ = _native_basis_geometry(raw, protocol)
    assert xyz.shape == (3, 3)
    with pytest.raises(EngineParseError, match='Exactly one'):
        _native_basis_geometry(raw+table[0][0], protocol)
    with pytest.raises(EngineParseError, match='Exactly one'):
        _native_basis_geometry(raw.replace(table[0][0], ''), protocol)
    first = table[0]['rows'].splitlines(True)[0]
    with pytest.raises(EngineParseError, match='count differs'):
        _native_basis_geometry(raw.replace(table[0]['rows'], first+table[0]['rows']), protocol)
    changed = raw.replace(table[0]['rows'], table[0]['rows'].replace('O', 'C', 1))
    with pytest.raises(EngineParseError, match='identity differs'):
        _native_basis_geometry(changed, protocol)
