"""Matched native entropy searches and explicit configurational statistics.

GOAT and CREST count rotamers differently and CREST adds an ensemble RRHO
correction. Native values remain separately labelled; hit counts never become
physical degeneracies and finite sampling is not a proof of completeness.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Any, Callable
from uuid import uuid4

import numpy as np
from pydantic import Field
from scipy import constants
from scipy.special import logsumexp

from .engines import EngineParseError, _number, artifact_inventory
from .models import Contract, MethodSpec, Molecule, ResourceLimits, utc_now
from .sampling import SamplingResult
from .science import HARTREE_J, KB_HARTREE_K, geometry_digest
from .storage import IntegrityError, atomic_json, digest_json, file_digest

GOAT_MANUAL = "https://www.faccts.de/docs/orca/6.1/manual/contents/structurereactivity/goat.html"
CREST_SOURCE = "https://github.com/crest-lab/crest/blob/v3.0.2/src/entropy/entropy.f90"
_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"
SAMPLING_TIMING_SCOPE = "UTC wall clock around sampling adapter dispatch, including prelaunch setup, version probes and evidence parsing"


def sampling_execution_timing(result: SamplingResult) -> tuple[str | None, str | None]:
    """Retain original dispatch boundaries; undated historical evidence stays undated."""
    timing = result.metadata.get("execution_timing")
    if timing is None:
        return None, None
    try:
        start, finish = timing["started_at"], timing["finished_at"]
        first, last = datetime.fromisoformat(start), datetime.fromisoformat(finish)
        if (set(timing) != {"started_at", "finished_at", "scope"}
                or timing["scope"] != SAMPLING_TIMING_SCOPE
                or first.utcoffset() != timedelta(0) or last.utcoffset() != timedelta(0) or last < first):
            raise ValueError("Invalid UTC dispatch boundary")
    except (KeyError, TypeError, ValueError) as exc:
        raise IntegrityError("Native sampling has invalid recorded execution wall-clock timing") from exc
    return start, finish


class EntropyOptions(Contract):
    temperature_k: float = Field(default=298.15, gt=0)
    energy_window_kcal_mol: float = Field(default=12, gt=0)
    goat_min_delta_s_cal_mol_k: float = Field(default=.1, gt=0)
    crest_entropy_growth_threshold: float = Field(default=.005, gt=0, lt=1)
    crest_conformer_growth_threshold: float = Field(default=.02, gt=0, lt=1)


def configurational_statistics(energies_hartree: list[float], temperature_k: float,
                               degeneracies: list[int], *, degeneracy_definition: str) -> dict[str, Any]:
    """Canonical electronic-energy conformer partition sum including explicit g.

    S=-R sum p_i log(p_i/g_i), relative F=-kT log sum g_i exp(-dE_i/kT).
    This excludes each conformer's intrinsic vibrational/rotational entropy.
    Degeneracies count states represented by a conformer, never sampling hits.
    """
    energies = np.asarray(energies_hartree, dtype=float)
    if (energies.ndim != 1 or len(energies) == 0 or not np.isfinite(energies).all()
            or not math.isfinite(temperature_k) or temperature_k <= 0
            or len(degeneracies) != len(energies) or not degeneracy_definition.strip()
            or any(isinstance(g, bool) or not isinstance(g, int) or g < 1 for g in degeneracies)):
        raise ValueError("finite energies, positive temperature, explicit integer degeneracies and definition required")
    delta = energies - energies.min()
    logg = np.log(np.asarray(degeneracies, dtype=float))
    logits = logg - delta / (KB_HARTREE_K * temperature_k)
    logz = float(logsumexp(logits))
    logp = logits - logz
    populations = np.exp(logp)
    entropy = float(-constants.R * np.sum(populations * (logp - logg)))
    u = float(populations @ delta)
    free = -KB_HARTREE_K * temperature_k * logz
    if not math.isclose(u - temperature_k * entropy / (HARTREE_J * constants.Avogadro), free, abs_tol=1e-12):
        raise ArithmeticError("configurational partition identities disagree")
    return {"temperature_k": temperature_k, "populations": populations.tolist(),
            "degeneracies": degeneracies, "degeneracy_definition": degeneracy_definition,
            "energy_definition": "electronic conformer energies; no intrinsic thermal terms",
            "reference_energy_hartree": float(energies.min()), "relative_internal_energy_hartree": u,
            "relative_configurational_free_energy_hartree": free,
            "configurational_entropy_j_mol_k": entropy, "log_relative_partition_sum": logz,
            "exhaustive": False, "formula": "p_i=g_i exp(-dE_i/kT)/Z; S=-R sum p_i ln(p_i/g_i)"}


def parse_goat_entropy(text: str, temperature_k: float) -> dict[str, Any]:
    entropies = re.findall(r"Sconf at\s+(" + _FLOAT + r")\s+K\s*:\s*(" + _FLOAT + r")\s+cal/\(molK\)", text)
    frees = re.findall(r"Gconf at\s+(" + _FLOAT + r")\s+K\s*:\s*(" + _FLOAT + r")\s+kcal/mol", text)
    if not entropies or not frees or any(abs(_number(rows[-1][0]) - temperature_k) > .0051 for rows in (entropies, frees)):
        raise EngineParseError("GOAT entropy temperature, units or final quantities missing")
    entropy = _number(entropies[-1][1])
    if entropy < -1e-8:
        raise EngineParseError("negative GOAT configurational entropy")
    # Global iteration tables are cumulative; retain each iteration once and
    # reject conflicting duplicate rows instead of double-counting history.
    trajectory = {}
    for row in re.findall(r"(?m)^\s*(\d+)\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s+(" + _FLOAT + r")\s*$", text):
        i, energy, s, g = int(row[0]), *[_number(v) for v in row[1:]]
        values = {"iteration": i, "minimum_energy_hartree": energy, "sconf_cal_mol_k": s, "gconf_kcal_mol": g}
        if i in trajectory and trajectory[i] != values:
            raise EngineParseError("conflicting GOAT entropy iteration evidence")
        trajectory[i] = values
    if not trajectory:
        raise EngineParseError("GOAT entropy lacks its convergence trajectory")
    return {"temperature_k": temperature_k, "sconf_cal_mol_k": entropy,
            "gconf_kcal_mol": _number(frees[-1][1]), "trajectory": [trajectory[k] for k in sorted(trajectory)],
            "sampling_converged": bool(re.search(r"Global minimum found\s*!", text, re.I)),
            "definition": "native GOAT CONFDEGEN auto conformer/rotamer statistics; see native table",
            "includes_intrinsic_rrho": False, "exhaustive": False, "reference": GOAT_MANUAL}


def parse_crest_entropy(text: str, temperature_k: float = 298.15) -> dict[str, Any]:
    headers = list(re.finditer(r"FINAL MOLECULAR ENTROPY AT T=\s*(" + _FLOAT + r")\s*K", text))
    if not headers or abs(_number(headers[-1][1]) - temperature_k) > .0051:
        raise EngineParseError("CREST final entropy or requested temperature missing")
    block = text[headers[-1].end():]
    if "(cal mol⁻¹ K⁻¹)" not in block or "(kcal mol⁻¹)" not in block:
        raise EngineParseError("CREST native entropy/free-energy units are not established")
    fields = {
        "sconf_cal_mol_k": r"Sconf\s*=\s*(" + _FLOAT + ")",
        "delta_srrho_cal_mol_k": r"δSrrho\s*=\s*(" + _FLOAT + ")",
        "total_entropy_cal_mol_k": r"S\(total\)\s*=\s*(" + _FLOAT + ")",
        "relative_enthalpy_kcal_mol": r"H\(T\)-H\(0\)\s*=\s*(" + _FLOAT + ")",
        "relative_gibbs_kcal_mol": r"G\(total\)\s*=\s*(" + _FLOAT + ")",
    }
    result: dict[str, Any] = {}
    for key, pattern in fields.items():
        match = re.search(pattern, block)
        if match is None:
            raise EngineParseError(f"CREST entropy component missing: {key}")
        result[key] = _number(match[1])
    if (abs(result["sconf_cal_mol_k"] + result["delta_srrho_cal_mol_k"] - result["total_entropy_cal_mol_k"]) > 2e-6
            or abs(result["relative_enthalpy_kcal_mol"] - temperature_k * result["total_entropy_cal_mol_k"] / 1000
                   - result["relative_gibbs_kcal_mol"]) > 2e-6):
        raise EngineParseError("CREST entropy components violate printed thermodynamic identities")
    counts = re.findall(r"Containing\s+(\d+)\s+conformers\s*:[\s\S]*?S\(conf\)\s+(" + _FLOAT + ")", text)
    conf_conv = re.findall(r"Convergence w\.r\.t\. conformers:\s*([TF])", text)
    entropy_conv = re.findall(r"Convergence w\.r\.t\. entropy\s*:\s*([TF])", text)
    if not counts:
        raise EngineParseError("CREST entropy convergence trajectory missing")
    result.update(temperature_k=temperature_k, trajectory=[{"conformers": int(n), "sconf_cal_mol_k": _number(s)} for n, s in counts],
                  sampling_converged=bool(conf_conv and entropy_conv and conf_conv[-1] == entropy_conv[-1] == "T"),
                  extrapolated="FINAL ENTROPY (extrapol.)" in text,
                  definition="native CREST conformer/rotamer entropy with ensemble delta-RRHO correction; not absolute molecular RRHO entropy",
                  includes_intrinsic_rrho=True, exhaustive=False, reference=CREST_SOURCE)
    return result


def run_matched_entropy(seeds: list[Molecule], method: MethodSpec, resources: ResourceLimits,
                        workdir: str | Path, *, options: EntropyOptions | None = None,
                        orca_executable: str | Path | None = None, crest_executable: str | Path | None = None,
                        xtb_executable: str | Path | None = None, process_runner: Callable[..., Any] | None = None,
                        cancel_event: Event | None = None) -> dict[str, Any]:
    """Run GOAT-ENTROPY and CREST entropy from every identical declared seed.

    Complete native searches survive recovery; incomplete searches restart in
    fresh native directories because neither adapter claims partial recovery.
    CREST 3.0.2's native stopping criterion is evaluated at 298.15 K; this
    paired protocol therefore requires that explicit shared temperature.
    """
    from .goat import run_goat
    from .sampling import run_crest

    started = time.monotonic()
    options = options or EntropyOptions()
    if not seeds or options.temperature_k != 298.15 or (method.engine, method.method) != ("xtb", "GFN2-xTB") or method.constraints:
        raise ValueError("paired native entropy requires explicit seeds, unconstrained GFN2-xTB and shared 298.15 K")
    identity = seeds[0].model_dump(exclude={"coordinates"})
    if any(seed.model_dump(exclude={"coordinates"}) != identity for seed in seeds):
        raise ValueError("matched entropy seeds must preserve complete chemical identity and atom mapping")
    folder = Path(workdir).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    binaries = {"orca": orca_executable, "crest": crest_executable, "xtb": xtb_executable}
    identities = {}
    for name, executable in binaries.items():
        import os

        binary = shutil.which(str(executable) if executable is not None else os.environ.get(f"TOPOS_{name.upper()}_EXECUTABLE", name))
        identities[name] = {"path": str(Path(binary).resolve()), "sha256": file_digest(Path(binary))} if binary else None
    protocol = {"schema": "topos-matched-native-entropy/0.1.0", "seeds": [m.model_dump(mode="json") for m in seeds],
                "method": method.model_dump(mode="json"), "options": options.model_dump(mode="json"),
                "resources": resources.model_dump(exclude={"budget_seconds"})}
    path = folder / "protocol.json"
    if path.exists():
        if json.loads(path.read_text()) != protocol:
            raise IntegrityError("matched entropy recovery protocol changed")
    elif any(folder.iterdir()):
        raise IntegrityError("matched entropy folder contains unverified evidence")
    else:
        atomic_json(path, protocol)
    # Provisioning a formerly missing licensed engine must not invalidate a
    # completed independent CREST stage. Once established, each binary identity
    # is immutable for this protocol, including its configured path.
    resolved_path = folder / "resolved-executables.json"
    if resolved_path.exists():
        previous = json.loads(resolved_path.read_text())
        for name, identity in previous.items():
            if identity is not None and identity != identities.get(name):
                raise IntegrityError("an established entropy executable identity changed")
    atomic_json(resolved_path, identities)
    results = []
    for seed_index, seed in enumerate(seeds):
        for engine in ("goat", "crest"):
            key = f"seed-{seed_index:04d}-{engine}"
            receipt = folder / (key + ".json")
            sampled = None
            reused = False
            if receipt.exists():
                saved = json.loads(receipt.read_text())
                candidate = SamplingResult.model_validate(saved["result"])
                timing = sampling_execution_timing(candidate)
                if ("result_sha256" in saved and digest_json(saved["result"]) != saved["result_sha256"]
                        or timing[0] is not None and "result_sha256" not in saved):
                    raise IntegrityError("Entropy result or its recorded timing identity changed")
                if candidate.status == "completed":
                    if candidate.metadata.get("execution_kind") != "real" or not candidate.artifacts or "native_entropy" not in candidate.metadata:
                        raise IntegrityError("completed entropy receipt lacks native execution evidence")
                    for artifact in candidate.artifacts:
                        raw = Path(artifact.path)
                        if not raw.resolve().is_relative_to(folder) or raw.is_symlink() or not raw.is_file() or file_digest(raw) != artifact.sha256:
                            raise IntegrityError("completed entropy artifact changed")
                    sampled, reused = candidate, True
            if sampled is None:
                remaining = resources.budget_seconds - (time.monotonic() - started)
                if remaining <= 0 or cancel_event is not None and cancel_event.is_set():
                    return {"status": "cancelled" if cancel_event is not None and cancel_event.is_set() else "timed-out",
                            "results": results, "protocol": protocol, "resolved_executables": identities, "artifacts": [a.model_dump(mode="json") for a in artifact_inventory(folder)]}
                # Reserve an equal share for each remaining native job; failed
                # jobs never borrow a future seed's entire allocation.
                limits = resources.model_copy(update={"budget_seconds": remaining / (2 * len(seeds) - len(results))})
                native = folder / (key + "-" + uuid4().hex)
                invocation_started_at = utc_now()
                if engine == "goat":
                    sampled = run_goat(seed, method, limits, native, executable=orca_executable, xtb_executable=xtb_executable,
                                       energy_window_kcal_mol=options.energy_window_kcal_mol,
                                       entropy_options={"temperature_k": options.temperature_k,
                                                        "min_delta_s_cal_mol_k": options.goat_min_delta_s_cal_mol_k},
                                       process_runner=process_runner, cancel_event=cancel_event)
                else:
                    sampled = run_crest(seed, method, limits, native, executable=crest_executable, xtb_executable=xtb_executable,
                                        profile="crest-entropy-v1", energy_window_kcal_mol=options.energy_window_kcal_mol,
                                        entropy_options={"temperature_k": options.temperature_k,
                                                         "entropy_growth_threshold": options.crest_entropy_growth_threshold,
                                                         "conformer_growth_threshold": options.crest_conformer_growth_threshold},
                                        process_runner=process_runner, cancel_event=cancel_event)
                sampled.metadata["execution_timing"] = {
                    "started_at": invocation_started_at, "finished_at": utc_now(), "scope": SAMPLING_TIMING_SCOPE}
                sampling_execution_timing(sampled)
                payload = sampled.model_dump(mode="json")
                atomic_json(receipt, {"result": payload, "result_sha256": digest_json(payload)})
            results.append({"seed_index": seed_index, "seed_geometry_sha256": geometry_digest(seed), "engine": engine,
                            "reused_completed": reused, "result": sampled.model_dump(mode="json")})
    return {"status": "completed" if all(row["result"]["status"] == "completed" for row in results) else "partial",
            "results": results, "protocol": protocol, "resolved_executables": identities, "artifacts": [a.model_dump(mode="json") for a in artifact_inventory(folder)],
            "provenance": {"seed_matching": "identical input geometries; native random streams are independent",
                           "comparison": "native definitions retained separately; no pooled entropy or inferred degeneracies",
                           "exhaustive": False}}
