# ORCA 6.1.1 on GitHub-hosted Actions

This deployment runs TOPOS and the ORCA executable **inside an actual GitHub-hosted Linux job**. It starts with a serial HF-3c water single-point calculation, using [the request file](../examples/orca-water-energy.json) and [the manual workflow](../.github/workflows/orca_hosted.yml). The initial limits are one thread, 120 seconds for the calculation workflow, and 2048 MB. A successful smoke calculation establishes that this particular installation and input worked; it does not validate all ORCA methods or the method matrix's time estimates.

The selected distribution source is now a **private GitHub Release in the same controlled repository**, shared with the authorized instructor/student group. Follow the [instructor provisioning steps](ORCA_STUDENT_TESTING.md) for archive upload, hashing, asset-ID lookup and repository configuration. Every repository reader can download Release assets; protected workflow environments do not narrow asset visibility.

**Current validation:** no licensed ORCA 6.1.1 execution has been tested by this setup task. This file and workflow provide a deployment procedure, not a successful calculation receipt. The TOPOS UI's remote-dispatch capability remains unavailable; manually starting this Actions workflow does not implement UI-to-Actions submission.

The earlier [local validation receipt](ORCA_HOSTED_VALIDATION.json) records **208 passing regression tests, zero failures/errors/skips**, source hashes, lint/dependency checks, workflow validation, and a successful wheel/source build before the private-Release download extension. Genuine xTB and CREST were used by their existing integration tests. ORCA-specific tests cover infrastructure and parser/failure contracts; no licensed ORCA calculation or hosted execution is claimed.

The subsequent [private-Release validation receipt](ORCA_PRIVATE_RELEASE_VALIDATION.json) records **132 passing local installer/worker tests** and Python/workflow linting after adding authenticated Release downloads. It does not establish vendor-archive compatibility or live ORCA execution.

The [June 2025 EULA assessment](ORCA_LICENSE_RESEARCH.md) evaluates the supplied five-page ORCA agreement, including installation, third-party access, data and software-use restrictions. It also identifies a separate GitHub restriction: its current Actions terms state that use is for developing and testing applications. The prepared smoke calculation tests CoChem's integration. Using Actions as a routine production chemistry backend requires assessing the applicable GitHub agreement in addition to obtaining ORCA permission; a private repository alone resolves neither issue.

## 1. Establish the applicable license permission

Use the terms accompanying **your ORCA 6.1.1 distribution** and your institution's agreement. Establish that they, or written permission from the licensor, cover all of the following before execution:

- Your intended academic, private, sponsored or commercial activity and the people entitled to use the installation.
- Uploading/copying the distribution to an authorized private archive and transferring it to GitHub-hosted runners.
- Execution on a third-party managed cloud service, including access by its operators and any automated/AI agents used in your workflow.
- Any retention, backup, snapshot or deletion conditions applicable to the archive and runner copies.

A private repository, private download URL or environment flag does **not** supply legal permission. Do not share a forum password, personal login session or license credentials with the repository or workflow. The workflow expects an authorized distribution archive, not credentials for bypassing the official download agreement.

The user-supplied **June 2025 EULA** has now been read. It defines SOFTWARE as ORCA version 4.0 or later and names **MPI/SGK** as the licensor. Section 3 permits installation and necessary copies, while §§3(a/i) restrict third-party availability and out-of-scope transfers. It contains no explicit cloud-provider exception or blanket cloud prohibition. Whether this hosted deployment falls within the permitted scope remains unresolved; consult the applicable licensor or authorized licensing representative for a precise interpretation or additional terms. Receiving the PDF does not authorize enabling the workflow.

