# BASE-managed isolated TOPOS and TORQ

TOPOS molecular execution still requires BASE and a real installed TORQ. These
components must have distinct interpreter environments when their wheel files
overlap. TORQ's current wheel owns `cochem` and `Libraries` names that are also
owned by BASE; installing it over BASE can replace execution authority and fails
strict wheel RECORD verification.

TOPOS therefore declares `CoChem-BASE>=1.0.1,<2`, while BASE supplies TORQ through
the independently verified `cochem.module-sidecar/1` contract. This is not an
optional TORQ dependency or a substitute distribution. The contract identifies
the real module installation root, its reviewed specification and the exact
SHA-256 of its installation receipt. TOPOS independently invokes BASE's strict
installation verifier, checking the pinned source, interpreter environment,
dependency consistency and every wheel RECORD before admitting scientific work.

BASE creates the sidecar from its verified receipt and passes it explicitly to
the reviewed TOPOS adapter. The adapter supplies `COCHEM_TORQ_SIDECAR` to the
isolated provider; inherited source-root overrides are removed. TORQ namespaces
are never imported into TOPOS's BASE authority environment. The resulting run
provenance records the real separate source revision, environment hash and
receipt hash. BASE routes TORQ operations to its own verified interpreter.

This change preserves data-only BASE artifact ingestion and all native engine
authority. It does not claim that arbitrary TOPOS-to-TORQ scientific consumers
are implemented. A producer export or discovered sidecar does not establish a
scientific consumption receipt. The previous three-wheels-in-one-environment
release acceptance script must not be used as acceptance of this route: its
ownership collision checks remain in place. BASE's native student-route
acceptance separately checks the actual isolated installations and calculations.
