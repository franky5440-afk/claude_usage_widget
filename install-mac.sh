#!/bin/bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "錯誤：此腳本只能在 macOS 執行。" >&2
  exit 1
fi

if [[ ! -d "/Applications/Übersicht.app" ]]; then
  echo "找不到 /Applications/Übersicht.app，請先安裝 Übersicht。" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SOURCE_DIR="$REPO_ROOT/widget/claude-usage.widget"
WIDGETS_DIR="$HOME/Library/Application Support/Übersicht/widgets"
TARGET="$WIDGETS_DIR/claude-usage.widget"
mkdir -p "$WIDGETS_DIR"

if [[ -e "$TARGET" && ! -L "$TARGET" ]]; then
  echo "錯誤：目標已存在且不是 symlink：$TARGET" >&2
  exit 1
fi

ln -sfn "$SOURCE_DIR" "$TARGET"
echo "已建立 symlink：$TARGET → $SOURCE_DIR"

LABEL="com.github.franky5440-afk.claude-usage-widget"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$LAUNCH_AGENTS_DIR/$LABEL.plist"
mkdir -p "$LAUNCH_AGENTS_DIR"
/usr/bin/python3 -I - "$PLIST_PATH" "$REPO_ROOT" "$LABEL" <<'PY'
import plistlib
import sys

plist_path, repo_root, label = sys.argv[1:]
with open(plist_path, "wb") as plist_file:
    plistlib.dump({
        "Label": label,
        "ProgramArguments": ["/usr/bin/python3", "-m", "collector.main"],
        "WorkingDirectory": repo_root,
        "StartInterval": 30,
        "RunAtLoad": True,
    }, plist_file, fmt=plistlib.FMT_XML, sort_keys=False)
PY

DOMAIN="gui/$(id -u)"
# 首次安裝時服務尚不存在，bootout 必然失敗，訊息不必顯示
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST_PATH"
echo "首次更新時 macOS 可能跳出「允許存取鑰匙圈」視窗，請按「永遠允許」。"
echo "collector 已由 launchd 每 30 秒執行。"
