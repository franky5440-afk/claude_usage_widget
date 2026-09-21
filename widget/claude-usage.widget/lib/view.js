"use strict";

function formatTokens(tokens) {
  if (tokens >= 1000000) return (tokens / 1000000).toFixed(2) + "M";
  if (tokens >= 1000) return (tokens / 1000).toFixed(1) + "K";
  return tokens.toString();
}

function formatUsd(value) {
  return "$" + (value !== null && value !== undefined ? value.toFixed(2) : "—");
}

function formatContextWindow(contextWindow) {
  if (contextWindow >= 1000000) return (contextWindow / 1000000) + "M";
  return (contextWindow / 1000) + "K";
}

function progressLevel(severity, percent) {
  if (severity === "critical" || percent >= 90) return "critical";
  if (severity === "warning" || percent >= 70) return "warning";
  return "normal";
}

function barPercent(percent) {
  if (typeof percent !== "number" || !Number.isFinite(percent)) return 0;
  return Math.min(100, Math.max(0, percent));
}

function parseState(text) {
  if (typeof text !== "string" || text.trim() === "") return null;
  try {
    const value = JSON.parse(text);
    return value !== null && typeof value === "object" && !Array.isArray(value)
      ? value
      : null;
  } catch (_) {
    return null;
  }
}

function normalizeState(input) {
  const source = input !== null && typeof input === "object" && !Array.isArray(input)
    ? input
    : {};
  const sourceCost = source.cost !== null && typeof source.cost === "object" && !Array.isArray(source.cost)
    ? source.cost
    : {};

  return Object.assign({}, source, {
    ok: typeof source.ok === "boolean" ? source.ok : false,
    errors: Array.isArray(source.errors) ? source.errors.slice() : [],
    limits: Array.isArray(source.limits) ? source.limits.slice() : [],
    projects: Array.isArray(source.projects) ? source.projects.slice() : [],
    sessions: Array.isArray(source.sessions) ? source.sessions.slice() : [],
    cost: Object.assign({}, sourceCost, {
      today_usd: Object.prototype.hasOwnProperty.call(sourceCost, "today_usd") ? sourceCost.today_usd : null,
      week_usd: Object.prototype.hasOwnProperty.call(sourceCost, "week_usd") ? sourceCost.week_usd : null,
      pricing_version: Object.prototype.hasOwnProperty.call(sourceCost, "pricing_version") ? sourceCost.pricing_version : null,
      by_model: Array.isArray(sourceCost.by_model) ? sourceCost.by_model.slice() : [],
    }),
    generated_at: Object.prototype.hasOwnProperty.call(source, "generated_at") ? source.generated_at : null,
  });
}

function sessionPercentText(session) {
  if (!session || session.percent === null || session.percent === undefined ||
      session.context_window === null || session.context_window === undefined) {
    return "";
  }
  return session.percent + "% of " + formatContextWindow(session.context_window);
}

function idleText(lastActiveAt, nowMs) {
  if (typeof lastActiveAt !== "string") return "";
  const activeMs = Date.parse(lastActiveAt);
  if (Number.isNaN(activeMs)) return "";
  const seconds = (nowMs - activeMs) / 1000;
  if (seconds < 60) return "使用中";
  if (seconds < 3600) return "閒置 " + Math.floor(seconds / 60) + " 分";
  if (seconds < 86400) return "閒置 " + Math.floor(seconds / 3600) + " 時";
  return "閒置 " + Math.floor(seconds / 86400) + " 天";
}

module.exports = {
  formatTokens,
  formatUsd,
  formatContextWindow,
  progressLevel,
  barPercent,
  parseState,
  normalizeState,
  sessionPercentText,
  idleText,
};
