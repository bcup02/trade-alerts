# 發布與升級流程

`trade-alerts` 是所有自動化策略共用的基礎元件，因此採取保守的版本流程。任何渠道、事件格式或重試行為變更，都必須先更新測試與 README，再由專案維護者合併到 `main`。

## 版本規則

採用 Semantic Versioning：向後相容的新功能增加 minor version；修正錯誤增加 patch version；破壞公開 API 才增加 major version。策略專案應優先依賴已審核的 tag 或 commit，而不是永久追蹤未固定的 `main`。

## 升級步驟

先在 `trade-alerts` 執行完整測試，再建立版本 tag 並推送。接著在每個策略專案更新 `pyproject.toml` 的 Git tag 或 commit，重新安裝依賴並執行該策略的完整測試。通知渠道必須使用 mock 或測試帳號驗證，不可用真實交易事件直接測試。

## 目前初版

目前 repository 已建立 `0.1.0` 初版，公開 API 為 `AlertEvent`、`AlertDispatcher`、`RetryPolicy`、`LineMessagingChannel`、`TelegramChannel` 與 `dispatcher_from_env`。Seykota 專案已改為依賴此 repository；舊的 `seykota_bot.notifier` 只保留相容性轉接層。
