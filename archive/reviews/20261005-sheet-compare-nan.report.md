# Perplexity 審閱歸檔 — 帳本對 Google 表的數值比較，NaN／無限大不再當成一樣（PR #129，v0.27.4）

- **Repo**：bcup02/trade-alerts
- **PR**：#129，head `20e91067ba85455f3cf686771d959b6a07fe573b`，base `f891b5978ea76d6d388e38e1a555653f8ab6f397`（main），squash 合併為 `e1e0c80`，tag `v0.27.4`
- **審閱者**：Perplexity — 一輪：首審 **PASS**
- **CI**：pytest = success（run `37305640787`；674 passed，起始 662）

## 做了什麼

`_value_mismatch` 的出場價、淨損益、毛損益三個比較由「差值 > 容忍度才算差異」改成肯定式 `not 差值 <= 容忍度`：Google 表欄位 `"nan"`、帳本值 NaN、±inf、兩邊都 NaN 一律列為 VALUE_MISMATCH。這是 #117 審閱者另案指出的缺口（進度頁 t10）。新增 12 個測試（拿掉修正有 7 個失敗）；版本 0.27.4。

## 審閱重點

- 優先序正確（not 低於 <=）；有限數的價格容忍度邊界不變（100.0 對 100.1 恰等於 0.1% 不列差異、100.1000000001 列差異）；雙方 ∞ 時差值為 NaN 現在正確列差異。
- 新測試不只斷言 DIVERGED，還斷言 VALUE_MISMATCH 與對應欄位（損益時 net／gross 兩欄）。

## 審閱者標明的界限

- PnL 浮點邊界：0.5 對 0.51 在二進位浮點下差可能略大於 0.01，會列差異；原本的 `>` 寫法對相同值也一樣，不是本 PR 引入。要精確十進位邊界需另案用 Decimal 或明確 epsilon。
- `to_number(True)` 仍是 1.0、價格 0 時 denom 仍為 1.0，是既有行為。
- 競賽有自己的 Google 對帳實作，只讀了檔頭，本次 PASS 不代表競賽也修了 NaN。
- PASS 不授權 consumer 改釘、部署或發 tag。

## 隔離聲明

審閱者唯讀；未接觸 /opt、/etc、/var/lib、systemd、交易所、Google 或實機帳本。合併不代表任何主機部署。
