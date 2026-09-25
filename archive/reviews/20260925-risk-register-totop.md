# Perplexity 審閱歸檔 — guides: back-to-top button on the risk register too

- **Repo**：bcup02/trade-alerts
- **PR**：#75，最終 head `f8f0b2d844d285558d1a8c3cee35193e0a34529e`，base `main` @ `b583d6e`，squash 合併為 `0f48568`
- **審閱者**：Perplexity — 首審 **`BLOCK`**（head `c3a3145`）→ 複審 **`PASS`**
- **CI**：pytest = success（run `36092222392`、`36092588994`；381 passed）
- **部署**：不需要；合併後重發兩張登記冊頁。

## 做了什麼

使用者要求風險登記冊也要有一致性登記冊的「回到最上方」浮動按鈕：scripts/render_guides.py 新增 _RISK_CSS、按鈕與 JS（篩選列捲出畫面後出現，點擊回頂並聚焦 h1）。

## 審閱

- 首審 BLOCK：按鈕只靠 opacity:0＋pointer-events:none 隱藏，仍可被 Tab 聚焦（隱形 Tab 停靠點）；一致性登記冊原本的按鈕也有同樣問題。
- 修正 f8f0b2d：隱藏時 visibility:hidden（淡出後才套用，顯示時立即解除），兩頁一併修；Chromium 實測頁首不可聚焦、捲動後可聚焦、Enter 回頂並聚焦 h1。機隊工程進度頁的同款按鈕也同步修正（該頁不在本 repo）。
- 複審 PASS。

## 隔離聲明

純顯示變更，未碰正式機、交易所、Google 或帳本。完整差異見同名 `.patch`。
