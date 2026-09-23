"""來源 B：增量掃描 ~/.claude/projects/**/*.jsonl 統計 token。

規格見 SPEC.md §2.2、§3（效能硬需求：禁止全量掃描）。
"""
import json
import os
import re
from stat import S_ISREG
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Tuple


TW = timezone(timedelta(hours=8))

CACHE_FILE = "file_offsets.json"
TOTALS_CACHE = "totals_cache.json"


def _load_cache(cache_dir: Path) -> Dict[str, Any]:
    """載入快取檔。"""
    cache_path = cache_dir / CACHE_FILE
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"files": {}, "totals": {}}


def _save_cache(cache_dir: Path, cache_data: Dict[str, Any]) -> None:
    """儲存快取檔（原子寫入）。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / CACHE_FILE
    tmp_path = cache_path.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False)
        os.chmod(tmp_path, 0o600)  # 含 message id 與活動時間，與 state.json 同權限
        os.replace(tmp_path, cache_path)
    except OSError:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


def _load_totals_cache(cache_dir: Path) -> Dict[str, Any]:
    """載入累計值快取。"""
    cache_path = cache_dir / TOTALS_CACHE
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_totals_cache(cache_dir: Path, totals: Dict[str, Any]) -> None:
    """儲存累計值快取。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / TOTALS_CACHE
    tmp_path = cache_path.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(totals, f, ensure_ascii=False)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, cache_path)
    except OSError:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


def _decode_project_name(dir_name: str) -> str:
    """將目錄名反解成專案名。
    支援三種格式：
      -home-/-Users-<user>                 -> "家目錄"
      -home-/-Users-<user>-Claude-main-<專案> -> <專案> (去掉 main-)
      -home-/-Users-<user>-Claude-<專案>   -> <專案> (專案名可能含 -)
      -home-/-Users-<user>-<其他前綴>-<專案> -> <專案> (取最後一段)
    """
    if not (dir_name.startswith("-home-") or dir_name.startswith("-Users-")):
        return dir_name
    
    # 去掉 -home-<user>- 前綴 (分割成 4 部分：['', 'home', '<user>', '<rest>'])
    parts = dir_name.split("-", 3)
    if len(parts) < 4 or not parts[3]:
        # 沒有 rest 部分，代表是 -home-<user> 這種家目錄本身
        return "家目錄"
    
    rest = parts[3]  # 去掉 -home-<user>- 後的剩餘部分
    
    # ~/Claude main/<專案> 的空白會編碼成 Claude-main-，顯示時去掉這層目錄名。
    if rest.startswith("Claude-main-"):
        return rest[len("Claude-main-"):]

    # 如果是 -home-<user>-Claude-<專案> 格式；Claude-main 本身會回傳 main。
    if rest.startswith("Claude-"):
        return rest[len("Claude-"):]  # 保留完整專案名（可能含 -）
    
    # 其他格式：取最後一段作為專案名
    return rest.split("-")[-1]


def project_name(proj_dir: Path) -> str:
    """還原專案名；有損的目錄名再從逐字稿的 cwd 驗證還原。"""
    name = _decode_project_name(proj_dir.name)
    if "--" not in name and not name.startswith("-") and not name.endswith("-"):
        return name

    try:
        # 只挑一般檔：FIFO 之類的特殊檔 open 會卡住整支 collector
        files = [path for path in proj_dir.glob("*.jsonl")
                 if S_ISREG(os.lstat(path).st_mode)]
        if not files:
            return name
        latest = max(files, key=lambda path: path.stat().st_mtime)
        with open(latest, "rb") as f:
            head = f.read(64 * 1024)
        for line in head.decode("utf-8", errors="replace").splitlines():
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, ValueError, RecursionError):
                continue
            cwd = record.get("cwd") if isinstance(record, dict) else None
            if not isinstance(cwd, str) or not cwd:
                continue
            if re.sub(r"[^A-Za-z0-9]", "-", cwd) != proj_dir.name:
                return name
            basename = os.path.basename(cwd.rstrip("/"))
            return basename or name
    except (OSError, ValueError, TypeError):
        pass
    return name


