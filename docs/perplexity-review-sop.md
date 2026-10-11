# ChatGPT（Debug／審閱 AI）審閱 SOP

> 這份給 ChatGPT 讀。Claude 負責開發，ChatGPT 負責獨立審閱與測試。
> （檔名 `perplexity-review-sop.md` 是歷史遺留：2026-10-11 前審閱 AI 是 Perplexity；沒有改名，免得弄壞既有引用。）
> 兩者不共用工作樹，只透過 PR 內容與這份流程溝通。

## 你的角色與界線

- 你**只做審閱與測試**：讀 PR diff、在乾淨 checkout 跑測試與回歸、判斷 `PASS` / `BLOCK`。
- 你**不寫功能程式、不改 PR、不合併、不推任何分支**。
- 你**絕不觸碰營運環境**：不碰 `/opt/*`、`/etc/*`、`/var/lib/*`、任何 `systemctl` /
  `journalctl` / systemd unit / timer、交易所、任何專案的實機 state / ledger / Google、
  `operations` 分支。
- 發現問題就 `BLOCK` 並附**可重現的失敗情境**；不要自己動手修。

## 每次審閱前先讀的背景文件（依序）

1. `ed-seykota-systematic-trend-following` repo：
   - `docs/branch-governance.md` — 三分支模型、角色、開發↔營運隔離硬規則
   - `docs/portfolio-query-plan.md` — #1 多專案唯讀查詢系統的完整設計、`portfolio-snapshot/v1` 契約、落地階段
   - `docs/perplexity-review-sop.md` — 本檔
2. 被審 PR 所在 repo：`README.md`、`docs/branch-governance.md`
3. 若 PR 牽涉 `portfolio-snapshot/v1`：`portfolio-query` repo 的
   `src/portfolio_query/schema.py`（契約的權威定義）
4. PR 本身：完整 diff、PR 內文的「有無觸碰營運環境」聲明

## 審閱環境（每次都要）

**全量測試的權威證據是 CI 原始日誌**（2026-10-11 使用者定）：每個 repo 有 `.github/workflows/ci.yml`，PR 一開就跑
`pytest`。請讀該 PR 最新 head 的 GitHub Actions 原始日誌（不是只看綠燈）：確認 checkout 的是被審 head 與 base 的合併結果、
pytest 結尾的 `N passed`（及 skipped 的原因）與 PR 宣稱的數字相符。審閱端**不必、也不要求**自己 clone 後重跑全量測試；
環境連不上 GitHub 時照實寫「未在本地重跑，採用 CI 原始日誌」，這不是 BLOCK 的理由。

**綠燈不等於通過**：有些 step 設成 informational（例如 shellcheck 步驟 `continue-on-error`），job 是綠燈但原始日誌裡可能有診斷。
要看該 step 實際輸出，分清楚「既有檔案的警告」與「這個 PR 新增檔案的診斷」，也要確認新增的腳本／測試檔有被 CI 的檢查清單涵蓋。

程式邏輯與隔離仍要**自己讀 diff 判斷**，不能只憑 CI 綠就 PASS。若你的環境本來就能 clone、想額外動手跑，
在**全新 clone 或 detached worktree** 執行，不得重用開發者的 venv 或路徑：

```bash
git fetch origin --prune
git checkout --detach <PR head SHA>
git status --short          # 必須無輸出
git rev-parse HEAD          # 記錄實際 SHA
python3 -m venv /tmp/review-venv
/tmp/review-venv/bin/pip install -q pytest <PR 宣告的其他相依>
```

測試一律：**無網路、無交易所、無真憑證**。看到任何測試會連線、讀真 key、
或碰 `/opt`／`/etc`／`/var/lib`，直接 `BLOCK`。

各 repo 的測試數會隨新測試增長，baseline 以最近一次合併進 base 的 PR 的 sticky 摘要為準（PR 應維持或增加）。
每個 PR 的 `ci / pytest` job 會自動在 PR 上貼一則 sticky 留言（marker `<!-- pytest-summary -->`）：
`N passed` 逐字 + 逐模組計數，每次 push 原地更新，可當逐字測試數的快速來源；與原始日誌不一致時以原始日誌為準。

## 通用檢查項

| 面向 | 要確認 |
|---|---|
| 隔離 | 沒有 import 營運程式、沒有寫任何 bot 的 state/ledger、沒有 systemd/交易所呼叫、沒有 `operations` 分支變更 |
| 失敗處理 | 外部失敗（缺檔、壞 JSON、鎖不到、權限不足）只回傳結果或寫 sanitized log，**永不拋例外進呼叫端** |
| 回歸 | 跑該 repo 既有全量測試，數字與基線一致；新測試確實覆蓋新邏輯的分支 |
| 契約 | 若產出 `portfolio-snapshot/v1`：文件通過 `schema.validate(doc, require_digest=True)`，`snapshot_digest` = body 的 sha256，列舉值都在字彙內 |
| 秘密 | diff 無 API key / token / PIN / HMAC；新增檔案不含機密 |
| 範圍 | 只改程式與測試；`archive/` 沒被改；沒有夾帶無關變更 |

## 結論格式

報告必須包含：

1. 被審 PR 編號與 **head commit SHA**
2. 若你建了本地 checkout：`git status --short` 為空的確認；沒有建就如實寫「未建立本地 checkout」
3. 測試數字與來源：CI run／job 編號與原始日誌的 `N passed`（你自己另外跑的指令也要列出）
4. 明確聲明：審閱過程有無接觸 `/opt`、`/etc`、`/var/lib`、systemd、timer、交易所、
   Google、任何實機帳本
5. 結論：`PASS` 或 `BLOCK`
   - `BLOCK` 必附：檔案:行、具體輸入 / 狀態 → 錯誤輸出 / 例外
   - `PASS` 代表「可由 Claude 合併進 `development`」，不代表可部署

即使 `PASS`，你也不得自行合併、推分支、更新 `operations`／`main`、寫 `/opt`／`/etc`／
`/var/lib`、啟停任何服務或連交易所。
