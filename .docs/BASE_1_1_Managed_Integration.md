# BASE-managed isolated TOPOS integration

TOPOS accepts an independently verified TORQ sidecar in a BASE-managed
deployment. Scientific solvers, controlled CFOUR dependencies, and the
scientific-only export policy use the same validation as other deployments.
Windows XYZ encoding signatures are retained in the immutable handoff while
the receiver parses the molecular coordinates.

The declared BASE dependency is `>=1.0.1,<2`. BASE installs its explicitly reviewed
science revision into TOPOS's interpreter and records the actual source, wheel,
installed file identities, dependency consistency and runtime qualification.
This version range does not establish compatibility or scientific acceptance
by itself. BASE must qualify the exact selected immutable revision.

TORQ remains a mandatory ecosystem component. A BASE deployment using this
route installs TORQ in a separate interpreter and supplies
`COCHEM_TORQ_SIDECAR`. Combining shared namespaces can overwrite BASE's
execution context. TOPOS independently verifies the supplied sidecar's
actual installation receipt, source, wheel RECORDs and dependencies. An absent
or invalid TORQ installation still refuses execution. The optional
`standalone-ecosystem` extra permits an explicit combined installation; it is
not used or claimed qualified by the BASE-managed route.

Pinned QCElemental and QCEngine dependencies, the complete CFOUR runtime and
property-program checks, and both export-membership guards remain unchanged.
The standalone TOPOS release scripts retain their own BASE 1.0.1 and combined
environment assumptions. BASE-managed interoperability checks do not qualify
those separate release scripts.

Students obtain only BASE and use its interface. They neither install TOPOS
directly nor configure sidecars. ORCA and CFOUR remain optional; genuine missing
engine or unvalidated scientific capabilities remain unavailable.

This document describes the integration contract. Actual review, installed-wheel,
receiver/export, native-calculation and student-platform evidence must be
recorded separately; no pending check is a passed calculation or release.
