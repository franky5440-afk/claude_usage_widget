"""讀取另一台 collector 已整理好的 session context。"""
import json
import math
import subprocess
from datetime import datetime, timezone


def load_config(path):
    """讀取 peer 設定；不存在或內容無效時停用功能。"""
    try:
        with open(path, encoding="utf-8") as f:
            config = json.load(f)
        if not isinstance(config, dict):
            return None
        target = config.get("ssh_target")
        label = config.get("label")
        if (not isinstance(target, str) or not target.strip()
                or target.startswith("-")):
            return None
        if not isinstance(label, str) or not label.strip():
            return None
        return {"ssh_target": target, "label": label}
    except (OSError, ValueError, TypeError):
        return None


def _failure(label, error, generated_at=None):
    return {"label": label, "ok": False, "sessions": [], "error": error,
            "generated_at": generated_at}


def _clean_session(session):
    if not isinstance(session, dict):
        return None
    result = {}
    for key in ("project", "model", "last_active_at"):
        value = session.get(key)
        if key == "model" and value is None:
            result[key] = None
            continue
        if not isinstance(value, str):
            return None
        result[key] = value[:200]
    for key in ("tokens", "context_window", "percent"):
        value = session.get(key)
        if key == "percent" and value is None:
            result[key] = None
        elif key == "context_window" and value is None:
            result[key] = None
        elif (isinstance(value, bool) or not isinstance(value, (int, float))
              or not math.isfinite(value)):
            return None
        else:
            result[key] = value
    return result


def fetch_peer(config, runner=subprocess.run, now=None):
    """以 SSH 讀取對方 state，只回傳清理過的 sessions。"""
    label = config.get("label", "") if isinstance(config, dict) else ""
    target = config.get("ssh_target") if isinstance(config, dict) else None
    if not isinstance(target, str) or not target:
        return _failure(label, "對方設定無效")
    args = ["/usr/bin/ssh", "-o", "BatchMode=yes", "-o",
            "ConnectTimeout=3", target,
            "cat .cache/claude-usage-widget/state.json"]
    try:
        result = runner(args, capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return _failure(label, "無法讀取對方資料")
        state = json.loads(result.stdout)
        if not isinstance(state, dict) or not isinstance(state.get("sessions"), list):
            return _failure(label, "對方資料格式錯誤")
        generated_at = state.get("generated_at")
        if not isinstance(generated_at, str) or not generated_at:
            return _failure(label, "對方資料時間格式錯誤", generated_at)
        try:
            peer_time = datetime.fromisoformat(generated_at)
            if peer_time.tzinfo is None or peer_time.utcoffset() is None:
                raise ValueError("missing timezone")
            current = now if now is not None else datetime.now(timezone.utc)
            if current.tzinfo is None or current.utcoffset() is None:
                raise ValueError("missing timezone")
            age = (current - peer_time).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return _failure(label, "對方資料時間格式錯誤", generated_at)
        if age > 600:
            return _failure(label, "對方資料已過期", generated_at)
        sessions = []
        for item in state["sessions"]:
            clean = _clean_session(item)
            if clean is not None:
                sessions.append(clean)
            if len(sessions) == 3:
                break
        return {"label": label, "ok": True, "sessions": sessions,
                "error": None, "generated_at": generated_at}
    except subprocess.TimeoutExpired:
        return _failure(label, "連線對方逾時")
    except OSError:
        return _failure(label, "無法連線到對方")
    except (ValueError, TypeError, AttributeError):
        return _failure(label, "對方資料格式錯誤")
    except Exception:
        return _failure(label, "讀取對方資料時發生錯誤")
