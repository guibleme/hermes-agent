"""Tests for the persistent WhatsApp bridge runtime and dependency identity."""
from pathlib import Path

import pytest

from gateway.platforms import whatsapp_common


def _seed_install_tree(install_bridge: Path) -> None:
    """Create a minimal fake bridge source tree."""
    install_bridge.mkdir(parents=True, exist_ok=True)
    (install_bridge / "bridge.js").write_text("// bridge\n")
    (install_bridge / "package.json").write_text('{"name": "whatsapp-bridge"}\n')
    (install_bridge / "package-lock.json").write_text('{"lockfileVersion": 3}\n')


def test_writable_install_uses_persistent_runtime(tmp_path, monkeypatch):
    """Editable installs do not own generated bridge dependencies."""
    install_root = tmp_path / "install"
    install_bridge = install_root / "scripts" / "whatsapp-bridge"
    _seed_install_tree(install_bridge)

    hermes_home = tmp_path / "hermes_home"
    hermes_home.mkdir()

    # Point the resolver's two anchors at our temp dirs.
    monkeypatch.setattr(
        whatsapp_common, "__file__",
        str(install_root / "gateway" / "platforms" / "whatsapp_common.py"),
    )
    monkeypatch.setattr(
        "hermes_constants.get_hermes_home", lambda: hermes_home
    )

    resolved = whatsapp_common.resolve_whatsapp_bridge_dir()
    expected = hermes_home / "scripts" / "whatsapp-bridge"
    assert resolved == expected
    assert (expected / "bridge.js").read_text() == "// bridge\n"
    assert not (expected / "node_modules").exists()


def test_readonly_install_mirrors_to_hermes_home(tmp_path, monkeypatch):
    """A read-only source install uses the same persistent runtime contract."""
    install_root = tmp_path / "install"
    install_bridge = install_root / "scripts" / "whatsapp-bridge"
    _seed_install_tree(install_bridge)

    hermes_home = tmp_path / "hermes_home"
    hermes_home.mkdir()

    monkeypatch.setattr(
        whatsapp_common, "__file__",
        str(install_root / "gateway" / "platforms" / "whatsapp_common.py"),
    )
    monkeypatch.setattr(
        "hermes_constants.get_hermes_home", lambda: hermes_home
    )

    resolved = whatsapp_common.resolve_whatsapp_bridge_dir()

    expected = hermes_home / "scripts" / "whatsapp-bridge"
    assert resolved == expected
    # Source was mirrored, not symlinked.
    assert (expected / "bridge.js").read_text() == "// bridge\n"
    assert (expected / "package.json").exists()


def test_readonly_install_reuses_existing_mirror(tmp_path, monkeypatch):
    """Refresh source in an existing mirror without deleting node_modules."""
    install_root = tmp_path / "install"
    install_bridge = install_root / "scripts" / "whatsapp-bridge"
    _seed_install_tree(install_bridge)

    hermes_home = tmp_path / "hermes_home"
    mirror = hermes_home / "scripts" / "whatsapp-bridge"
    mirror.mkdir(parents=True)
    # A sentinel file proves the resolver returned the EXISTING mirror
    # rather than wiping/recopying it.
    (mirror / "node_modules").mkdir()
    (mirror / "node_modules" / "sentinel").write_text("keep me\n")
    (mirror / "bridge.js").write_text("// stale bridge\n")

    monkeypatch.setattr(
        whatsapp_common, "__file__",
        str(install_root / "gateway" / "platforms" / "whatsapp_common.py"),
    )
    monkeypatch.setattr(
        "hermes_constants.get_hermes_home", lambda: hermes_home
    )

    resolved = whatsapp_common.resolve_whatsapp_bridge_dir()

    assert resolved == mirror
    assert (mirror / "bridge.js").read_text() == "// bridge\n"
    assert (mirror / "node_modules" / "sentinel").read_text() == "keep me\n"


def test_unavailable_runtime_falls_back_to_install_source(tmp_path, monkeypatch):
    install_root = tmp_path / "install"
    install_bridge = install_root / "scripts" / "whatsapp-bridge"
    _seed_install_tree(install_bridge)
    hermes_home = tmp_path / "hermes_home"

    monkeypatch.setattr(
        whatsapp_common,
        "__file__",
        str(install_root / "gateway" / "platforms" / "whatsapp_common.py"),
    )
    monkeypatch.setattr("hermes_constants.get_hermes_home", lambda: hermes_home)
    monkeypatch.setattr(
        whatsapp_common,
        "_sync_whatsapp_bridge_source",
        lambda source, runtime: False,
    )

    assert whatsapp_common.resolve_whatsapp_bridge_dir() == install_bridge


