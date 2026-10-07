"""Portable installation configuration; scientific requests remain explicit."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LOGGER = logging.getLogger("cochem.config")


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
    return config
