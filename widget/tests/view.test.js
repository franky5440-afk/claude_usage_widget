// Mac 版 widget 純函式的驗收測試（CONTRACT.md）。執行：node --test widget/tests/
const test = require("node:test");
const assert = require("node:assert/strict");
const view = require("../claude-usage.widget/lib/view.js");

test("formatTokens 與 desklet 一致", () => {
  assert.equal(view.formatTokens(999), "999");
  assert.equal(view.formatTokens(1000), "1.0K");
  assert.equal(view.formatTokens(12345), "12.3K");
  assert.equal(view.formatTokens(1000000), "1.00M");
  assert.equal(view.formatTokens(2934567), "2.93M");
});

test("formatUsd：數字兩位小數，null/undefined 顯示破折號", () => {
  assert.equal(view.formatUsd(12.3), "$12.30");
  assert.equal(view.formatUsd(0), "$0.00");
  assert.equal(view.formatUsd(null), "$—");
  assert.equal(view.formatUsd(undefined), "$—");
});

test("formatContextWindow 不帶多餘小數", () => {
  assert.equal(view.formatContextWindow(1000000), "1M");
  assert.equal(view.formatContextWindow(200000), "200K");
});

test("progressLevel 依 severity 或百分比門檻", () => {
  assert.equal(view.progressLevel("normal", 10), "normal");
  assert.equal(view.progressLevel("normal", 70), "warning");
  assert.equal(view.progressLevel("warning", 5), "warning");
  assert.equal(view.progressLevel("normal", 90), "critical");
  assert.equal(view.progressLevel("critical", 1), "critical");
});

test("barPercent 夾在 0–100，非數字回 0", () => {
  assert.equal(view.barPercent(34), 34);
  assert.equal(view.barPercent(-5), 0);
  assert.equal(view.barPercent(130), 100);
  assert.equal(view.barPercent(undefined), 0);
  assert.equal(view.barPercent(NaN), 0);
  assert.equal(view.barPercent("50"), 0);
});

test("parseState：只接受 JSON 物件", () => {
  assert.deepEqual(view.parseState('{"ok":true}'), { ok: true });
  for (const bad of ["", "not json", "[]", "null", "42", undefined]) {
    assert.equal(view.parseState(bad), null, String(bad));
  }
});

test("normalizeState 補齊缺欄位且不改動傳入物件", () => {
  const input = { ok: false, errors: ["登入已過期"] };
  const frozen = JSON.stringify(input);
  const s = view.normalizeState(input);
  assert.equal(JSON.stringify(input), frozen);
  assert.equal(s.ok, false);
  assert.deepEqual(s.errors, ["登入已過期"]);
  for (const k of ["limits", "projects", "sessions"]) assert.ok(Array.isArray(s[k]), k);
  assert.ok(Array.isArray(s.cost.by_model));
  for (const k of ["today_usd", "week_usd", "pricing_version"]) assert.ok(k in s.cost, k);
  assert.ok("generated_at" in s);
});

test("normalizeState 保留原有值", () => {
  const input = {
    ok: true, errors: [], generated_at: "2026-09-15T12:00:00+08:00",
    limits: [{ label: "本次 session", percent: 3 }],
    cost: { today_usd: 1.5, week_usd: null, pricing_version: "2026-09-08", by_model: [] },
    projects: [{ name: "q", tokens: 1, percent: 100 }], sessions: [],
  };
  const s = view.normalizeState(input);
  assert.equal(s.ok, true);
  assert.equal(s.limits[0].label, "本次 session");
  assert.equal(s.cost.today_usd, 1.5);
  assert.equal(s.cost.week_usd, null);
  assert.equal(s.generated_at, "2026-09-15T12:00:00+08:00");
});

test("normalizeState 面對 null 也回完整結構", () => {
  const s = view.normalizeState(null);
  assert.equal(s.ok, false);
  assert.ok(Array.isArray(s.errors) && Array.isArray(s.limits));
});

test("sessionPercentText：分母未知時留白不猜", () => {
  assert.equal(view.sessionPercentText({ percent: 13.5, context_window: 1000000 }), "13.5% of 1M");
  assert.equal(view.sessionPercentText({ percent: 23, context_window: 200000 }), "23% of 200K");
  assert.equal(view.sessionPercentText({ percent: null, context_window: null }), "");
  assert.equal(view.sessionPercentText({ percent: 5, context_window: null }), "");
});
