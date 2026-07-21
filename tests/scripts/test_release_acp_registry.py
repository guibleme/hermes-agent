"""Tests for atomic release-version ownership in scripts/release.py.

The Python package, Desktop package metadata and workspace lock, and official
ACP Registry manifest must move together. The release script is their single
owner; if it silently misses one, packaged identity or registry pins drift from
the release users believe they installed.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _load_release_module(monkeypatch, tmp_root: Path):
    """Import scripts/release.py with REPO_ROOT pinned to a temp tree."""
    spec = importlib.util.spec_from_file_location(
        "_release_under_test",
        Path(__file__).resolve().parents[2] / "scripts" / "release.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.setattr(module, "REPO_ROOT", tmp_root)
    monkeypatch.setattr(
        module, "ACP_REGISTRY_MANIFEST", tmp_root / "acp_registry" / "agent.json"
    )
    return module


def _write_manifest(root: Path, version: str) -> None:
    manifest_dir = root / "acp_registry"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "agent.json").write_text(
        json.dumps(
            {
                "id": "hermes-agent",
                "name": "Hermes Agent",
                "version": version,
                "description": "test",
                "distribution": {
                    "uvx": {
                        "package": f"hermes-agent[acp]=={version}",
                        "args": ["hermes-acp"],
                    }
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_update_acp_registry_versions_bumps_manifest_and_pin(monkeypatch, tmp_path):
    _write_manifest(tmp_path, "0.13.0")
    module = _load_release_module(monkeypatch, tmp_path)

    module._update_acp_registry_versions("0.14.0")

    manifest = json.loads(
        (tmp_path / "acp_registry" / "agent.json").read_text(encoding="utf-8")
    )
    assert manifest["version"] == "0.14.0"
    assert manifest["distribution"]["uvx"]["package"] == "hermes-agent[acp]==0.14.0"
    # args stay untouched so we don't accidentally rewrite them.
    assert manifest["distribution"]["uvx"]["args"] == ["hermes-acp"]


def test_update_acp_registry_versions_is_silent_when_manifest_missing(
    monkeypatch, tmp_path
):
    """Older release branches predate the ACP Registry asset — must no-op."""
    module = _load_release_module(monkeypatch, tmp_path)

    # No fixture written; function should not raise.
    module._update_acp_registry_versions("0.14.0")


def test_update_version_files_bumps_manifest_alongside_pyproject(
    monkeypatch, tmp_path
):
    """End-to-end: update_version_files() is the function release.py actually
    calls, so it must drive the manifest bump too."""
    _write_manifest(tmp_path, "0.13.0")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "hermes-agent"\nversion = "0.13.0"\n', encoding="utf-8"
    )
    version_dir = tmp_path / "hermes_cli"
    version_dir.mkdir()
    (version_dir / "__init__.py").write_text(
        '__version__ = "0.13.0"\n__release_date__ = "2026-05-14"\n',
        encoding="utf-8",
    )
    desktop_dir = tmp_path / "apps" / "desktop"
    desktop_dir.mkdir(parents=True)
    (desktop_dir / "package.json").write_text(
        json.dumps({"name": "hermes", "version": "0.13.0"}, indent=2) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "package-lock.json").write_text(
        json.dumps(
            {
                "lockfileVersion": 3,
                "packages": {
                    "": {"name": "hermes-agent", "version": "1.0.0"},
                    "apps/desktop": {"name": "hermes", "version": "0.13.0"},
                    "node_modules/example": {"version": "0.13.0"},
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    module = _load_release_module(monkeypatch, tmp_path)
    monkeypatch.setattr(module, "VERSION_FILE", version_dir / "__init__.py")
    monkeypatch.setattr(module, "PYPROJECT_FILE", tmp_path / "pyproject.toml")

    module.update_version_files("0.14.0", "2026-05-21")

    pyproject_text = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "0.14.0"' in pyproject_text

    desktop_package = json.loads(
        (desktop_dir / "package.json").read_text(encoding="utf-8")
    )
    lock_data = json.loads(
        (tmp_path / "package-lock.json").read_text(encoding="utf-8")
    )
    assert desktop_package["version"] == "0.14.0"
    assert lock_data["packages"]["apps/desktop"]["version"] == "0.14.0"
    assert lock_data["packages"][""]["version"] == "1.0.0"
    assert lock_data["packages"]["node_modules/example"]["version"] == "0.13.0"

    manifest = json.loads(
        (tmp_path / "acp_registry" / "agent.json").read_text(encoding="utf-8")
    )
    assert manifest["version"] == "0.14.0"
    assert manifest["distribution"]["uvx"]["package"] == "hermes-agent[acp]==0.14.0"

    owned_files = set(module.version_files_for_release())
    assert owned_files == {
        version_dir / "__init__.py",
        tmp_path / "pyproject.toml",
        desktop_dir / "package.json",
        tmp_path / "package-lock.json",
        tmp_path / "acp_registry" / "agent.json",
    }


def test_update_version_files_rejects_missing_desktop_lock_entry(
    monkeypatch, tmp_path
):
    """A present workspace lock must not silently omit packaged Desktop."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "0.13.0"\n', encoding="utf-8"
    )
    version_dir = tmp_path / "hermes_cli"
    version_dir.mkdir()
    (version_dir / "__init__.py").write_text(
        '__version__ = "0.13.0"\n__release_date__ = "2026-05-14"\n',
        encoding="utf-8",
    )
    desktop_dir = tmp_path / "apps" / "desktop"
    desktop_dir.mkdir(parents=True)
    (desktop_dir / "package.json").write_text(
        '{"name":"hermes","version":"0.13.0"}\n', encoding="utf-8"
    )
    (tmp_path / "package-lock.json").write_text(
        '{"lockfileVersion":3,"packages":{}}\n', encoding="utf-8"
    )

    module = _load_release_module(monkeypatch, tmp_path)
    monkeypatch.setattr(module, "VERSION_FILE", version_dir / "__init__.py")
    monkeypatch.setattr(module, "PYPROJECT_FILE", tmp_path / "pyproject.toml")

    with pytest.raises(
        ValueError,
        match="package-lock.json is missing the apps/desktop workspace entry",
    ):
        module.update_version_files("0.14.0", "2026-05-21")