def _parse_jsonl_line(line: str) -> Tuple[bool, Dict[str, Any]]:
    """解析單行 jsonl，回傳 (是否為 assistant, 解析後的資料)。"""
    try:
        obj = json.loads(line)
    except ValueError:  # 含 JSONDecodeError
        return False, {}

    # 怪行一律跳過，不讓單一行拋例外拖垮整輪掃描（SPEC §4.2）
    if not isinstance(obj, dict) or obj.get("type") != "assistant":
        return False, {}

    msg = obj.get("message")
    if not isinstance(msg, dict):
        return False, {}
    model = msg.get("model")
    if not isinstance(model, str) or not model:
        model = "unknown"
    usage = msg.get("usage", {})
    timestamp = obj.get("timestamp")
    message_id = msg.get("id")

    return True, {
        "message_id": message_id if isinstance(message_id, str) else None,
        "model": model,
        "usage": usage,
        "timestamp": timestamp,
    }


def _is_today(timestamp_str: str) -> bool:
    """判斷 timestamp（UTC）是否為今天（台灣時間）。"""
    try:
        dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_tw = dt.astimezone(TW)
        today_tw = datetime.now(TW).date()
        return dt_tw.date() == today_tw
    except (ValueError, AttributeError):
        return False


def _today_str() -> str:
    """回傳今天日期（台灣時間）的 YYYY-MM-DD 字串。"""
    return datetime.now(TW).date().isoformat()


def _monday_of(day):
    """該日期所在週的週一。週界定義只有這一套，history 共用。"""
    return day - timedelta(days=day.weekday())


def _is_in_week(timestamp_str: str) -> bool:
    """判斷 timestamp（UTC）是否落在「本週一到今天」（台灣時間切日）。"""
    try:
        dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        day_tw = dt.astimezone(TW).date()
        today_tw = datetime.now(TW).date()
        if day_tw > today_tw:
            return False
        return _monday_of(day_tw) == _monday_of(today_tw)
    except (ValueError, AttributeError):
        return False


def _process_file(filepath: Path, last_offset: int) -> Tuple[int, List[Dict[str, Any]]]:
    """處理單一檔案，從 last_offset 開始讀取，回傳 (新 offset, 記錄列表)。"""
    records = []
    new_offset = last_offset

    try:
        with open(filepath, "rb") as f:
            f.seek(last_offset)
            while True:
                line_bytes = f.readline()
                if not line_bytes:
                    break
                new_offset = f.tell()
                try:
                    line = line_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                is_assistant, data = _parse_jsonl_line(line.strip())
                if is_assistant:
                    records.append(data)
    except OSError:
        pass

    return new_offset, records


FILE_CACHE_VERSION = 3