def test_existing_last_good_runtime_survives_refresh_failure(tmp_path, monkeypatch):
    install_root = tmp_path / "install"
    install_bridge = install_root / "scripts" / "whatsapp-bridge"
    _seed_install_tree(install_bridge)
    hermes_home = tmp_path / "hermes_home"
    runtime = hermes_home / "scripts" / "whatsapp-bridge"
    runtime.mkdir(parents=True)
    (runtime / "bridge.js").write_text("// last good\n")

    monkeypatch.setattr(
        whatsapp_common,
        "__file__",
        str(install_root / "gateway" / "platforms" / "whatsapp_common.py"),
    )
    monkeypatch.setattr("hermes_constants.get_hermes_home", lambda: hermes_home)
    monkeypatch.setattr(
        whatsapp_common,
        "_sync_whatsapp_bridge_source",
        lambda source, runtime: False,
    )

    assert whatsapp_common.resolve_whatsapp_bridge_dir() == runtime


def test_dependency_freshness_covers_package_and_lock(tmp_path):
    bridge = tmp_path / "bridge"
    _seed_install_tree(bridge)
    node_modules = bridge / "node_modules"
    node_modules.mkdir()

    assert whatsapp_common.whatsapp_bridge_dependencies_fresh(bridge) is False
    whatsapp_common.mark_whatsapp_bridge_dependencies_fresh(bridge)
    assert whatsapp_common.whatsapp_bridge_dependencies_fresh(bridge) is True

    (bridge / "package-lock.json").write_text('{"lockfileVersion": 2}\n')
    assert whatsapp_common.whatsapp_bridge_dependencies_fresh(bridge) is False

    whatsapp_common.mark_whatsapp_bridge_dependencies_fresh(bridge)
    assert whatsapp_common.whatsapp_bridge_dependencies_fresh(bridge) is True
    (bridge / "package.json").write_text('{"name": "changed"}\n')
    assert whatsapp_common.whatsapp_bridge_dependencies_fresh(bridge) is False


def test_dependency_stamp_rejects_missing_manifests_and_modules(tmp_path):
    bridge = tmp_path / "bridge"
    bridge.mkdir()
    assert whatsapp_common.whatsapp_bridge_dependency_hash(bridge) == ""
    assert whatsapp_common.whatsapp_bridge_dependencies_fresh(bridge) is False
    with pytest.raises(OSError, match="manifests"):
        whatsapp_common.mark_whatsapp_bridge_dependencies_fresh(bridge)


def test_compatible_dependencies_survive_editable_checkout_switch(tmp_path, monkeypatch):
    hermes_home = tmp_path / "hermes_home"
    first_root = tmp_path / "checkout-a"
    first_bridge = first_root / "scripts" / "whatsapp-bridge"
    _seed_install_tree(first_bridge)
    second_root = tmp_path / "checkout-b"
    second_bridge = second_root / "scripts" / "whatsapp-bridge"
    _seed_install_tree(second_bridge)
    (second_bridge / "bridge.js").write_text("// bridge from checkout b\n")
    monkeypatch.setattr("hermes_constants.get_hermes_home", lambda: hermes_home)

    monkeypatch.setattr(
        whatsapp_common,
        "__file__",
        str(first_root / "gateway" / "platforms" / "whatsapp_common.py"),
    )
    runtime = whatsapp_common.resolve_whatsapp_bridge_dir()
    (runtime / "node_modules").mkdir()
    (runtime / "node_modules" / "sentinel").write_text("compatible\n")
    whatsapp_common.mark_whatsapp_bridge_dependencies_fresh(runtime)

    monkeypatch.setattr(
        whatsapp_common,
        "__file__",
        str(second_root / "gateway" / "platforms" / "whatsapp_common.py"),
    )
    resolved = whatsapp_common.resolve_whatsapp_bridge_dir()

    assert resolved == runtime
    assert (runtime / "bridge.js").read_text() == "// bridge from checkout b\n"
    assert (runtime / "node_modules" / "sentinel").read_text() == "compatible\n"
    assert whatsapp_common.whatsapp_bridge_dependencies_fresh(runtime) is True