The [method matrix, §11.1](../wiki/Method_Matrix.md#111-orca) relies on older EULA copies; its personal-Codespaces comments are not a license determination. Official ORCA destinations include [FACCTs](https://www.faccts.de/orca/) and the [ORCA Forum](https://orcaforum.kofo.mpg.de/), but FACCTs is not named in the supplied agreement. Verify the representative's authority and the actual terms of any separate license. The [ORCA manual](https://www.faccts.de/docs/orca/6.1/manual/) does not replace the agreement.

Sections 3(c–g) also constrain outputs and their use: journal publication is expressly permitted; database sharing carries noncommercial, notice and §7-disclaimer requirements; §3(e) broadly addresses software using ORCA DATA. CoChem's Apache-2.0 source declaration does not resolve those contractual obligations. The current exporter does not enforce ORCA-specific dataset licenses or insert the required notices, and its ORCA reference list still needs §5's citation (DOI `10.1002/wcms.70019`). Resolve these gaps and the scope of private provider-hosted artifacts before distribution; see the assessment for clause/page references.

If the agreement does not resolve this deployment, the following is a query **you can send** to the licensor or your institution's license administrator; this setup has not sent it:

> I hold ORCA 6.1.1 under [identify the agreement and licensed institution/user]. May our specified academic group store a private distribution archive and run CoChem development/integration tests on ephemeral GitHub-hosted Linux Actions runners? Please clarify §§1(g), 3(a/b/i) for the transfers, provider/operator/agent access, authorized users and retention. CoChem's independently authored source is Apache-2.0; how does §3(e) apply to its parsers, workflows, regression fixtures and downstream users? Which private artifact, journal-supplement and dataset-sharing arrangements satisfy §§3(c–g)? Please confirm the applicable interpretation or identify a license/addendum that covers this arrangement.

Until this is resolved, keep the workflow disabled or its license-confirmation variable unset. An existing licensed workstation/HPC installation remains an alternative only within its own applicable terms; inputs and outputs can be exchanged where their rights allow it.

## 2. Prepare the private controller and protected environment

1. Use a **private controller repository** containing the reviewed TOPOS source and workflow. If the development repository is public, put the reviewed controller code in a separate private repository. Store the authorized archive as a private Release asset in that controller; keep binaries out of tracked Git source. All controller readers must be intended authorized recipients of the archive. The workflow rejects a public controller repository.
2. Review and place the workflow on the controller's **default branch**. Only manual `workflow_dispatch` execution from that branch is intended. There is no pull-request trigger and no untrusted PR-code execution with these secrets. Protect workflow changes through the repository's review rules. Action dependencies are pinned to reviewed commit hashes in the workflow; updates require review.
3. Create the GitHub Actions environment **`orca-licensed`**. Restrict its deployment branches to the protected default branch and configure required reviewers where your plan supports them. If one instructor both dispatches and approves, leave prevention of self-review disabled; use a second authorized reviewer if that restriction is enabled. Confirm which rules are actually enforced: protection features on private repositories depend on the GitHub plan, and an environment's name alone is not an approval gate. If those controls are unavailable, review an instructor-only controller/dispatch design before changing the workflow; do not treat unsupported rules as enforced.
4. Set the environment variables below. Store the license authorization/evidence through your institution's appropriate process; the boolean is only the workflow's operator confirmation that this review occurred. GitHub supplies the download token automatically.

| Name | GitHub environment setting | Value and purpose |
|---|---|---|
| `ORCA_CLOUD_LICENSE_CONFIRMED` | Variable | Set to the exact string `true` **only after** the applicable terms or written permission cover this deployment. The value grants no rights itself. |
| `ORCA_611_SHA256` | Variable | Reviewed SHA-256 of the complete authorized ORCA 6.1.1 archive. Obtain it from a trusted distribution manifest or independently hash the legitimately obtained archive and retain its provenance. A matching checksum alone does not establish its license or origin. |
| `ORCA_611_ASSET_ID` | Variable | Numeric ID of that archive's private Release asset in the same repository. Pin the exact asset rather than resolving a mutable "latest" release. |

The download step receives the automatic `GITHUB_TOKEN` with `contents: read`. The installer authenticates only to GitHub's fixed Release-asset API endpoint. It accepts a direct response or one inspected HTTPS redirect to the explicitly allowed GitHub Release CDN, with authorization removed from the redirected request. The token and signed redirect URL are not saved or logged, and the token is not passed to the scientific solver. Do not disable checksum or TLS verification to make a failed download work.

The installer retains a separate direct-HTTPS source mode using `ORCA_611_ARCHIVE_URL`; that mode rejects redirects and is not selected by this workflow. It is an explicit alternative for other deployments, not a fallback if the pinned private Release asset is missing or inaccessible.

GitHub's official guidance explains [deployment environments and protection rules](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments), [manual workflow runs](https://docs.github.com/en/actions/using-workflows/manually-running-a-workflow), and [Actions security hardening](https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions). These platform references do not establish ORCA license permission.

## 3. Supply the complete compatible distribution

Obtain the **complete ORCA 6.1.1 Linux x86-64 distribution** through an authorized channel. Keep its helper executables, libraries and directory relationships intact; uploading only the `orca` driver is insufficient. Select the build for the actual hosted CPU's instruction-set support and the distribution's documented runtime requirements. Record the distribution filename, checksum and required runtime versions.

The [installer](../scripts/install_orca.py) supports uncompressed tar, `.tar.gz`, `.tar.xz` and `.tar.bz2` archives. It preserves regular files and directory structure but intentionally **rejects every symlink and hardlink**. If the vendor archive contains links, inspect the distribution and review appropriate installer support before proceeding. Do not remove links or silently omit their dependency contents merely to make extraction pass. Compatibility with the actual licensed distribution remains unverified because that archive has not been supplied.

Installation uses a fresh destination strictly beneath `RUNNER_TEMP`, with limits of **4 GiB downloaded**, **12 GiB expanded content**, **100,000 members** and **512 MiB free-disk reserve**. The installer verifies the archive's SHA-256 identity; it does not run bundled scripts or executables. Its `expected_version: "6.1.1"` metadata is an expectation, not measured version evidence.

After installation, `TOPOS_ORCA_EXECUTABLE` points to the resolved executable. The calculation worker obtains a real ORCA version diagnostic and requires **6.1.1**, then executes the reviewed smoke request. No ORCA archive, executable, library tree, container layer or installation cache belongs in Git or an uploaded result artifact. The workflow does not distribute a prebuilt ORCA container or use a shared installation cache.

The initial calculation is serial. This avoids introducing parallel-launch configuration into the first test, but does not guarantee the chosen ORCA distribution has no shared-runtime dependencies. Do not fix a library failure by installing an arbitrary “latest MPI” package. Identify the exact package's requirements from its authorized documentation first. A later parallel workflow needs a tested compatible MPI/runtime, explicit rank/thread/memory limits and its own execution evidence. Do not assume ordinary GitHub-hosted CPU runners provide a CUDA GPU or match the matrix's workstation benchmarks.

## 4. Run and inspect the evidence

1. Open the private controller's **Actions** tab and select the manual ORCA workflow. Select the default branch and run it. Complete any configured environment-review gate.
2. The job validates the repository/branch controls, operator confirmation and archive checksum; installs the complete authorized distribution; obtains the exact engine version; and runs the water HF-3c request inside that job. Both TOPOS and ORCA execute on the Actions runner.
3. Inspect the job's actual execution receipt and retained scientific outputs. Check the Actions run identity/source revision, resolved ORCA version, requested and executed method, input, command, process termination, raw output membership/checksums and parsed energy/convergence status. An Actions submission, available executable or successfully uploaded artifact is not a passed calculation.
4. An unavailable engine, rejected version, failed checksum, missing library, timeout or failed calculation remains a failure. Do not substitute xTB, Lennard-Jones or another ORCA method to obtain a green smoke result.

Download only the workflow's designated calculation/receipt artifacts through the private repository's access controls; review their contents and retention according to institutional policy. Do not broaden upload paths to the runner's installation, home, temporary parent directory or archive. Keep private binaries and download credentials outside scientific bundles. The workflow's cleanup and runner lifecycle reduce retention but do not replace the provider's actual retention terms or the license agreement.

After the smoke calculation passes, expand validation deliberately: gradient parsing and finite differences, optimization and declared convergence, then the selected method-matrix rows on representative systems. Recalibrate wall time on the actual hosted runner and preserve the distinction between a successful engine integration test and validated scientific accuracy.
