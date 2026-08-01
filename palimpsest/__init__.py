"""Palimpsest — a deterministic, offline manuscript workbench.

The importable package. The real work lives in engine/ (run as subprocesses on
PYTHONPATH — see engine/dossier.py, which is where builders are spawned) and the
CLI entry point is cli.main, exposed as the `pal` console script by pyproject.toml.
"""
from importlib.metadata import PackageNotFoundError, version as _version

def _read_version():
    """The version, read from pyproject.toml rather than restated here.

    Installed, it comes from package metadata; from a source checkout, from
    pyproject.toml directly, so `./pal --version` works in a clone too. Keeping
    one source of truth means a release bump cannot leave this behind.
    """
    try:
        return _version("palimpsest")
    except PackageNotFoundError:
        pass
    import tomllib
    from pathlib import Path
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        with open(pyproject, "rb") as fh:
            return str(tomllib.load(fh)["project"]["version"]) + "+source"
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "0+unknown"


__version__ = _read_version()

from .cli import main  # noqa: E402  (convenience: `from palimpsest import main`)

__all__ = ["main", "__version__"]