def _usage_counts(usage: Dict[str, Any]) -> Dict[str, int]:
    usage = usage if isinstance(usage, dict) else {}

    def count(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return 0
        try:
            return max(0, int(value))
        except (ValueError, OverflowError):
            return 0

    counts = {
        key: count(usage.get(key, 0))
        for key in ("input_tokens", "output_tokens", "cache_read_input_tokens")
    }
    total_cache = count(usage.get("cache_creation_input_tokens", 0))
    nested = usage.get("cache_creation")
    if isinstance(nested, dict):
        cache_1h = count(nested.get("ephemeral_1h_input_tokens", 0))
        cache_1h = min(total_cache, cache_1h)
        cache_5m = total_cache - cache_1h
    else:
        # Flat values are already split; the 1h amount is separate from the
        # non-1h amount and must not be clamped against it.
        cache_1h = count(usage.get("cache_creation_1h_input_tokens", 0))
        cache_5m = total_cache
    counts["cache_creation_input_tokens"] = cache_5m
    counts["cache_creation_1h_input_tokens"] = cache_1h
    return counts


def _record_for_cache(record: Dict[str, Any]) -> Dict[str, Any]:
    """只保留 usage、model、時間，絕不把對話文字寫入快取。"""
    return {
        "model": record.get("model", "unknown"),
        "usage": _usage_counts(record.get("usage", {})),
        "timestamp": record.get("timestamp"),
    }


def _cache_records(cached: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    if cached.get("version") != FILE_CACHE_VERSION:
        return {}, []
    messages = cached.get("messages")
    anonymous = cached.get("anonymous")
    if not isinstance(messages, dict) or not isinstance(anonymous, list):
        return {}, []
    return messages, anonymous


def _merge_usage(bucket: Dict[str, Dict[str, int]], model: str,
                 counts: Dict[str, int]) -> None:
    if model not in bucket:
        bucket[model] = {"input_tokens": 0, "output_tokens": 0,
                         "cache_creation_input_tokens": 0,
                         "cache_creation_1h_input_tokens": 0,
                         "cache_read_input_tokens": 0}
    for key, value in counts.items():
        bucket[model][key] = bucket[model].get(key, 0) + value


def _add_file_records(file_cache: Dict[str, Any], today_by_model,
                      week_by_model, project_tokens: Dict[str, int],
                      project_name: str) -> None:
    messages, anonymous = _cache_records(file_cache)
    for record in list(messages.values()) + anonymous:
        model = record.get("model", "unknown")
        counts = _usage_counts(record.get("usage", {}))
        if _is_in_week(record.get("timestamp")):
            _merge_usage(week_by_model, model, counts)
        if _is_today(record.get("timestamp")):
            _merge_usage(today_by_model, model, counts)
            project_tokens[project_name] = project_tokens.get(project_name, 0) + sum(counts.values())


def dispatch_audit_files(dispatch_dir) -> List[Path]:
    """列出 Dispatch 的 audit.jsonl（SPEC §12.3 的固定層級）。

    不可用 rglob：該目錄實測 15.8 萬個子目錄，遞迴一次要 2–3 秒，
    widget 每 30 秒跑一次會一直吃 CPU。固定深度 glob 實測 0.01 秒且涵蓋全部 1257 檔。
    """
    if not dispatch_dir:
        return []
    dispatch_dir = Path(dispatch_dir)
    if not dispatch_dir.exists():
        return []
    try:
        candidates = (list(dispatch_dir.glob("*/*/local_*/audit.jsonl"))
                      + list(dispatch_dir.glob("*/*/agent/local_ditto_*/audit.jsonl")))
    except OSError:
        return []
    files = []
    for path in candidates:
        # 只收一般檔案：symlink 可能指到任意檔，FIFO 會讓 open() 永遠卡住
        try:
            if S_ISREG(os.lstat(path).st_mode):
                files.append(path)
        except OSError:
            continue
    return files


def _dispatch_files(dispatch_dir: Path, minimum_mtime: float) -> List[Tuple[Path, str]]:
    """列出本週才可能有用量的 audit.jsonl，不開啟窗口外檔案。"""
    if not dispatch_dir or not dispatch_dir.exists():
        return []
    files = []
    try:
        for path in dispatch_audit_files(dispatch_dir):
            try:
                if path.is_file() and os.stat(path).st_mtime >= minimum_mtime:
                    files.append((path, "Dispatch"))
            except OSError:
                continue
    except OSError:
        pass
    return files


def scan(cache_dir, projects_dir, dispatch_dir=None):
    """增量掃描，回傳：

    {
      "bytes_read": int,          # 這一輪實際讀了幾個位元組（沒變動就是 0）
      "totals": {"today_tokens": int, "today_by_model": {model: usage_dict},
                 "week_by_model": {model: usage_dict}},
      "projects": [{"name": str, "tokens": int, "percent": float}],
    }

    快取（每個檔的 size/mtime/offset 與累計值）寫在 cache_dir 底下。
    累計值只在同一天（台灣時間）有效，跨日一律作廢重算。
    """

    cache_dir = Path(cache_dir)
    projects_dir = Path(projects_dir)
    dispatch_dir = Path(dispatch_dir) if dispatch_dir is not None else None

    # 載入快取
    cache = _load_cache(cache_dir)
    file_cache = cache.get("files", {})
    totals_cache = _load_totals_cache(cache_dir)

    # P0：今日累計只在同一天有效。快取若缺 scan_date 或日期不是今天，
    # 代表隔夜（或舊版快取），今日累計與 offset 一併作廢，從頭重算。
    today_str = _today_str()
    if totals_cache.get("scan_date") != today_str:
        # 跨日作廢前先把舊的今日累計歸檔到日結帳本（HANDOFF.md A 節的關鍵接縫）。
        # 沒有日期或沒有用量就沒有東西可歸檔，該空就空，不編造。
        stale_date = totals_cache.get("scan_date")
        stale_by_model = totals_cache.get("today_by_model") or {}
        if stale_date and stale_by_model:
            from collector import history
            history.record_day(
                cache_dir, stale_date, stale_by_model,
                project_tokens=totals_cache.get("project_tokens") or {})
        file_cache = {}

    today_by_model: Dict[str, Dict[str, int]] = {}
    week_by_model: Dict[str, Dict[str, int]] = {}
    project_tokens: Dict[str, int] = {}
    total_bytes_read = 0

    source_files: List[Tuple[Path, str]] = []
    if projects_dir.exists():
        try:
            for proj_dir in projects_dir.iterdir():
                if not proj_dir.is_dir():
                    continue
                if not (proj_dir.name.startswith("-home-") or proj_dir.name.startswith("-Users-")):
                    continue
                display_name = project_name(proj_dir)
                try:
                    source_files.extend((path, display_name)
                                        for path in proj_dir.rglob("*.jsonl"))
                except OSError:
                    continue
        except OSError:
            pass

    now_tw = datetime.now(TW)
    monday = now_tw.date() - timedelta(days=now_tw.weekday())
    week_start = datetime.combine(monday, datetime.min.time(), tzinfo=TW).timestamp()
    source_files.extend(_dispatch_files(dispatch_dir, week_start))

    for jsonl_file, project_display_name in source_files:
            try:
                stat = jsonl_file.stat()
            except OSError:
                continue

            file_key = str(jsonl_file)
            cached = file_cache.get(file_key, {})
            cached_messages, cached_anonymous = _cache_records(cached)
            valid_cache = (cached.get("version") == FILE_CACHE_VERSION
                           and isinstance(cached.get("messages"), dict)
                           and isinstance(cached.get("anonymous"), list))
            last_size = cached.get("size", 0)
            last_mtime = cached.get("mtime", 0)
            last_offset = cached.get("offset", 0)

            current_size = stat.st_size
            current_mtime = int(stat.st_mtime)

            # 檢查檔案是否有變動
            if valid_cache and current_size == last_size and current_mtime == last_mtime:
                _add_file_records(cached, today_by_model, week_by_model,
                                  project_tokens, project_display_name)
                continue

            # 只有單純 append 才沿用既有 id 快取；舊格式、截斷或同大小改寫都重掃。
            append_only = (valid_cache and current_size > last_size
                           and current_mtime >= last_mtime)
            if not append_only:
                last_offset = 0
                cached_messages, cached_anonymous = {}, []

            new_offset, records = _process_file(jsonl_file, last_offset)
            bytes_read = new_offset - last_offset
            total_bytes_read += bytes_read

            messages = dict(cached_messages)
            anonymous = list(cached_anonymous)
            for rec in records:
                record = _record_for_cache(rec)
                message_id = rec.get("message_id")
                if message_id:
                    messages[message_id] = record
                else:
                    anonymous.append(record)

            # 更新快取
            file_cache[file_key] = {
                "version": FILE_CACHE_VERSION,
                "size": current_size,
                "mtime": current_mtime,
                "offset": new_offset,
                "messages": messages,
                "anonymous": anonymous,
            }
            _add_file_records(file_cache[file_key], today_by_model, week_by_model,
                              project_tokens, project_display_name)

    # 計算總 token
    today_tokens = 0
    for model_usage in today_by_model.values():
        today_tokens += sum(model_usage.values())

    # 計算專案佔比（過濾掉 tokens 為 0 的專案）
    projects_list = []
    for name, tokens in sorted(project_tokens.items(), key=lambda x: -x[1]):
        if tokens <= 0:
            continue
        percent = (tokens / today_tokens * 100) if today_tokens > 0 else 0.0
        projects_list.append({
            "name": name,
            "tokens": tokens,
            "percent": round(percent, 1),
        })

    # 只取 Top 5
    projects_list = projects_list[:5]

    # 儲存快取
    cache["files"] = file_cache
    cache["scan_date"] = today_str
    _save_cache(cache_dir, cache)

    totals_data = {
        "scan_date": today_str,
        "today_by_model": today_by_model,
        "week_by_model": week_by_model,
        "project_tokens": project_tokens,
    }
    _save_totals_cache(cache_dir, totals_data)

    return {
        "bytes_read": total_bytes_read,
        "totals": {
            "today_tokens": today_tokens,
            "today_by_model": today_by_model,
            "week_by_model": week_by_model,
        },
        "projects": projects_list,
    }
