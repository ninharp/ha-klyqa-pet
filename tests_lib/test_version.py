from pathlib import Path
import re

from pyklyqa_pet import __version__


def test_version() -> None:
    """The library's __version__ must match pyproject.toml's [project].version.

    scripts/check_versions.py additionally checks this against the Home Assistant
    manifest; this test only guards against __init__.py and pyproject.toml drifting
    apart, which would otherwise slip past a normal test run.
    """
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', pyproject.read_text())
    assert match is not None, "pyproject.toml: no top-level version field found"
    assert __version__ == match.group(1)
