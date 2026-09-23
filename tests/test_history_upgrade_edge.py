"""舊版帳本升級的邊界：重建後就算一天都沒補到，也要寫成新版，否則每 30 秒全量重建一次（SPEC §3）。"""
import json

from collector import history, main


def test_舊版帳本且沒有任何逐字稿時仍升版_不會一再重建(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / history.HISTORY_FILE).write_text(json.dumps({"schema_version": 1, "days": {}}))

    main._sync_history(cache, tmp_path / "projects")
    assert json.loads((cache / history.HISTORY_FILE).read_text())["schema_version"] == history.SCHEMA_VERSION

    calls = []
    monkeypatch.setattr(history, "rebuild", lambda *a, **k: calls.append(1) or {})
    main._sync_history(cache, tmp_path / "projects")
    assert calls == []
