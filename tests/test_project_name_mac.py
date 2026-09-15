"""Mac 專案名反解：`~/Claude main/<專案>` 在目錄名裡是 `Claude-main-<專案>`（空白變成 -）。

Frank 2026-09-15：專案排行要顯示 `claude-usage-widget`，不要 `main-claude-usage-widget`。
"""
from collector import transcript_scan


def test_claude_main_底下的專案要去掉_main():
    assert transcript_scan._decode_project_name(
        "-Users-someone-Claude-main-claude-usage-widget") == "claude-usage-widget"


def test_名叫_main_的專案本身不能被吃掉():
    assert transcript_scan._decode_project_name("-Users-someone-Claude-main") == "main"


def test_既有規則不受影響():
    assert transcript_scan._decode_project_name("-Users-someone-Claude-my-proj") == "my-proj"
    assert transcript_scan._decode_project_name("-home-someone-Claude-quantum") == "quantum"
    assert transcript_scan._decode_project_name("-Users-someone") == "家目錄"
