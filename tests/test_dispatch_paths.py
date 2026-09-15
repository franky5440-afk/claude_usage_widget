"""Dispatch 找檔只走 SPEC §12.3 的固定層級，不遞迴（實測遞迴 15.8 萬個子目錄要 2–3 秒）。"""
from collector import transcript_scan


def _touch(p):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("")
    return p


def test_只列出固定層級的_audit_jsonl(tmp_path):
    main_s = _touch(tmp_path / "acct" / "org" / "agent" / "local_ditto_org" / "audit.jsonl")
    child = _touch(tmp_path / "acct" / "org" / "local_1111" / "audit.jsonl")
    _touch(tmp_path / "acct" / "org" / "local_1111" / "outputs" / "deep" / "audit.jsonl")
    _touch(tmp_path / "acct" / "org" / "local_1111" / "other.jsonl")
    _touch(tmp_path / "skills-plugin" / "audit.jsonl")

    found = sorted(str(p) for p in transcript_scan.dispatch_audit_files(tmp_path))

    assert found == sorted([str(main_s), str(child)])


def test_目錄不存在或未指定時回空(tmp_path):
    assert transcript_scan.dispatch_audit_files(None) == []
    assert transcript_scan.dispatch_audit_files(tmp_path / "nope") == []
