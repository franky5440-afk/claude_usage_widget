import { run } from "uebersicht";
import * as view from "./lib/view";

export const SHOW_COST = true;
export const SHOW_PROJECTS = true;
export const SHOW_SESSIONS = true;
export const WIDTH = 320;
// 桌面位置（px）。Übersicht 不支援滑鼠拖拉，要換位置就改這裡，
// 例如右下角改成 { bottom: 20, right: 20 }
export const POSITION = { top: 20, left: 20 };
export const refreshFrequency = 30000;

const STATE_PATH = '"$HOME/.cache/claude-usage-widget/state.json"';

// 只有確認解析出的目錄真的是本 repo 才執行 collector，避免在意外目錄跑 python -m
export const command = `R="$(cd claude-usage.widget 2>/dev/null && pwd -P)" && [ -n "$R" ] && cd "$R/../.." && [ -f collector/main.py ] && (/usr/bin/python3 -m collector.main >/dev/null 2>&1 || true); cat ${STATE_PATH} 2>/dev/null || true`;
const OPEN_REPORT = 'open "$HOME/.cache/claude-usage-widget/report.html"';

const esc = (value) => String(value == null ? "" : value);

const Section = ({ title, children }) => (
  <section className="section">
    <h3>{title}</h3>
    {children}
  </section>
);

const Limits = ({ limits }) => (
  <Section title="額度使用">
    {limits.map((limit, index) => {
      const percent = view.barPercent(limit.percent);
      return (
        <div className="limit" key={index}>
          <div className="limit-header"><span>{limit.label || "未知限制"}</span><strong>{limit.percent == null ? "—" : `${limit.percent}%`}</strong></div>
          <div className="progress"><div className={`progress-fill ${view.progressLevel(limit.severity, percent)}`} style={{ width: `${percent}%` }} /></div>
          <small>{limit.resets_in_text ? `重置：${limit.resets_in_text}` : (limit.resets_at ? `重置：${limit.resets_at}` : "")}</small>
        </div>
      );
    })}
  </Section>
);

const Cost = ({ cost }) => !SHOW_COST ? null : (
  <Section title="成本估算">
    <div className="cost-row cost-header"><span /><strong>今日</strong><strong>本週</strong></div>
    {cost.by_model.map((entry, index) => (
      <div className="cost-row" key={index}><span>{entry.label || entry.model || ""}</span><strong>{view.formatUsd(entry.today_usd)}</strong><strong>{view.formatUsd(entry.week_usd)}</strong></div>
    ))}
    <div className="cost-row total"><span>合計</span><strong>{view.formatUsd(cost.today_usd)}</strong><strong>{view.formatUsd(cost.week_usd)}</strong></div>
    <small className="note">參考估算值（Max 訂閱制不依此收費）</small>
  </Section>
);

const Projects = ({ projects }) => !SHOW_PROJECTS ? null : (
  <Section title="專案排行 (Top 5)">
    {projects.map((project, index) => <div className="data-row" key={index}><span>{project.name || "未知專案"}</span><span>{view.formatTokens(project.tokens || 0)}</span><strong>{project.percent == null ? "—" : `${project.percent.toFixed(1)}%`}</strong></div>)}
  </Section>
);

const Sessions = ({ sessions }) => !SHOW_SESSIONS ? null : (
  <Section title="Session Context">
    {sessions.map((session, index) => <div className="data-row" key={index}><span>{session.project || "未知專案"}</span><span>{view.formatTokens(session.tokens || 0)}</span><strong>{view.sessionPercentText(session) || "—"}</strong></div>)}
  </Section>
);

export const render = ({ output }) => {
  const parsed = view.parseState(output);
  if (!parsed) return <div className="widget empty" style={{ width: WIDTH }} onClick={() => run(OPEN_REPORT)}><style>{style}</style>尚無資料，collector 執行中…</div>;
  const state = view.normalizeState(parsed);
  return (
    <div className="widget" style={{ width: WIDTH }} onClick={() => run(OPEN_REPORT)}>
      <style>{style}</style>
      <Limits limits={state.limits} />
      <Cost cost={state.cost} />
      <Projects projects={state.projects.slice(0, 5)} />
      <Sessions sessions={state.sessions} />
      {state.errors.length > 0 && <div className="errors">{state.errors.map((error, index) => <div key={index}>{esc(error)}</div>)}</div>}
      <div className="updated">更新：{esc(state.generated_at)}</div>
    </div>
  );
};

export const className = { ...POSITION, width: WIDTH, fontFamily: "-apple-system", fontSize: "12px", color: "var(--text-color)" };

export const style = `
  .widget { box-sizing: border-box; padding: 10px; border-radius: 8px; background: rgba(255,255,255,.72); color: #202124; box-shadow: 0 2px 12px rgba(0,0,0,.16); backdrop-filter: blur(14px); }
  .section { margin-bottom: 9px; } h3 { margin: 0 0 5px; font-size: 13px; } .limit { margin-bottom: 6px; }
  .limit-header, .cost-row, .data-row { display: flex; gap: 8px; align-items: baseline; } .limit-header span, .cost-row span:first-child, .data-row span:first-child { flex: 1; }
  .progress { height: 7px; overflow: hidden; margin: 3px 0; border-radius: 4px; background: rgba(0,0,0,.18); } .progress-fill { height: 100%; background: #5294e2; } .progress-fill.warning { background: #f0ad4e; } .progress-fill.critical { background: #d9534f; }
  small, .updated { opacity: .68; font-size: 10px; } .cost-row strong:last-child, .data-row strong { min-width: 80px; text-align: right; } .cost-row strong { min-width: 54px; text-align: right; } .total { margin-top: 3px; } .note { font-style: italic; } .errors { margin: 5px 0; color: #c0392b; } .updated { text-align: right; }
  @media (prefers-color-scheme: dark) { .widget { background: rgba(35,35,38,.82); color: #f2f2f2; box-shadow: 0 2px 12px rgba(0,0,0,.4); } .progress { background: rgba(255,255,255,.2); } .errors { color: #ff8a80; } }
`;
