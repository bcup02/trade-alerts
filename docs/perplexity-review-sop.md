# Perplexity（Debug／審閱 AI）審閱 SOP

> 這份給 Perplexity 讀。Claude 負責開發，Perplexity 負責獨立審閱與測試。
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

**權威測試數字先看 CI**：每個 repo 有 `.github/workflows/ci.yml`，PR 一開就跑
`pytest`。先讀該 PR 的 `ci / pytest` check 結果與 log 的 `N passed` 當基準，不要靠
手動重建檔案樹去湊數字（易出錄入手誤）。CI 綠 + 數字符合 PR 宣稱 → 這項就過。

程式邏輯與隔離仍要**自己讀 diff 判斷**，不能只憑 CI 綠就 PASS。需要動手跑時，
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

CI 基線測試數（PR 應維持或增加）：portfolio-query 125、ed-seykota 157、
mexc-4h-momentum 222、my-crypto-bot 66。my-crypto-bot 與 mexc-4h-momentum 的 CI
現在會裝 pinned 相依（`deploy/install_systemd.sh` 同一組）跑全量 `pytest`，不再只跑
snapshot adapter 一檔。每個 PR 的 `ci / pytest` job 會自動在 PR 上貼一則 sticky 留言
（marker `<!-- pytest-summary -->`）：`N passed` 逐字 + 逐模組計數，每次 push 原地更新。
優先讀這則留言取得逐字測試數。

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
2. `git status --short` 為空的確認
3. 逐條指令與**實際測試數字**（例：`42 passed`）
4. 明確聲明：審閱過程有無接觸 `/opt`、`/etc`、`/var/lib`、systemd、timer、交易所、
   Google、任何實機帳本
5. 結論：`PASS` 或 `BLOCK`
   - `BLOCK` 必附：檔案:行、具體輸入 / 狀態 → 錯誤輸出 / 例外
   - `PASS` 代表「可由 Claude 合併進 `development`」，不代表可部署

即使 `PASS`，你也不得自行合併、推分支、更新 `operations`／`main`、寫 `/opt`／`/etc`／
`/var/lib`、啟停任何服務或連交易所。
