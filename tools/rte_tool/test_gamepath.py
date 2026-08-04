"""Tests for gamepath's install-path handling.

Pure path logic - no game, no registry, no writes outside tmp_path. What is
under test is the validation, because everything downstream (install, uninstall)
writes into the folder it returns, and a wrong answer there puts a DLL somewhere
the user did not choose.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gamepath import GameInstall  # noqa: E402


def make_install(tmp_path, exe_name="Avatar.exe"):
    """A believable install tree: <root>/bin/Avatar.exe."""
    bin_dir = tmp_path / "Avatar The Game" / "bin"
    bin_dir.mkdir(parents=True)
    exe = bin_dir / exe_name
    exe.write_bytes(b"MZ")
    return exe


def test_accepts_the_exe_itself(tmp_path):
    exe = make_install(tmp_path)
    ok, result = GameInstall.validate(str(exe))
    assert ok
    assert os.path.normcase(result) == os.path.normcase(str(exe))


def test_accepts_the_bin_folder(tmp_path):
    exe = make_install(tmp_path)
    ok, result = GameInstall.validate(str(exe.parent))
    assert ok
    assert os.path.basename(result).lower() == "avatar.exe"


def test_accepts_the_install_root_and_looks_in_bin(tmp_path):
    """People pick the game's top folder, not bin\\. Both must work."""
    exe = make_install(tmp_path)
    ok, result = GameInstall.validate(str(exe.parent.parent))
    assert ok
    assert os.path.normcase(result) == os.path.normcase(str(exe))


def test_rejects_a_missing_path(tmp_path):
    ok, msg = GameInstall.validate(str(tmp_path / "nope" / "Avatar.exe"))
    assert not ok
    assert "does not exist" in msg


def test_rejects_the_wrong_executable(tmp_path):
    """Guards against someone picking the launcher, or Python, or anything else
    - the name is the only cheap proof we have that this is the game."""
    other = tmp_path / "bin"
    other.mkdir()
    wrong = other / "Launcher.exe"
    wrong.write_bytes(b"MZ")
    ok, msg = GameInstall.validate(str(wrong))
    assert not ok
    assert "not Avatar.exe" in msg


def test_rejects_a_folder_with_no_game(tmp_path):
    ok, msg = GameInstall.validate(str(tmp_path))
    assert not ok
    assert "no Avatar.exe" in msg


def test_rejects_empty(tmp_path):
    ok, msg = GameInstall.validate("")
    assert not ok
    assert "no path set" in msg


def test_derived_locations_hang_off_bin(tmp_path, monkeypatch):
    """proxy_path and log_path must land next to Avatar.exe. The DLL writes its
    log beside itself, so bin\\ is where both belong."""
    exe = make_install(tmp_path)
    monkeypatch.setattr(GameInstall, "_load", lambda self: "")
    g = GameInstall()
    ok, _ = g.set_path(str(exe))
    assert ok
    assert os.path.normcase(g.bin_dir) == os.path.normcase(str(exe.parent))
    assert g.proxy_path.lower().endswith("bin\\dinput8.dll")
    assert g.log_path.lower().endswith("bin\\avatar_console_dll.log")


def test_status_reports_log_path(tmp_path, monkeypatch):
    """Regression: status() did not include log_path, and the Setup page's
    'the log says why' branch read it with .get() - so the one message that
    pointed at the answer silently rendered as an empty line."""
    exe = make_install(tmp_path)
    monkeypatch.setattr(GameInstall, "_load", lambda self: "")
    g = GameInstall()
    g.set_path(str(exe))
    st = g.status()
    assert st["log_path"]
    assert st["log_path"].lower().endswith("avatar_console_dll.log")


def test_install_refuses_while_the_game_is_running(tmp_path, monkeypatch):
    """The copy would fail with a sharing violation anyway, but Windows reports
    that as something that reads like a permissions problem."""
    exe = make_install(tmp_path)
    monkeypatch.setattr(GameInstall, "_load", lambda self: "")
    import gamepath
    monkeypatch.setattr(gamepath, "game_is_running", lambda *a, **k: True)
    g = GameInstall()
    g.set_path(str(exe))
    ok, msg = g.install()
    assert not ok
    assert "running" in msg.lower()
    assert not os.path.exists(g.proxy_path)


def test_set_path_rejects_without_storing(tmp_path, monkeypatch):
    monkeypatch.setattr(GameInstall, "_load", lambda self: "")
    g = GameInstall()
    ok, _ = g.set_path(str(tmp_path / "Avatar.exe"))
    assert not ok
    assert g.exe == ""
