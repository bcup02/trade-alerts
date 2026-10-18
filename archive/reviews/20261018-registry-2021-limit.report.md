# PR #232 審閱歸檔：登記冊加密停損限制句改成已實測的 Binance -2021／-4130 說法（f-54）

- PR：bcup02/trade-alerts #232
- head 2655d7d64a82b2a5797acbbe6ec9fb42a7a3d0a1；base 8a6d799ffcf7ca6df62ef58339eb6f2e100bf545
- squash：d41d3ac46142cd53c198738fc061346e103d933a
- 審閱：ChatGPT 1 輪，PASS（審閱PR#232結論：PASS）
- CI：run 39139751756，原始日誌 1107 passed、0 skipped（PR 描述與送審文字寫的本機 1093 passed、1 skipped 與 CI 不同，以 CI 為準；審閱者列為非阻擋紀錄落差）
- 重點：MYC.PROTECTION_REPLACE_FAILED 與 MYC.PROTECTION_PLACEMENT_REJECTED 兩格限制句從「依文件推論」改成 2026-10-18 開發機測試網實測：整倉停損單觸發價已越過現價回 -2021（標記價與最後價都一樣）、部位仍沒停損；同方向第二張整倉停損回 -4130；移動停損先取消再掛，越界會留下沒停損的部位（f-54）。格子狀態全部不變。
- 審閱者更正：updated_at 在 base 已是 2026-10-18，本 PR 實際沒有變更它。
- 隔離聲明：審閱者只用 GitHub 唯讀資料與 CI 日誌，未接觸 /opt /etc /var/lib、systemd、交易所、Google、實機帳本。
