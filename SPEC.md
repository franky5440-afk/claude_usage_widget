# SPEC — Cinnamon 桌面 Claude 用量 Widget

版本 0.1（2026-09-08 建立）。本檔是**唯一規格權威**；實作行為規則見 `AGENTS.md`，
專案脈絡見 `CLAUDE.md`。三份檔不重複同一件事。

---

## 1. 目標

在 Cinnamon 桌面上常駐一個 desklet，隨時看得到 Claude 用量，不必開瀏覽器或打指令。

必須同時呈現三類資訊（Frank 2026-09-08 拍板，三者皆為必要，非二選一）：

| # | 區塊 | 內容 | 資料來源 |
|---|---|---|---|
| A | **額度**（主視覺） | 5 小時 session %、每週 %、分模型週限 %，各自的重置時間 | Usage API |
| B | **成本估算** | 今日 / 本週的 token 換算美金 | 逐字稿 + 價格表 |
| C | **專案排行** | 各專案今日 token 佔比（Top 5） | 逐字稿 |

---

## 2. 資料來源（皆已實測，Evidence 層）

### 2.1 來源 A：Usage API（額度百分比）

```
GET https://api.anthropic.com/api/oauth/usage
Authorization: Bearer <claudeAiOauth.accessToken>
anthropic-beta: oauth-2025-04-20
```

Token 取自 `~/.claude/.credentials.json` 的 `claudeAiOauth.accessToken`。
2026-09-08 實測 HTTP 200，回傳與 claude.ai Settings→Usage 畫面一致。

**只讀 `limits` 陣列，不要硬編模型名。** 每個元素長這樣：

```json
{
  "kind": "session | weekly_all | weekly_scoped",
  "group": "session | weekly",
  "percent": 34,
  "severity": "normal",
  "resets_at": "2026-09-11T17:00:00+00:00",
  "scope": { "model": { "display_name": "Fable" }, "surface": null },
  "is_active": true
}
```

顯示規則：
- 標題文字＝`scope.model.display_name` 有值就用它，否則依 `kind` 對應
  （`session`→「本次 session」、`weekly_all`→「本週全部模型」）。
- **未來多出新的 limit 條目要能自動顯示**，不得因為程式沒認得就整條吞掉。
- `resets_at` 是 UTC，**顯示一律換算台灣時間（UTC+8）**，格式如「4 小時 46 分後重置」。

頂層還有 `five_hour` / `seven_day` 等欄位，與 `limits` 重複，**只當 `limits` 缺漏時的
fallback**，不平行維護兩套邏輯。

### 2.2 來源 B：逐字稿（token 實算）

`~/.claude/projects/<專案目錄名>/**/*.jsonl`，每行一個 JSON。
`type == "assistant"` 的行有 `message.model` 與 `message.usage`：

```json
{"input_tokens":2,"cache_creation_input_tokens":42032,
 "cache_read_input_tokens":29800,"output_tokens":489,
 "output_tokens_details":{"thinking_tokens":184}}
```

專案名＝目錄名反解（`-home-lintzuyang-Claude-quantum` → `quantum`）。
時間戳用該行的 `timestamp`（UTC），分日一律按**台灣時間**切。

⚠️ **不要用 `~/.claude/stats-cache.json`。** 它停在 2026-08-12 就沒再更新，是死資料。

---

## 3. 🔴 硬性效能約束

本機是 **2012 iMac (i5)**，且逐字稿現況 **335 檔 / 254 MB 且持續長大**。

- **禁止每次更新都全量掃描。** 必須做增量：記住每個檔的 `(size, mtime)`，
  只讀「變大的檔案從上次 offset 之後的部分」，其餘直接跳過。
- 快取放 `~/.cache/claude-usage-widget/`，不寫進專案目錄、不寫進 `~/.claude`。
- **絕不在 desklet 的 GJS 主執行緒解析 jsonl** —— 會直接凍住整個桌面。

---

## 4. 架構：兩層，用一個 JSON 檔接起來

```
collector/（Python 3，背景執行）
   └─ 讀 API + 增量掃逐字稿 → 寫 state.json
                    ↓
desklet/（cjs/GJS，只讀 state.json 畫圖）
```

分層理由：GJS 適合畫 UI、不適合啃 254MB 檔案；Python 適合啃檔案、不該碰 UI。
接縫只有一個檔，兩邊可獨立測試與替換。

### 4.1 介面契約（**先定死，實作不得更動**）

collector 輸出 `~/.cache/claude-usage-widget/state.json`，schema：

