# BASE-managed isolated TOPOS integration

This integration revision starts from TOPOS `cf5655158456d763453376b108d26efcd748fe4f`
and preserves its scientific solvers, CFOUR controlled-dependency evidence, and
scientific-only export policy. It restores the independently verified TORQ
sidecar and XYZ byte-order-mark handling from
`f63249fa32c5350bd53d285758994c9ebc7154eb`.

The declared BASE dependency is `>=1.0.1,<2`. BASE installs its explicitly reviewed
science revision into TOPOS's interpreter and records the actual source, wheel,
installed file identities, dependency consistency and runtime qualification.
This version range does not establish compatibility or scientific acceptance
by itself. BASE must qualify the exact selected immutable revision.

TORQ remains a mandatory ecosystem component. BASE installs it in a separate
interpreter because combining its shared namespaces with BASE can overwrite
BASE's execution context. TOPOS independently verifies the supplied sidecar's
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
