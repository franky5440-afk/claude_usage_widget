"""peer 契約以外的時間戳防護測試。"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from collector import peer  # noqa: E402


class Runner:
    def __init__(self, state):
        self.state = state

    def __call__(self, args, **kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps(self.state), stderr="")


def _state(generated_at):
    return {"generated_at": generated_at, "sessions": []}


def test_未提供_now_時使用目前時間而不接受過期資料():
    old_time = (datetime.now(timezone.utc) - timedelta(seconds=601)).isoformat()
    result = peer.fetch_peer({"ssh_target": "a@b", "label": "Mac"},
                             runner=Runner(_state(old_time)))
    assert result["ok"] is False
    assert result["sessions"] == []


def test_沒有時區的_generated_at_視為無效():
    result = peer.fetch_peer({"ssh_target": "a@b", "label": "Mac"},
                             runner=Runner(_state("2026-10-02T20:45:48")),
                             now=datetime(2026, 10, 2, tzinfo=timezone.utc))
    assert result["ok"] is False
    assert result["sessions"] == []
    assert result["error"]