```json
{
  "schema_version": 1,
  "generated_at": "2026-09-08T21:55:00+08:00",
  "ok": true,
  "errors": [],

  "limits": [
    { "label": "本次 session", "percent": 3, "severity": "normal",
      "resets_at": "2026-09-09T02:40:00+08:00", "resets_in_text": "4 小時 46 分後" }
  ],

  "cost": {
    "today_usd": 12.34,
    "week_usd": 78.90,
    "pricing_version": "2026-09-08",
    "by_model": [
      { "model": "claude-opus-5", "label": "Opus 5",
        "today_usd": 8.20, "week_usd": 51.30 }
    ]
  },

  "projects": [
    { "name": "quantum", "tokens": 1234567, "percent": 42.1 }
  ],

  "totals": {
    "today_tokens": 2934567,
    "today_by_model": {
      "claude-opus-5": { "input_tokens": 120, "output_tokens": 45000,
                         "cache_creation_input_tokens": 300000,
                         "cache_creation_1h_input_tokens": 600000,
                         "cache_read_input_tokens": 1954880 }
    }
  }
}
```

規則：
- **`today_by_model` 的值是「分項 usage dict」不是單一數字**——成本估算要分別套用
  input / output / cache 寫入 / cache 讀取四種單價，只有總數算不出金額。
- **cache 寫入拆成不重疊的兩塊**（Frank 2026-09-23）：`cache_creation_1h_input_tokens` 是 1 小時 cache 寫入，
  `cache_creation_input_tokens` 是**扣掉 1h 之後**的部分（5 分鐘）。兩者相加＝逐字稿的總寫入，
  所以把 dict 的值全部加總仍是正確的 token 總數。來源是逐字稿 `usage.cache_creation.ephemeral_1h_input_tokens`；
  沒有這個明細的舊資料一律算 5 分鐘。
- **所有時間欄位一律已經是台灣時間（UTC+8）的 ISO 字串**，desklet 不做時區換算。
- **`ok: false` 時其餘欄位仍須存在**（可為空陣列 / null），desklet 不得因缺欄位而炸掉。
- `errors` 是人看得懂的中文字串陣列，會直接顯示在 widget 上。

### 4.2 失敗必須是「可讀的降級」，不是空白

| 狀況 | 行為 |
|---|---|
| API 401 / token 過期 | `ok:false`、errors 加「登入已過期，請在終端機執行一次 claude」。**B、C 區塊照常顯示**（不依賴 API） |
| 沒有網路 | 同上，額度區塊顯示上次成功的數值並標「(舊資料)」 |
| `.credentials.json` 讀不到 | 同上，訊息換成「找不到憑證檔」 |
| 逐字稿目錄不存在 | 額度照常，B/C 顯示「—」 |

---

## 5. 🔒 安全約束（不可協商）

1. **憑證只讀，絕不寫入。** collector **不得**嘗試 refresh token、不得改寫
   `~/.claude/.credentials.json`。token 過期就降級顯示，由 Frank 自己跑一次 `claude` 續期。
   （理由：跟 CLI 搶著寫憑證檔會把登入狀態弄壞。）
2. **token 絕不出現在 log、stdout、state.json、錯誤訊息、commit 裡。** 任何一處出現即為缺陷。
3. `state.json` 權限設 `0600`。
4. **只打 `api.anthropic.com` 這一個網域**，不得有其他對外連線、不得有遙測。
5. `.gitignore` 必須擋掉快取與任何 `*.credentials*`。

---

## 6. 成本估算（B 區塊）

價格表獨立成 `collector/pricing.json`，欄位含 `input` / `output` /
`cache_write` / `cache_write_1h` / `cache_read` 的每百萬 token 單價與 `version` 日期。
`cache_write` 是 5 分鐘 cache 寫入價（input × 1.25），`cache_write_1h` 是 1 小時 cache 寫入價（input × 2）。

- 程式**不得把價格寫死在 .py 裡**，一律讀 JSON。
- 找不到某個模型的價格 → 該模型不計入，並在 `errors` 加一條「模型 X 無價格資料」，
  **不得靜默當 0**（靜默當 0 會讓金額看起來很漂亮但是錯的）。
- ⚠️ 顯示時要標明這是**參考估算值**：Max 訂閱制下實際不會照這個金額收費。

### 6.1 分模型明細（`cost.by_model`）

只有總額看不出錢花在哪個模型上，所以總額之外還要給分項。

- 陣列，**依 `week_usd` 由大到小排序**，花最多的排最前面。
- **只列有用量的模型**（所有分項全為 0 的跳過，與 §6 的錯誤訊息規則一致）。
- 查不到價格的模型**不進這個陣列**（沒有金額可放），但 §6 的錯誤訊息照舊要有——
  使用者從錯誤訊息知道為什麼它沒出現，不是被無聲吞掉。
- `label` 是給人看的短名稱，**存在 `pricing.json` 每個模型的 `display` 欄位**，
  不在程式裡寫死對照表，也不從 model id 硬拼（`claude-fable-5-1` 拼不出「Fable 5.1」）。
