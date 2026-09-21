// Session 閒置時間文字的驗收測試（CONTRACT-5.md）。執行：node --test widget/tests/*.js
const test = require("node:test");
const assert = require("node:assert/strict");
const view = require("../claude-usage.widget/lib/view.js");

const NOW = Date.parse("2026-09-21T12:00:00+08:00");
const ago = (sec) => new Date(NOW - sec * 1000).toISOString();

test("一分鐘內算使用中", () => {
  assert.equal(view.idleText(ago(0), NOW), "使用中");
  assert.equal(view.idleText(ago(59), NOW), "使用中");
});

test("未來時間（時鐘誤差）也算使用中", () => {
  assert.equal(view.idleText(ago(-30), NOW), "使用中");
});

test("分鐘、小時、天都無條件捨去", () => {
  assert.equal(view.idleText(ago(60), NOW), "閒置 1 分");
  assert.equal(view.idleText(ago(59 * 60 + 59), NOW), "閒置 59 分");
  assert.equal(view.idleText(ago(3600), NOW), "閒置 1 時");
  assert.equal(view.idleText(ago(23 * 3600 + 3599), NOW), "閒置 23 時");
  assert.equal(view.idleText(ago(86400), NOW), "閒置 1 天");
  assert.equal(view.idleText(ago(3 * 86400 + 5), NOW), "閒置 3 天");
});

test("吃 state.json 裡的台灣時間字串", () => {
  assert.equal(view.idleText("2026-09-21T11:03:11.442944+08:00", NOW), "閒置 56 分");
});

test("缺值或壞值回空字串，不丟例外", () => {
  for (const bad of [null, undefined, "", "not-a-date", 123, {}]) {
    assert.equal(view.idleText(bad, NOW), "");
  }
});
