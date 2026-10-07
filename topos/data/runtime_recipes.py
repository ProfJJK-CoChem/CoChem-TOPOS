"""Compiled TOPOS matrix recipe identities, shared with hosted preflight."""

EXECUTABLE_ROWS = {
    "T1-1min", "T1-3h", "T1-12h", "T2-10s", "T2-30min", "T2-1h",
    "T1-10s", "T1-1h", "T1-3d", "T3O-10s", "T3O-1min", "T3O-30min", "T3O-1h", "T5-10s", "T5-1h",
    "T3O-12h", "T3O-3d", "T5-12h", "T5-1d", "T5-3d",
    "T1-1d", "T2-1min", "T5-1min",
    "T3C-30min", "T3C-1h", "T3C-3h", "T3C-12h", "T3C-1d", "T5-1mo",
    "T5-30min",
    "T1-1mo",
    "T5-1w",
    "T3C-3d",
    "T1-30min",
    "T3C-1w",
    "T1-1w",
    "T3O-1d", "T3O-1mo",
    "T5-3h",
    "T3O-1w",
    "T3O-3h",
}

# Native reference-energy branch is useful, but does not implement the row's
# alternative Molpro optimized reference geometry.
IMPLEMENTED_BRANCH_ROWS = {"T3O-1mo", "T3C-1mo"}