- 🔴 **成本算法只能有一套。** 分項與總額必須來自同一個計算函式，
  不得為了分項另寫一份乘法——兩份遲早會對不起來，而且對不起來時沒人看得出是哪邊錯。

⚠️ **`pricing.json` 的 `version` 欄位在價格表內容變動時必須跟著更新**，
它會顯示在 widget 上；表變了版本沒變等於騙人。

---

## 7. 更新頻率

- API：每 **5 分鐘**。⚠️ **這不是禮貌問題，是硬限制**——2026-09-08 實際被
  Anthropic 回 `429 Too Many Requests`，額度區塊整塊變空白。
  原因是 desklet 每 30 秒更新一次、每次都叫 collector、collector 每次都打 API。
  ⇒ **節流必須做在 collector 裡**（`fetch_usage_throttled`），不能指望呼叫端自律：
  desklet 的更新間隔是使用者可調的，最短 10 秒。
  被回 429 之後改用 **15 分鐘** 的退避間隔，且**沿用上次成功的資料繼續顯示**
  （標明是舊資料），不要變成空白。相關契約由 tests 中「API 節流」那三條守著。
- 逐字稿增量掃描：每 **60 秒**。
- desklet 讀 `state.json`：每 **30 秒**，用 `GLib.spawn_async` 非同步呼叫 collector，
  **不得用同步呼叫**（會凍桌面）。

---

## 8. Desklet 規格

- 安裝路徑 `~/.local/share/cinnamon/desklets/claude-usage@lintzuyang/`
- 環境：Cinnamon **6.6.9**、直譯器 `cjs`（GJS）
- 必要檔：`metadata.json`、`desklet.js`、`settings-schema.json`、`stylesheet.css`
- 可設定項（settings-schema）：更新間隔、是否顯示成本、是否顯示專案排行、寬度
- UI：額度用橫條進度條（對應截圖那三條），成本與排行用文字列
- 深淺色主題都要能看（用 Cinnamon 主題色，不要寫死背景色）

---

## 9. 驗收標準

1. `python3 collector/main.py` 跑得完，產出的 `state.json` **完全符合 §4.1 schema**。
2. 測試全綠：`python3 -m pytest tests/ -v`。
3. 斷網 / 假造壞 token 兩種情境下，collector 仍 exit 0 且產出合法 `state.json`（`ok:false`）。
4. 第二次執行明顯比第一次快（證明增量掃描真的有生效，不是每次全掃）。
5. desklet 加到桌面後不當機，數字與 `claude.ai → Settings → Usage` 一致。
6. `grep -rE "sk-|accessToken|Bearer [A-Za-z0-9]" --include=*.py --include=*.js --include=*.json .`
   在 repo 內查無憑證值。

---

## 10. D 區塊：單一 session 的 context 佔用（2026-09-13 追加）

回答「我現在這個對話用掉多少 context」，與 A 區塊的**額度百分比意義完全不同**：
額度是計費窗口的消耗，context 是這一輪送進模型的對話長度，會因 compaction 下降。
**兩者不可互相換算、不可共用欄位。**

### 11.1 資料來源（2026-09-13 實測，Observation 層）

同樣讀 `~/.claude/projects/**/*.jsonl`，但**不走增量掃描那條路**——
增量掃描累加全部歷史，這裡要的是「最後一則的當下值」。

- **分子**：最後一則 `type=="assistant"` 且 `isSidechain != true` 的
  `message.usage` 之 `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`。
  **`output_tokens` 不算**（下一輪才進 context）。
- **分母**：最後一則 `type=="attachment"` 且 `attachment.type=="model"` 的
  `attachment.identity.modelId`。含 `[1m]` → 1,000,000；開頭是 `claude-fable-5`（含 5.1）或 `claude-opus-5` → 1,000,000（原生 1M、不帶標記，Frank 2026-09-17）；否則 → 200,000。
- 🔴 **查不到 modelId 時 `context_window` 與 `percent` 一律 `null`，不得預設 200,000。**
  實測預設 20 萬會讓 1M 的 session 算出 116.5% 這種鬼數字，比留白更糟。

### 11.2 顯示規則（Frank 2026-09-13 拍板：方案 B）

顯示**最近 5 分鐘內有活動**的 session，依活動時間由新到舊，**最多 3 條**。
理由：本機常態就是多開，只顯示一條會在多個 session 之間跳來跳去。

**2026-09-21 Frank 改：拿掉 5 分鐘窗口，常駐顯示最近活動的 3 條**，session idle 之後不再消失
（collector 呼叫 `active_sessions(window_minutes=None)`）。不設窗口時仍依 mtime 排序、湊滿 3 條就停，
更舊的檔不得開啟（測試 `test_不設窗口時_湊滿_limit_後其餘檔不得被開啟`）。

