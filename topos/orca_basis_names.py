"""Exact, element-aware translation of scientific orbital labels to ORCA names.

ORCA's built-in seasonal correlation-consistent bases use the ``(X+d)``
spelling. The extra tight d function belongs to the second-row construction;
it does not change H--Ne. Mapping a bare second-row jun basis to that spelling
would change its orbital space and is deliberately not an alias here.
"""
from __future__ import annotations

import re
from typing import Any

from .models import Molecule

BASIS_SOURCE = "https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/basisset.html#correlation-consistent-basis-sets"
TIGHT_D_SOURCE = "https://doi.org/10.1063/1.1367373"
_FIRST_ROW = frozenset({"H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne"})


def resolve_orca_orbital_basis(molecule: Molecule, requested_basis: str) -> dict[str, Any]:
    """Return an explicit naming receipt; never substitute a different basis.

    This maps names only. Separate role/element validation establishes whether
    ORCA provides the requested orbital, fitting and CABS sets for every atom.
    Native acceptance still requires a successful real engine calculation.
    """
    elements = sorted(set(molecule.symbols))
    receipt = {"requested_basis": requested_basis, "native_basis": requested_basis,
               "mapping": "native-keyword", "elements": elements,
               "orbital_space_changed": False, "sources": [BASIS_SOURCE]}
    if not requested_basis.startswith("jun-"):
        return receipt
    match = re.fullmatch(r"jun-cc-pV([DTQ])Z", requested_basis)
    if match is None:
        raise ValueError("ORCA 6.1 provides reviewed native jun orbital names only for D/T/Q zeta")
    unsupported = sorted(set(elements) - _FIRST_ROW)
    if unsupported:
        raise ValueError("Bare jun orbital bases for " + ", ".join(unsupported)
                         + " require an explicit exact basis definition; ORCA's (X+d) keyword is not an alias outside H-Ne")
    receipt.update(native_basis=f"jun-cc-pV({match[1]}+d)Z", mapping="exact-H-Ne-seasonal-name",
                   domain="H-Ne only; no extra second-row tight-d function is introduced",
                   sources=[BASIS_SOURCE, TIGHT_D_SOURCE])
    return receipt


# Role-specific availability from the retained official ORCA 6.1 manual.
SOURCE_URL = "https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/basisset.html"
SOURCE_HTML_SHA256 = "48750fa1c9dc25992c9e339648e52ef0f63423a7ad196e33b78609eb7143c4b6"
SOURCE_TEXT_SHA256 = "38151794dc6c7a3fd94f67de94515ea189c2b3b013f06984fcb250329d6a91ea"
ELEMENTS = tuple("H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr".split())


def _elements(domain: str) -> set[str]:
    selected = set()
    for item in domain.split(', '):
        if '–' in item:
            low, high = item.split('–')
            selected.update(ELEMENTS[ELEMENTS.index(low):ELEMENTS.index(high)+1])
        else:
            selected.add(item)
    return selected


# Each tuple is the literal element column and table number in the retained
# official manual. Lists are explicit where cardinalities have different scope.
BASIS_DOMAINS: dict[str, dict[str, tuple[str, str]]] = {
    "orbital": {
        "cc-pVDZ": ("H–Ar, Ca–Kr", "2.22"),
        "cc-pVTZ": ("H–Ar, Ca–Kr, Y, Ag, Au", "2.22"),
        "cc-pVQZ": ("H–Ar, Ca–Kr", "2.22"),
        "cc-pV5Z": ("H–Ar, Ca–Kr", "2.22"),
        "aug-cc-pVDZ": ("H–Ar, Sc–Kr", "2.22"),
        "aug-cc-pVTZ": ("H–Ar, Sc–Kr, Ag, Au", "2.22"),
        "aug-cc-pVQZ": ("H–Ar, Sc–Kr", "2.22"),
        "aug-cc-pV5Z": ("H–Ar, Sc–Kr", "2.22"),
        "cc-pwCVDZ": ("H–Ar, Ca, Ga–Kr", "2.22"),
        "cc-pwCVTZ": ("H–Ar, Ca–Kr, Ag, Au", "2.22"),
        "cc-pwCVQZ": ("H–Ar, Ca–Kr", "2.22"),
        "cc-pwCV5Z": ("H–Ar, Ca–Kr", "2.22"),
        **{f"cc-pV{n}Z-F12": ("H–Ar", "2.23") for n in ('D', 'T', 'Q')},
        **{f"jun-cc-pV({n}+d)Z": ("H–Ar", "2.22") for n in ('D', 'T', 'Q')},
        **{name: ("H–Rn", "2.14") for name in ('def2-SVP', 'def2-TZVP', 'def2-TZVPP', 'def2-QZVPP')},
    },
    "auxiliary_c": {
        "cc-pVDZ/C": ("H–Ar, Ga–Kr", "2.36"),
        "cc-pVTZ/C": ("H–Ar, Sc–Kr", "2.36"),
        "cc-pVQZ/C": ("H–Ar, Sc–Kr", "2.36"),
        "cc-pV5Z/C": ("H–Ar, Ga–Kr", "2.36"),
        **{name: ("H–Rn", "2.36") for name in ('def2-SVP/C', 'def2-TZVP/C', 'def2-TZVPP/C', 'def2-QZVPP/C')},
    },
    "auxiliary_jk": {
        **{f"cc-pV{n}Z/JK": ("H, B–F, Al–Cl, Ga–Br", "2.35") for n in ('T', 'Q', '5')},
        "def2/JK": ("H–Rn", "2.35"),
    },
    "auxiliary_j": {"def2/J": ("H–Lr", "2.34")},
    "cabs": {f"cc-pV{n}Z-F12-CABS": ("H, B–Ne, Al–Ar", "2.37") for n in ('D', 'T', 'Q')},
}


def validate_basis_elements(name: str, role: str, symbols: list[str]) -> dict:
    """Reject unverified native keywords or elements before any solver launch."""
    entry = BASIS_DOMAINS.get(role, {}).get(name)
    if entry is None:
        raise ValueError(f"ORCA 6.1 native {role} keyword {name!r} has no verified manual entry; no basis is substituted")
    domain, table = entry
    absent = sorted(set(symbols) - _elements(domain))
    if not symbols or absent:
        raise ValueError(f"ORCA 6.1 {role} {name} is documented for {domain}; unsupported requested elements: {', '.join(absent) or 'empty molecule'}")
    return {"native_keyword": name, "role": role, "requested_elements": sorted(set(symbols)),
            "documented_elements": domain, "source_url": SOURCE_URL, "source_table": table,
            "source_html_sha256": SOURCE_HTML_SHA256, "source_text_sha256": SOURCE_TEXT_SHA256,
            "evidence_kind": "official manual preflight; native execution remains independently required"}
