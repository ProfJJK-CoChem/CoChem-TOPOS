"""Portable installation configuration; scientific requests remain explicit."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LOGGER = logging.getLogger("cochem.config")

# This is the explicitly retained, audited foundation compatibility revision,
# not an inference from an installed version or a claim about the newest BASE.
DEFAULT_REMOTE_BASE_COMMIT = "35f97a1b7a6a294f381b4a30780c5b3a766b537d"


class SystemConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    output_root: Path = Field(default_factory=lambda: Path.home() / "CoChem_Artifacts" / "TOPOS")
    executables: dict[str, str] = Field(default_factory=dict)
    max_threads: int = Field(default_factory=lambda: os.cpu_count() or 1, ge=1)
    max_memory_mb: int | None = Field(default=None, ge=64)
    execution_backend: Literal["base", "development"] = Field(
        default_factory=lambda: os.environ.get("TOPOS_EXECUTION_BACKEND", "base")
    )
    base_registry_path: Path | None = None
    remote_repository: str | None = None
    remote_ref: str = "main"
    remote_base_commit: str = Field(default=DEFAULT_REMOTE_BASE_COMMIT, pattern=r"^[0-9a-f]{40}$")
    remote_controller_profile: Literal["free", "legacy-topos-orca"] = "free"
    # Lab workstation queue: the user's assigned Drive folder (synced path or
    # drive.google.com link). Unset values fall back to the environment and to
    # the folder assigned in CoChem-BASE.
    workstation_folder: str | None = Field(default=None, max_length=1024)
    workstation_student_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    workstation_template: str = Field(default="topos_run", pattern=r"^[A-Za-z0-9_-]{1,64}$")
    # Fingerprints of the workstation keys whose signed results are imported
    # (`cochem-runner key` on the workstation); TOPOS_/COCHEM_WORKSTATION_TRUSTED_KEYS
    # and the keys trusted in CoChem-BASE are added to these.
    workstation_trusted_keys: list[str] = Field(default_factory=list, max_length=32)


def load_config(path: Path | str | None = None) -> SystemConfig:
    """Read an explicit or environment-selected registry without guessing old schemas."""
    chosen = Path(path or os.environ.get("TOPOS_CONFIG", "cochem_system_config.json"))
    if chosen.is_file():
        config = SystemConfig.model_validate(json.loads(chosen.read_text(encoding="utf-8")))
    elif path is not None or os.environ.get("TOPOS_CONFIG"):
        raise FileNotFoundError(f"Configured TOPOS registry does not exist: {chosen}")
    else:
        LOGGER.info("No TOPOS settings file; using mandatory BASE execution authority")
        config = SystemConfig()
    if os.environ.get("TOPOS_OUTPUT_ROOT"):
        config.output_root = Path(os.environ["TOPOS_OUTPUT_ROOT"]).expanduser()
    if os.environ.get("TOPOS_REMOTE_BASE_COMMIT"):
        config = SystemConfig.model_validate({**config.model_dump(),
                                             "remote_base_commit": os.environ["TOPOS_REMOTE_BASE_COMMIT"]})
    for variable, field in (("TOPOS_WORKSTATION_FOLDER", "workstation_folder"),
                            ("TOPOS_WORKSTATION_STUDENT", "workstation_student_id")):
        if os.environ.get(variable):
            config = SystemConfig.model_validate({**config.model_dump(), field: os.environ[variable]})
    if os.environ.get("TOPOS_REMOTE_CONTROLLER_PROFILE"):
        config = SystemConfig.model_validate({**config.model_dump(),
                                             "remote_controller_profile": os.environ["TOPOS_REMOTE_CONTROLLER_PROFILE"]})
    return config
