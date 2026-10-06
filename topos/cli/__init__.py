"""CoChem-TOPOS Command Line Interface and Verification Subsystem."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from topos.cli.test_runner import HeadlessUITestRunner, run_cli_verification

__all__ = ["HeadlessUITestRunner", "run_cli_verification"]


def __getattr__(name: str):
    if name in {"HeadlessUITestRunner", "run_cli_verification"}:
        import topos.cli.test_runner as tr
        return getattr(tr, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
