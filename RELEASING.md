# Releasing

This repository ships two things from one version number: the `pyklyqa-pet`
library on PyPI and the `klyqa_pet` integration through HACS. They are
developed together and released together.

## The version lives in four places

`scripts/check_versions.py` fails CI unless all four agree:

- `version` in `pyproject.toml`
- `__version__` in `pyklyqa_pet/__init__.py`
- `version` in `custom_components/klyqa_pet/manifest.json`
- the `pyklyqa-pet==X.Y.Z` pin in that same manifest

Bump them in one commit. There is no such thing as releasing only the
integration: the manifest pins the library by exact version, so a new
integration version needs a library version that exists on PyPI. When the
library's code has not changed, it still goes out under the new number — an
identical release is cheaper than a version scheme that needs explaining.

## Steps

```bash
# 1. Bump all four places, then prove it
python3 scripts/check_versions.py

# 2. Run what CI runs
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy
.venv/bin/pytest -q

# 3. Commit and push; wait for CI to go green on main
git commit -am "Bump to X.Y.Z" && git push origin main
gh run list --limit 1

# 4. Build. `uv publish` does NOT build -- it uploads whatever sits in dist/,
#    which is the previous release until you do this.
uv build

# 5. Publish the new files by name, because dist/ keeps older builds around
uv publish dist/pyklyqa_pet-X.Y.Z*

# 6. Tag the commit CI went green on, and push the tag
git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z

# 7. Write the release notes for someone deciding whether to update
gh release create vX.Y.Z --title "vX.Y.Z" --notes "..."
```

Publish before tagging. A tag is a promise that the release exists; PyPI
rejects a re-upload of a version, so an upload that fails after tagging
leaves a tag pointing at a release nobody can install.

## Release notes

Write them for a user deciding whether to update, not from the commit log.
Lead with what changes for them, say plainly when something needs a migration
or a firmware version, and name the parts that stayed the same when a version
number might suggest otherwise.
