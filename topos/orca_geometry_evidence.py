"""Narrow evidence for ORCA 6.1.1's omitted first-cycle energy-change row.

A first-cycle stationary point has no preceding optimizer energy to print in
its convergence table. ORCA nevertheless evaluates both the starting geometry
and the geometry after that step. Their actual total energies can establish
the same numerical energy-change gate. This does not establish an independent
final gradient, nor does it replace the caller's input/geometry/artifact binding.
"""
from __future__ import annotations

import hashlib
import re
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any


def convergence_evidence(text: str, *, energy_tolerance: float) -> tuple[dict[str, bool], dict[str, Any] | None]:
    """Return native gates plus an explicitly derived, source-bound energy gate.

    Existing printed rows are never replaced. Recovery requires exactly one
    native optimizer cycle, four passing geometry rows, and one converged SCF
    evaluation on each side of its single stationary-point transition. The
    optimizer's printed TolE must equal the caller's unchanged profile value.
    Printed energies are interpreted as rounded to their final decimal digit;
    the worst-case difference must pass, without a numerical slack allowance.
    Ambiguous or incomplete output remains incomplete and cannot authorize a
    final-gradient calculation. A genuine above-threshold difference is False,
    permitting the existing bounded native restart policy to decide what follows.
    """
    # Local import permits engines to use this helper without an import cycle.
    from .engines import _FLOAT, _orca_convergence

    criteria = _orca_convergence(text)
    expected = {"rms_gradient", "max_gradient", "rms_step", "max_step"}
    if set(criteria) != expected or not all(criteria.values()):
        return criteria, None
    try:
        tolerance = Decimal(str(energy_tolerance))
    except InvalidOperation as exc:
        raise ValueError("Energy tolerance must be a finite positive number") from exc
    if not tolerance.is_finite() or tolerance <= 0:
        raise ValueError("Energy tolerance must be a finite positive number")

    versions = re.findall(r"Program Version\s+(\S+)", text)
    cycles = list(re.finditer(r"GEOMETRY OPTIMIZATION CYCLE\s+(\d+)", text))
    tables = list(re.finditer(r"\|Geometry convergence\|", text))
    banners = list(re.finditer(r"THE OPTIMIZATION HAS CONVERGED", text))
    finals = list(re.finditer(
        r"FINAL ENERGY EVALUATION AT THE STATIONARY POINT\s*\*+\s*\*+\s*\(AFTER\s+(\d+)\s+CYCLES\)", text))
    totals = list(re.finditer(r"(?m)^[ \t]*FINAL SINGLE POINT ENERGY[ \t]+(" + _FLOAT + r")[ \t]*$", text))
    terminations = list(re.finditer(r"ORCA TERMINATED NORMALLY", text))
    geometries = list(re.finditer(r"CARTESIAN COORDINATES \(ANGSTROEM\)", text))
    if (versions != ["6.1.1"] or len(cycles) != 1 or cycles[0].group(1) != "1"
            or len(tables) != 1 or len(banners) != 1 or len(finals) != 1
            or finals[0].group(1) != "1" or len(totals) != 2
            or text.count("FINAL SINGLE POINT ENERGY") != 2
            or len(terminations) != 1 or len(geometries) != 2
            or re.search(r"SCF NOT CONVERGED|SCF CONVERGENCE FAILURE", text, re.I)):
        return criteria, None
    ordered = [cycles[0], geometries[0], totals[0], tables[0], banners[0],
               finals[0], geometries[1], totals[1], terminations[0]]
    if any(first.end() >= second.start() for first, second in zip(ordered[:-1], ordered[1:], strict=True)):
        return criteria, None

    settings = text[:cycles[0].start()].split("Convergence Tolerances:")
    if len(settings) != 2:
        return criteria, None
    thresholds = re.findall(r"(?m)^Energy Change\s+TolE\s+\.{4}\s+(" + _FLOAT + r")\s+Eh\s*$", settings[1])
    if len(thresholds) != 1 or Decimal(thresholds[0].replace("D", "E").replace("d", "e")) != tolerance:
        return criteria, None
    sections = (text[cycles[0].end():totals[0].start()], text[finals[0].end():totals[1].start()])
    if any(len(re.findall(r"SCF CONVERGED AFTER\s+\d+\s+CYCLES", section)) != 1 for section in sections):
        return criteria, None
    # Require all four rows in this actual table, never scattered matches in
    # other output sections, and reject duplicate geometry rows.
    table = text[tables[0].end():banners[0].start()]
    if re.search(r"(?im)^\s*Energy change\b", table):
        # An existing malformed or nonnumeric diagnostic is not an omitted row.
        return criteria, None
    rows = re.findall(r"(?im)^\s*(RMS gradient|MAX gradient|RMS step|MAX step)\s+(" + _FLOAT
                      + r")\s+(" + _FLOAT + r")\s+(YES|NO)\s*$", table)
    if len(rows) != 4 or {row[0].lower() for row in rows} != {
            "rms gradient", "max gradient", "rms step", "max step"}:
        return criteria, None

    literals = [match.group(1) for match in totals]
    energies = [Decimal(value.replace("D", "E").replace("d", "e")) for value in literals]
    # Native energies have 12 decimal places. Bound unsupported precision or
    # exponents before Decimal arithmetic on otherwise well-formed tokens.
    if any(not value.is_finite() or len(value.as_tuple().digits) > 50
           or abs(value.as_tuple().exponent) > 50 for value in energies):
        return criteria, None
    with localcontext() as context:
        context.prec = 110
        difference = energies[1] - energies[0]
        rounding = sum((Decimal(5).scaleb(value.as_tuple().exponent - 1) for value in energies), Decimal(0))
        upper_bound = abs(difference) + rounding
    passed = upper_bound <= tolerance
    evidence = {
        "schema": "topos-orca-one-cycle-energy-change/1",
        "source": "difference of actual native initial and final stationary-point total energies; not a printed convergence row",
        "engine_version": "6.1.1", "optimizer_cycles": 1,
        "printed_energy_change_status": "NOT_EVALUATED",
        "printed_geometry_criteria": dict(criteria),
        "raw_stdout_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "native_energy_lines": [text.count("\n", 0, match.start()) + 1 for match in totals],
        "native_energy_literals_hartree": literals,
        "signed_energy_change_hartree": str(difference),
        "printed_rounding_allowance_hartree": str(rounding),
        "absolute_energy_change_upper_bound_hartree": str(upper_bound),
        "threshold_hartree": str(tolerance), "passed": passed,
        "scope": "energy gate only; exact native input/output geometry binding and independent final gradient remain required",
    }
    return {**criteria, "energy_change": passed}, evidence
