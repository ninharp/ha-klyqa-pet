#!/usr/bin/env python3
"""Fail if the library and integration disagree on the pyklyqa-pet version.

The version is duplicated in three places on purpose (a PyPI package and a
Home Assistant manifest each need their own copy) and they must always match:

- `version` in pyproject.toml (the pyklyqa-pet library)
- `__version__` in pyklyqa_pet/__init__.py
- the `pyklyqa-pet==X.Y.Z` pin and the `version` field in
  custom_components/klyqa_pet/manifest.json
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent


def pyproject_version() -> str:
    text = (ROOT / "pyproject.toml").read_text()
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    if not match:
        raise SystemExit("pyproject.toml: no top-level version field found")
    return match.group(1)


def library_version() -> str:
    text = (ROOT / "pyklyqa_pet" / "__init__.py").read_text()
    match = re.search(r'(?m)^__version__\s*=\s*"([^"]+)"', text)
    if not match:
        raise SystemExit("pyklyqa_pet/__init__.py: no __version__ found")
    return match.group(1)


def manifest_versions() -> tuple[str, str]:
    manifest = json.loads((ROOT / "custom_components" / "klyqa_pet" / "manifest.json").read_text())
    manifest_version = manifest["version"]
    requirement = next((r for r in manifest["requirements"] if r.startswith("pyklyqa-pet==")), None)
    if requirement is None:
        raise SystemExit("manifest.json: no pinned pyklyqa-pet requirement found")
    pinned_version = requirement.removeprefix("pyklyqa-pet==")
    return manifest_version, pinned_version


def main() -> int:
    versions = {
        "pyproject.toml [project].version": pyproject_version(),
        "pyklyqa_pet/__init__.py __version__": library_version(),
    }
    manifest_version, pinned_version = manifest_versions()
    versions["manifest.json version"] = manifest_version
    versions["manifest.json requirements pyklyqa-pet=="] = pinned_version

    unique = set(versions.values())
    if len(unique) == 1:
        print(f"All versions match: {unique.pop()}")
        return 0

    print("Version mismatch across files:")
    for label, value in versions.items():
        print(f"  {label}: {value}")
    print(
        "\nBump pyproject.toml, pyklyqa_pet/__init__.py and "
        "custom_components/klyqa_pet/manifest.json (both the version field and "
        "the pyklyqa-pet== requirement) together in the same commit."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
