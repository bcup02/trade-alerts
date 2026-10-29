# PR #320 移除臨時檢查 dev-competition-drill（R033 P3 演練結束）

- PR：bcup02/trade-alerts #320；base a5778014b9e6c1a89b3a63ab80f753cd619103fb；squash 5b3c3be9fb3519bd9c8ccf02df329d9a763f73b8
- 審閱：ChatGPT 1 輪。head ecac9dc9d35445f7f5143af06a1b71b29d42f494 PASS（審閱PR#320結論：PASS）。CI run 40794279040，1570 passed。
- 重點：用 git apply -R 完整還原 #318（c565cec），+1／−71；CHECKS 其餘 19 項、ALLOWED_PATHS、共用輔助函式不變；run_checks() 本來就會清掉不在 CHECKS 的舊狀態，不需另寫清理。
- 教訓（來自部署當天）：臨時檢查依賴的資料來源（開發機競賽的對帳計時器）在演練結束後會停用，檢查會變成「資料太舊」連續出錯；臨時檢查要和資料來源的停用一起移除。開發機的競賽計時器基準狀態是全部停用（install_systemd.sh 的 START_SERVICE=0 閘門），演練後別留著每日計時器。
- 部署：開發機 /opt/observation-watch/observation_watch.py 單檔更新；進度頁 meta/watch 移除 phase-r033-p3。
- 隔離：審閱端未接觸主機、交易所、帳本。
