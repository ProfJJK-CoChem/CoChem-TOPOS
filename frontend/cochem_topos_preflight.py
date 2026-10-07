"""Compatibility entry point to the shared typed chemistry validation.

The historical separate valency, radius, and isotope tables were removed so
that BASE and TOPOS cannot validate the same molecule differently.
"""
from typing import Any

from topos.models import Molecule, RunRequest


def validate_molecule(value: dict[str, Any] | Molecule) -> Molecule:
    values = value.model_dump(mode="json") if isinstance(value, Molecule) else value
    return Molecule.model_validate(values)


def validate_request(value: dict[str, Any] | RunRequest) -> RunRequest:
    values = value.model_dump(mode="json") if isinstance(value, RunRequest) else value
    return RunRequest.model_validate(values)


__all__ = ["validate_molecule", "validate_request"]
