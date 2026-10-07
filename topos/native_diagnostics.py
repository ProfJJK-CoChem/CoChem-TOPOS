"""Bounded native process diagnostics for private calculation acceptance logs."""
from pathlib import Path


def native_failure_tails(folder: Path, *, limit: int = 4, tail_bytes: int = 2000) -> list[dict[str, str]]:
    """Expose retained native errors without loading whole outputs or following links."""
    root = folder.resolve()
    def modified(path: Path) -> int:
        try:
            return path.stat().st_mtime_ns
        except OSError:
            return 0

    paths = sorted(folder.rglob("*"), key=modified, reverse=True) if folder.is_dir() else []
    selected = []
    for suffix in ("stderr", "stderr.txt", "stdout", "stdout.txt"):
        for path in paths:
            if not path.name.endswith("." + suffix) or path.is_symlink() or not path.is_file():
                continue
            if any(parent.is_symlink() for parent in path.parents if parent != root and parent.is_relative_to(root)):
                continue
            if not path.resolve().is_relative_to(root):
                continue
            try:
                with path.open("rb") as stream:
                    stream.seek(max(0, path.stat().st_size - tail_bytes))
                    tail = stream.read(tail_bytes).decode("utf-8", errors="replace").strip()
            except OSError:
                continue
            if tail:
                selected.append({"path": path.relative_to(folder).as_posix(), "tail": tail})
                if len(selected) >= limit:
                    return selected
    return selected
