"""Mandatory open-source CFOUR parser preflight; no native engine discovery/run."""
from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from .engines import EngineParseError

PARSER_VERSIONS = {"qcengine": "0.51.0", "qcelemental": "0.51.2"}


def require_cfour_parsers() -> tuple[Callable[..., Any], Callable[..., Any]]:
    """Return actual harvesters only after exact installed and imported checks.

    This is deliberately uncached: replacing/breaking a dependency between
    evaluations must fail before the next native calculation, not after it.
    """
    for name, expected in PARSER_VERSIONS.items():
        try:
            observed = version(name)
        except PackageNotFoundError as exc:
            raise EngineParseError(
                f"CFOUR parser dependency {name}=={expected} is missing; restore the reviewed TOPOS installation"
            ) from exc
        if observed != expected:
            raise EngineParseError(
                f"CFOUR parser dependency requires {name}=={expected}, found {observed}; restore the reviewed TOPOS installation"
            )
    try:
        modules = {name: import_module(name) for name in PARSER_VERSIONS}
        harvester = import_module("qcengine.programs.cfour.harvester")
        harvesters = (harvester.harvest_GRD, harvester.harvest_outfile_pass)
    except (ImportError, AttributeError, OSError, RuntimeError, ValueError) as exc:
        raise EngineParseError("CFOUR parser dependency import failed; restore the reviewed TOPOS installation") from exc
    for name, module in modules.items():
        if getattr(module, "__version__", None) != PARSER_VERSIONS[name]:
            raise EngineParseError(f"Imported {name} version differs from its pinned CFOUR parser distribution")
    if not all(callable(function) for function in harvesters):
        raise EngineParseError("CFOUR parser harvesting functions are unavailable")
    return harvesters