entrypoint 以 `sdk-` 開頭的 session（Agent SDK／`claude -p` 叫出來、跑完即結束）不列入，也不佔 3 條上限（Frank 2026-09-21）。

### 11.3 效能（實測，不是估計）

按檔案 mtime 篩掉窗口外的檔，**只讀留下來那幾個檔的頭尾各數百 KB**。
2026-09-13 實測：115 個逐字稿檔中選出 4 個計算，**耗時 0.017 秒**。
🔴 **窗口外的檔不得被開啟**（SPEC §3），由測試 `test_窗口外的檔案不得被開啟` 守著。

### 11.4 state.json 欄位（§4.1 schema 的追加）

```json
"sessions": [
  { "project": "quantum", "tokens": 229567, "context_window": 1000000,
    "percent": 23.0, "model": "claude-opus-5[1m]",
    "last_active_at": "2026-09-13T01:00:00+08:00" }
]
```

`ok:false` 時仍須存在（空陣列）。完整契約見 `tests/test_session_context.py`。

---

## 12. Mac 移植（2026-09-15 追加）

### 12.1 平台差異
- 逐字稿目錄在 macOS 是 `-Users-<user>-...`，與 `-home-` 同規則反解；`~/Claude main/<專案>` 編碼成 `Claude-main-<專案>`，反解時去掉 `main-`。
- 反解有損（結果含 `--` 或以 `-` 開頭／結尾，例如中文專案名 `業務自動助理` → `------`）時，改讀該目錄最新逐字稿檔頭 64 KB 的第一個 `cwd`；`cwd` 的非英數字元換成 `-` 後須與目錄名完全相同才採用，取最後一層資料夾名，否則照舊用反解結果。無損的目錄不開檔。C、D 區塊共用 `transcript_scan.project_name`（Frank 2026-09-21）。
- 憑證：macOS 先查 Keychain（服務名 `Claude Code-credentials`，以 `/usr/bin/security` 讀取、逾時 10 秒），查不到才讀 `~/.claude/.credentials.json`。§5 安全約束不變。
- 前端：Übersicht widget（`widget/claude-usage.widget/`），collector 固定用 `/usr/bin/python3` 執行。

### 12.2 🔴 同一則回覆只算一次（修正 §2.2）
Claude Code 會把一則回覆的每個 content block 各寫成一行，每行帶同一個 `message.id` 與 usage；
串流中的行 `output_tokens` 尚未長完，最後一行才是最終值。2026-09-15 實測逐行累加使今日用量高估 3.81 倍（CLI）與 1.83 倍（Dispatch）。
- **同一個檔內同一個 `message.id` 只計一次，以最後出現的那一行為準**；增量掃描跨越同一則回覆時，後來的行取代先前的貢獻。
- 沒有 `message.id` 的行照舊逐行計。
- 今日、本週、專案排行、歷史帳本全部適用同一規則（成本算法只能有一套，§6.1）。
- 歷史帳本 `schema_version` 升為 **2**；讀到舊版帳本時自動全量重建一次（不是損毀，不得出現損毀提醒）。

### 12.3 Dispatch（Claude 桌面版）用量（Frank 2026-09-15 拍板）
資料來源：`~/Library/Application Support/Claude/local-agent-mode-sessions/<acct>/<org>/`
- 主 session：`agent/local_ditto_<org>/audit.jsonl`；派出的子 session：`local_<uuid>/audit.jsonl`。**只讀 `audit.jsonl`**。
- assistant 行 `message.usage` 與 CLI 同格式；子代理的行帶非 null 的 `parent_tool_use_id`；`system` 行的 `model` 是模型 id。
- ⚠️ 屬桌面版內部格式、未公開，改版可能失效；讀不到時該部分視為沒有資料，不得讓 collector 失敗。

用途：
- **B 成本／C 排行／歷史帳本**：全部 assistant 行（含子代理）計入，專案名一律 `Dispatch`。走增量掃描；**mtime 早於本週一（台灣時間）的檔不開啟**（實測 1257 檔／503MB，絕大多數是舊檔）。
- **D Session Context**：主 session 顯示為 `Dispatch`、子 session 為 `Dispatch 子任務`；context＝最後一則 `parent_tool_use_id` 為 null 的 assistant usage；分母依最後一筆 `system.model`，規則同 §11.1（Opus 5／Fable 5 系列不帶 `[1m]` 也是 1M；2026-09-15 實機套 200K 曾算出 110.3%）；查不到→null。與 CLI session 一起依 mtime 排序、共用窗口設定（2026-09-21 起不設窗口，見 §11.2）與 3 條上限；窗口外的檔不得開啟。

契約：`tests/test_dispatch.py`、`tests/test_dedupe.py`。
