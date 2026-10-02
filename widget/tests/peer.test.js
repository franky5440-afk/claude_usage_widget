// 對方機器的 session（SPEC §13 peer，Frank 2026-10-02 拍板）。執行：node --test widget/tests/*.js
// 規則：peer 為 null、ok 不是 true、或 sessions 為空 → 整段不畫（回 null）。
const test = require("node:test");
const assert = require("node:assert/strict");
const view = require("../claude-usage.widget/lib/view.js");

const S = (project) => ({ project, tokens: 1000, percent: 1, context_window: 1000000,
                          last_active_at: "2026-10-02T22:00:00+08:00" });

test("peerView：沒有 peer 或 peer 不是物件 → null", () => {
  assert.equal(view.peerView({}), null);
  assert.equal(view.peerView({ peer: null }), null);
  assert.equal(view.peerView({ peer: "x" }), null);
  assert.equal(view.peerView({ peer: [] }), null);
  assert.equal(view.peerView(null), null);
});

test("peerView：ok 不是 true → null（含 truthy 但非 true 的值）", () => {
  for (const ok of [false, null, undefined, 1, "true"]) {
    assert.equal(view.peerView({ peer: { label: "Linux", ok, sessions: [S("a")] } }), null, String(ok));
  }
});

test("peerView：sessions 空、缺或不是陣列 → null", () => {
  assert.equal(view.peerView({ peer: { label: "Linux", ok: true, sessions: [] } }), null);
  assert.equal(view.peerView({ peer: { label: "Linux", ok: true } }), null);
  assert.equal(view.peerView({ peer: { label: "Linux", ok: true, sessions: "x" } }), null);
});

test("peerView：label 不是非空字串 → null", () => {
  for (const label of [undefined, null, "", "   ", 3]) {
    assert.equal(view.peerView({ peer: { label, ok: true, sessions: [S("a")] } }), null, String(label));
  }
});

test("peerView：正常資料回 label 與 sessions，最多 3 條", () => {
  const v = view.peerView({ peer: { label: "Linux", ok: true, error: null,
    sessions: [S("a"), S("b"), S("c"), S("d")] } });
  assert.equal(v.label, "Linux");
  assert.deepEqual(v.sessions.map((s) => s.project), ["a", "b", "c"]);
});

test("peerView：sessions 裡不是物件的項目略過", () => {
  const v = view.peerView({ peer: { label: "Linux", ok: true, sessions: [null, "x", 3, S("a")] } });
  assert.deepEqual(v.sessions.map((s) => s.project), ["a"]);
});

test("peerView：不改動傳入物件", () => {
  const sessions = [S("a"), S("b"), S("c"), S("d")];
  const state = { peer: { label: "Linux", ok: true, sessions } };
  view.peerView(state);
  assert.equal(state.peer.sessions.length, 4);
});

test("normalizeState 保留 peer 原樣（不由 normalize 決定顯示與否）", () => {
  const peer = { label: "Linux", ok: false, sessions: [], error: "timeout", generated_at: null };
  assert.deepEqual(view.normalizeState({ peer }).peer, peer);
});
