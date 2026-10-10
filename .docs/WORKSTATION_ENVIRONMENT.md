# Lab workstation calculation environment

`calculation_environment: "workstation"` queues a TOPOS request to the lab
workstation through a Google Drive folder the user assigns. The workstation's
[job runner](https://github.com/ProfJJK-CoChem/cochem_workstation_job_runner)
runs it with its `topos_run` template (`python -m topos run --request
request.json --output-root runs`) when its owner is not using the machine.

* **Submit** (`Workflow.run`) deposits the request with
  `calculation_environment` set to `local` for the worker and returns at once
  with a `queued` record (`execution_kind = "workstation-request"`). Jobs may
  wait for hours; nothing blocks.
* **Resume** (`Workflow.resume`, the app's "Check the workstation now" or
  "Resume saved calculation") polls `jobs/<label>/status.json`, records the
  workstation state, queue position, adjustments, progress and output tail in
  `metadata.workstation_dispatch`, and never re-submits.
* **Import** happens only when the archive matches its published SHA-256, the
  workstation's Ed25519 **signature** verifies against a key you trust and names
  this submission, the exact worker request bytes and that archive, the
  runner's summary agrees, the worker's RunStore snapshot verifies, and its
  request equals the submitted one. Results that are unsigned, signed by an
  unknown key or for something else are not imported; the run keeps waiting
  (with the reason in its status), so trusting the right key later still
  imports them. Artifacts are copied with the same verified-copy
  rules as GitHub Actions results; the run becomes
  `execution_kind = "verified-workstation-result"`.

## Trusting the workstation

The workstation owner prints the key fingerprint with `cochem-runner key`.
Enter it as **Workstation key** in the app's "Lab workstation" expander
(`SystemConfig.workstation_trusted_keys`), or set `TOPOS_WORKSTATION_TRUSTED_KEYS`
/ `COCHEM_WORKSTATION_TRUSTED_KEYS` (comma-separated); keys trusted in
CoChem-BASE's Lab workstation panel are trusted too.

## Choosing the folder

Nothing is hard-coded. In order of precedence: `SystemConfig.workstation_folder`
/ `workstation_student_id` (the app's "Lab workstation (Drive folder queue)"
expander), `TOPOS_WORKSTATION_FOLDER` / `TOPOS_WORKSTATION_STUDENT`,
`COCHEM_WORKSTATION_FOLDER` / `COCHEM_WORKSTATION_STUDENT`, then the folder
assigned in CoChem-BASE's Lab workstation panel. A synced folder path works
directly; a drive.google.com link uses CoChem-BASE's Drive API transport.

Code: `topos/workstation.py`; hooks in `workflow.py`, `ingestion.py`,
`config.py` and `ui.py`. Tests: `tests/test_workstation_backend.py` (the worker
record is a genuine `python -m topos run` result).
