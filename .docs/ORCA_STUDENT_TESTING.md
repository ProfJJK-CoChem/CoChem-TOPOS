# Provision ORCA for private CoChem integration tests

This is the selected deployment: **a private GitHub Release in the same controlled repository as the CoChem test workflow**, shared with the instructor's authorized student group. The runner uses its automatic, temporary `GITHUB_TOKEN` with `contents: read` to retrieve one reviewed asset. The workflow explicitly passes that token to the installer in the download step; it is excluded from the solver's environment. No additional storage service or manually managed download token is needed.

This procedure prepares actual CoChem installation and integration tests. The [June 2025 EULA assessment](ORCA_LICENSE_RESEARCH.md) describes the remaining license-scope questions, including hosted transfers and DATA use. `ORCA_CLOUD_LICENSE_CONFIRMED` records the responsible operator's determination under the applicable agreement; repository privacy and the testing purpose are not themselves licensor authorization.

## 1. Prepare the repository and group

- Confirm the **controller repository is private before uploading ORCA**. All repositories containing restricted ORCA results should have the intended access controls as well.
- Limit controller membership to people authorized to receive the ORCA distribution. **Every repository reader can download its Release assets.** Environment approvals protect this workflow's execution, not asset visibility to repository readers.
- For instructor-controlled testing, use an **organization-owned repository** to give students the Read role and have the instructor dispatch runs. Personal private-repository collaborators generally receive write access rather than a selectable read-only role. Read-only students cannot normally dispatch workflows. A teacher-only controller with separate student repositories is another access model. Review student code before bringing it onto the controller's default branch.
- Protect the default branch and workflow changes. Configure the `orca-licensed` environment with deployment restricted to that branch, where the account plan supports those protections. If the same instructor dispatches and approves, leave prevention of self-review disabled; enable it only with a second authorized reviewer. Confirm the configured rules are enforced. Private-environment availability and reviewer features depend on the GitHub plan; do not assume naming an environment enables them.
- Place the reviewed TOPOS implementation, [workflow](../.github/workflows/orca_hosted.yml), [installer](../scripts/install_orca.py), [worker](../topos/actions/hosted_worker.py), and [smoke request](../examples/orca-water-energy.json) in a committed revision on that default branch. A local working copy does not make the workflow available in GitHub Actions.

## 2. Upload the complete authorized distribution

Download the **complete ORCA 6.1.1 Linux x86-64 distribution** through the authorized ORCA channel. Preserve helper executables and libraries. Record the exact filename, shared/static variant, CPU requirements and MPI/runtime version stated by that distribution. The initial test runs serially, but shared-library requirements still apply.

The installer accepts tar, tar.gz, tar.xz and tar.bz2. Its current extractor rejects symlinks and hardlinks; actual compatibility cannot be established before inspecting the vendor archive. If links are present, stop and review support for that distribution; do not remove dependencies or modify the package merely to make extraction pass.

GitHub requires each Release asset to be **under 2 GiB** ([official release documentation](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)). If the complete compressed distribution exceeds that limit, this single-asset path needs revision. Do not upload only the driver or drop necessary files to fit.

Compute SHA-256 on the legitimately obtained archive **before uploading**. On Linux:

```bash
sha256sum /path/to/your-orca-archive.tar.xz
```

On Windows PowerShell:

```powershell
Get-FileHash 'C:\Downloads\your-orca-archive.tar.xz' -Algorithm SHA256
```

In the private controller repository, open **Releases → Draft a new release**. Use a dedicated tag such as `orca-runtime-6.1.1`, attach the complete archive, and publish the release within that private repository. The release can be marked as a prerelease to distinguish this runtime asset from CoChem software releases. Avoid marking it as the latest CoChem release. Keep the EULA and third-party notices supplied with the archive intact.

Record the numeric asset ID. With GitHub CLI authenticated as a repository member, replace `OWNER/REPOSITORY` and run:

```bash
gh api repos/OWNER/REPOSITORY/releases/tags/orca-runtime-6.1.1 \
  --jq '.assets[] | {id, name, size}'
```

Select the ID belonging to the exact archive you hashed. The workflow pins the **asset ID plus SHA-256**, not a mutable filename or a "latest release" lookup. Replacing the asset requires reviewing both settings again.

## 3. Configure three environment variables

Open **Settings → Environments → orca-licensed → Environment variables** and configure:

| Variable | Value |
| --- | --- |
| `ORCA_611_ASSET_ID` | Numeric ID of the reviewed archive asset in this same repository. |
| `ORCA_611_SHA256` | Full 64-character SHA-256 computed from the authorized archive. |
| `ORCA_CLOUD_LICENSE_CONFIRMED` | `true` when the responsible licensee/institution has established that the applicable agreement covers the deployment and users. |

GitHub supplies the job token automatically. The selected workflow does not require an `ORCA_611_ARCHIVE_URL` secret. The installer retains an explicitly selected HTTPS-URL mode for other deployments; the two download sources are not combined or used as automatic fallbacks.

## 4. Run the first integration test

Open **Actions → Licensed ORCA 6.1.1 hosted smoke calculation → Run workflow**, select the default branch, and complete the configured environment review for that revision.

The job:

1. Checks the private repository, default branch and configured variables.
2. Downloads the pinned asset using the job token; a permitted GitHub release-CDN redirect receives no token or authorization header.
3. Verifies the archive hash, installs in the runner's temporary directory and checks ORCA's actual reported version through a separate serial diagnostic.
4. Executes the reviewed water HF-3c energy request: one thread, 2048 MiB and a 120-second calculation budget.
5. Uploads only the worker receipt and verified calculation evidence, with seven-day retention, and attempts cleanup of temporary installation and scratch files.

Inspect `worker-receipt.json` in the `orca-evidence-RUN_ID-ATTEMPT` artifact and the corresponding scientific snapshot. Success requires actual completed/converged ORCA 6.1.1 energy evidence and passing integrity checks. Installation, artifact upload or a diagnostic calculation alone does not establish that the requested calculation succeeded. Cancellation cleanup is best effort; it does not imply guaranteed secure erasure by the provider.

Once that passes, expand test coverage to gradients, optimization and selected method-matrix cases with declared reference criteria. MPI tests require the runtime matching the exact ORCA distribution and separate observed validation.

## Current readiness

The [private-Release validation receipt](ORCA_PRIVATE_RELEASE_VALIDATION.json) records 132 passing local installer/worker tests and successful Python/workflow linting. These exercise infrastructure contracts and failure paths without a licensed archive or simulated scientific success.

The source changes provide the provisioning path; no private Release asset has been uploaded, repository visibility changed, hosted job dispatched, or licensed ORCA calculation validated by this task. The remaining concrete inputs are the archive's filename/build/size, its upload and asset ID, reviewed SHA-256, applicable license determination, and the committed private-controller configuration. Detailed installation and publication constraints remain in the [deployment guide](ORCA_GITHUB_ACTIONS.md).
