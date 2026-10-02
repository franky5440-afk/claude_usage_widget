"""Mac 由 launchd 定時跑 collector（Frank 2026-10-02 拍板）。

背景：原本 collector 由 Übersicht widget 的 command 帶起來，螢幕一關 Übersicht 就不刷新，
state.json 跟著停（2026-10-02 實機 20:47 關螢幕後停在 20:45）。改由 launchd 每 30 秒跑，
widget 只讀 state.json。collector 沒有檔案鎖，兩邊同時跑會一起改 file_offsets.json，
所以 widget 的 command 不得再執行 collector。

測試用假的 launchctl 與暫時 HOME 跑 install-mac.sh，不碰真的系統設定。
"""
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
LABEL = "com.github.franky5440-afk.claude-usage-widget"

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin" or not Path("/Applications/Übersicht.app").is_dir(),
    reason="install-mac.sh 只在裝了 Übersicht 的 macOS 上跑")


def _fake_repo(parent: Path) -> Path:
    """複製 install-mac.sh 到路徑含空白與 XML 特殊字元的假 repo。"""
    repo = parent / "a b & <c>"
    (repo / "widget" / "claude-usage.widget").mkdir(parents=True)
    shutil.copy(REPO / "install-mac.sh", repo / "install-mac.sh")
    return repo


def _run_install(tmp_path: Path, repo: Path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    log = tmp_path / "launchctl.log"
    stub = bindir / "launchctl"
    stub.write_text('#!/bin/bash\necho "$*" >> "%s"\nexit 0\n' % log)
    stub.chmod(0o755)
    env = {"HOME": str(home), "PATH": f"{bindir}:/usr/bin:/bin:/usr/sbin:/sbin"}
    proc = subprocess.run(["/bin/bash", str(repo / "install-mac.sh")], env=env,
                          capture_output=True, text=True, timeout=30)
    calls = log.read_text().splitlines() if log.exists() else []
    return proc, home, calls


def test_install_writes_valid_launchd_plist(tmp_path):
    repo = _fake_repo(tmp_path)
    proc, home, _ = _run_install(tmp_path, repo)
    assert proc.returncode == 0, proc.stderr

    plist_path = home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    assert plist_path.is_file()
    lint = subprocess.run(["/usr/bin/plutil", "-lint", str(plist_path)],
                          capture_output=True, text=True)
    assert lint.returncode == 0, lint.stdout + lint.stderr

    with open(plist_path, "rb") as f:
        p = plistlib.load(f)
    assert p["Label"] == LABEL
    # 固定用系統 python（其他 python 可能缺 CA 憑證，SPEC §12.1）
    assert p["ProgramArguments"] == ["/usr/bin/python3", "-m", "collector.main"]
    assert p["WorkingDirectory"] == os.path.realpath(repo)
    assert p["StartInterval"] == 30
    assert p["RunAtLoad"] is True


def test_install_loads_agent_and_is_rerunnable(tmp_path):
    repo = _fake_repo(tmp_path)
    proc, home, calls = _run_install(tmp_path, repo)
    assert proc.returncode == 0, proc.stderr
    plist_path = str(home / "Library" / "LaunchAgents" / f"{LABEL}.plist")
    domain = f"gui/{os.getuid()}"
    assert f"bootstrap {domain} {plist_path}" in calls

    # 重跑：要先卸載舊的再載入，且不因已載入而失敗
    proc2, _, calls2 = _run_install(tmp_path, repo)
    assert proc2.returncode == 0, proc2.stderr
    assert f"bootout {domain}/{LABEL}" in calls2
    assert calls2.index(f"bootout {domain}/{LABEL}") < len(calls2) - 1
    assert calls2[-1] == f"bootstrap {domain} {plist_path}"


def test_install_survives_bootout_failure(tmp_path):
    """首次安裝時 bootout 會失敗（服務不存在），不得讓 set -e 中止腳本。"""
    repo = _fake_repo(tmp_path)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "launchctl.log"
    (bindir / "launchctl").write_text(
        '#!/bin/bash\necho "$*" >> "%s"\n[ "$1" = bootout ] && exit 3\nexit 0\n' % log)
    (bindir / "launchctl").chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    env = {"HOME": str(home), "PATH": f"{bindir}:/usr/bin:/bin:/usr/sbin:/sbin"}
    proc = subprocess.run(["/bin/bash", str(repo / "install-mac.sh")], env=env,
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert any(c.startswith("bootstrap ") for c in log.read_text().splitlines())


def test_widget_command_does_not_run_collector():
    src = (REPO / "widget" / "claude-usage.widget" / "index.jsx").read_text(encoding="utf-8")
    line = next(l for l in src.splitlines() if l.startswith("export const command"))
    assert "collector" not in line
    assert "python" not in line
    assert "state.json" in src and "cat " in line
