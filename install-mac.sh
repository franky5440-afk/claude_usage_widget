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

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/widget/claude-usage.widget"
WIDGETS_DIR="$HOME/Library/Application Support/Übersicht/widgets"
TARGET="$WIDGETS_DIR/claude-usage.widget"
mkdir -p "$WIDGETS_DIR"

if [[ -e "$TARGET" && ! -L "$TARGET" ]]; then
  echo "錯誤：目標已存在且不是 symlink：$TARGET" >&2
  exit 1
fi

ln -sfn "$SOURCE_DIR" "$TARGET"
echo "已建立 symlink：$TARGET → $SOURCE_DIR"
echo "首次更新時 macOS 可能跳出「允許存取鑰匙圈」視窗，請按「永遠允許」。"
