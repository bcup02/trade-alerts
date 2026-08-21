from dataclasses import dataclass, field

from trade_alerts.investor import InvestorQueryController, render_closed_trades, render_portfolio_snapshot


@dataclass
class FakeProvider:
    project_id: str = "demo-btc"
    project_name: str = "Demo BTC 策略"
    portfolio_command: str = "查看 Demo 投資摘要"
    trade_command: str = "查看 Demo 交易紀錄"
    action_commands: dict[str, str] = field(default_factory=lambda: {
        "status": "查看 Demo 系統狀態",
        "pause": "暫停 Demo 策略",
        "resume": "恢復 Demo 模擬運轉",
    })

    def portfolio_snapshot(self):
        return {
            "schema_version": "1.0",
            "project_id": self.project_id,
            "project_name": self.project_name,
            "execution_mode": "DRY_RUN",
            "status": "OPEN",
            "as_of": "2026-08-19T08:00:00Z",
            "equity": 201.5,
            "realized_pnl_total": 1.5,
            "open_position": {
                "side": "long", "entry_price": 65000, "mark_price": 66000,
                "unrealized_pnl": 0.8, "opened_at": "2026-08-19T00:00:00Z",
            },
            "protective_orders": [{"order_type": "strategy_stop", "stop_price": 63250, "status": "active"}],
            "performance": {
                key: {"total_pnl": 1.5, "trade_count": 1, "win_count": 1, "loss_count": 0}
                for key in ("7d", "30d", "ytd", "1y")
            },
        }

    def closed_trades(self):
        return [{
            "symbol": "BTCUSDT", "side": "long", "opened_at": "2026-08-18T00:00:00Z",
            "closed_at": "2026-08-19T08:00:00Z", "entry_price": 65000, "exit_price": 66000,
            "contracts": 10, "realized_pnl": 1.0, "fees": 0.03, "close_reason": "test_exit",
        }]


def test_portfolio_render_uses_taipei_time_and_v1_fields():
    text = render_portfolio_snapshot(FakeProvider().portfolio_snapshot())
    assert "2026-08-19 16:00" in text
    assert "策略停損規則｜觸發價：63250｜狀態：啟用中" in text
    assert "7 天：1.5000 USDT" in text


def test_controller_accepts_only_whitelisted_query_commands():
    controller = InvestorQueryController([FakeProvider()])
    assert controller.handle("systemctl stop bot") is None
    portfolio_menu = controller.handle("查看投資摘要").text
    assert "投資摘要查詢" in portfolio_menu
    assert "Demo BTC 策略" in portfolio_menu
    assert "Demo BTC 策略" in controller.handle("查看告警狀態").text
    assert "交易紀錄查詢" in controller.handle("查看交易紀錄").text
    summary = controller.handle("查看 Demo 投資摘要")
    assert "帳戶總權益：201.5000 USDT" in summary.text
    assert "策略運行狀態：" in summary.text
    response = controller.handle("查看 Demo 交易紀錄")
    assert "2026-08-19 16:00" in response.text
    assert "手續費：0.0300 USDT" in response.text
    assert "已實現損益：1.0000 USDT" in response.text


def test_single_project_summary_still_requires_project_selection():
    text = InvestorQueryController([FakeProvider()]).handle("投資摘要").text
    assert "投資摘要查詢" in text
    assert "Demo BTC 策略" in text


def test_multi_project_summary_returns_project_selection():
    other = FakeProvider(
        project_id="other", project_name="Other 策略", portfolio_command="查看 Other 投資摘要", trade_command="查看 Other 交易紀錄",
        action_commands={"status": "查看 Other 系統狀態", "pause": "暫停 Other 策略", "resume": "恢復 Other 模擬運轉"},
    )
    text = InvestorQueryController([FakeProvider(), other]).handle("查看投資摘要").text
    assert "Demo BTC 策略" in text
    assert "Other 策略" in text


def test_project_options_expose_provider_commands_for_both_query_menus():
    controller = InvestorQueryController([FakeProvider()])
    assert controller.project_options("查看投資摘要") == [("Demo BTC 策略", "查看 Demo 投資摘要")]
    assert controller.project_options("查看交易紀錄") == [("Demo BTC 策略", "查看 Demo 交易紀錄")]
    assert controller.project_options("未定義命令") == []


def test_provider_queries_resolve_their_parent_menu():
    controller = InvestorQueryController([FakeProvider()])
    assert controller.previous_menu_command("查看 Demo 投資摘要") == "查看投資摘要"
    assert controller.previous_menu_command("查看 Demo 交易紀錄") == "查看交易紀錄"
    assert controller.previous_menu_command("查看投資摘要") is None


def test_project_action_options_and_resolution_are_fixed_and_whitelisted():
    controller = InvestorQueryController([FakeProvider()])
    assert controller.project_action_options("status") == [("Demo BTC 策略", "查看 Demo 系統狀態")]
    assert controller.project_action_options("pause") == [("Demo BTC 策略", "暫停 Demo 策略")]
    provider, action = controller.resolve_project_action("恢復 Demo 模擬運轉")
    assert provider.project_id == "demo-btc"
    assert action == "resume"
    assert controller.resolve_project_action("任意指令") is None


def test_portfolio_render_explains_exchange_trailing_stop_without_inventing_fixed_trigger():
    snapshot = FakeProvider().portfolio_snapshot()
    snapshot["execution_mode"] = "LIVE"
    snapshot["protective_orders"] = [{
        "order_type": "trailing_stop",
        "status": "active",
        "callback_pct": 0.05,
        "reference_stop_price": 63250,
        "description": "MEXC 原生追蹤停損委託；交易所依回撤百分比持續計算。",
    }]
    snapshot["data_quality"] = {"complete": False, "stale": False, "missing_fields": ["equity", "mark_price"]}

    text = render_portfolio_snapshot(snapshot)

    assert "交易所追蹤停損｜回撤設定：5.00%｜狀態：啟用中" in text
    assert "策略參考停損點：63250（非固定交易所觸發價）" in text
    assert "MEXC 原生追蹤停損委託" in text
    assert "資料限制：" not in text
    assert "資料說明：" not in text


def test_portfolio_render_hides_internal_data_quality_summary():
    snapshot = FakeProvider().portfolio_snapshot()
    snapshot["data_quality"] = {
        "complete": False,
        "stale": False,
        "missing_fields": ["equity"],
        "summary": "本摘要只讀取策略快照，不連線交易所即時帳戶資料。",
    }

    text = render_portfolio_snapshot(snapshot)

    assert "資料說明：" not in text
    assert "資料限制：" not in text


def test_portfolio_render_translates_internal_status_and_data_field_codes():
    snapshot = FakeProvider().portfolio_snapshot()
    snapshot["status"] = "SAFE_HALT"
    snapshot["data_quality"] = {"complete": False, "stale": False, "missing_fields": ["equity", "mark_price"]}

    text = render_portfolio_snapshot(snapshot)

    assert "策略運行狀態：安全暫停，等待人工處理" in text
    assert "SAFE_HALT" not in text
    assert "資料限制：" not in text
    assert "資料說明：" not in text


def test_closed_trade_render_uses_mobile_cards_and_maintenance_label():
    text = render_closed_trades([
        {
            "symbol": "XRP_USDT", "side": "long", "opened_at": "2026-08-19T11:00:00Z",
            "closed_at": "2026-08-19T12:00:00Z", "entry_price": 1.0049, "exit_price": 1.0048,
            "contracts": 5, "realized_pnl": -0.0085, "fees": 0.0080,
            "close_reason": "受限實盤維護驗證（非策略訊號）", "record_type": "maintenance_verification",
        }
    ], project_name="MEXC 4H Momentum Trailing Stop")

    assert "台北時間（UTC+8）\n最近 5 筆交易紀錄如下：" in text
    assert "#1 XRP_USDT｜看漲" in text
    assert text.count("UTC+8") == 1
    assert "買進：2026-08-19 19:00" in text
    assert "平倉：2026-08-19 20:00" in text
    assert "部位：5 張" in text
    assert "進場：1.0049" in text
    assert "出場：1.0048" in text
    assert "手續費：0.0080 USDT" in text
    assert "已實現損益：-0.0085 USDT" in text
    assert "結束原因：驗證交易（非策略）" in text


def test_closed_trade_render_includes_optional_execution_quality():
    text = render_closed_trades([
        {
            "symbol": "BOME_USDT", "side": "long", "opened_at": "2026-08-20T09:59:57Z",
            "closed_at": "2026-08-20T10:21:24Z", "entry_price": 0.001191,
            "exit_price": 0.0011818, "contracts": 5, "realized_pnl": -0.0554912,
            "fees": 0.0094912, "return_on_margin": -0.027955264483627205,
            "close_reason": "追蹤停損出場",
            "execution_quality": {
                "status": "NORMAL_RECONCILED",
                "investor_label": "正常交易",
                "summary": "交易所成交已明確對應原生追蹤停損；帳本已補齊完整資料。",
            },
        }
    ], project_name="MEXC 4H Momentum Trailing Stop")

    assert "保證金報酬率：-2.80%" in text
    assert "結束原因：追蹤停損出場" in text
    assert "交易性質：正常交易" in text
    assert "備註：" not in text


def test_closed_trade_render_shows_note_only_for_abnormal_trade():
    text = render_closed_trades([
        {
            "symbol": "TEST_USDT", "side": "long", "opened_at": "2026-08-20T09:00:00Z",
            "closed_at": "2026-08-20T10:00:00Z", "entry_price": 1.0, "exit_price": 0.9,
            "contracts": 1, "realized_pnl": -1.0, "return_on_margin": -0.1, "fees": 0.01,
            "close_reason": "平倉委託失敗後補核",
            "execution_quality": {
                "status": "ABNORMAL", "investor_label": "異常交易",
                "summary": "帳本記錄此筆交易的保護或平倉委託失敗，需要檢視交易所結果與程式紀錄。",
            },
        }
    ], project_name="Demo")

    assert "交易性質：異常交易" in text
    assert "備註：帳本記錄此筆交易的保護或平倉委託失敗" in text


def test_portfolio_render_uses_runtime_status_and_hides_unavailable_equity():
    snapshot = FakeProvider().portfolio_snapshot()
    snapshot.update({
        "runtime_status": "HEALTHY",
        "position_status": "FLAT",
        "equity": None,
        "open_position": None,
        "data_quality": {"complete": False, "stale": False, "missing_fields": ["equity"]},
    })

    text = render_portfolio_snapshot(snapshot)

    assert "策略運行狀態：系統正常" in text
    assert "目前部位：沒有持倉。" in text
    assert "帳戶總權益：" not in text
    assert "資料限制：" not in text


def test_portfolio_debug_mode_appends_nonsecret_diagnostics_only_when_enabled():
    snapshot = FakeProvider().portfolio_snapshot()
    snapshot.update({
        "runtime_status": "HEALTHY",
        "last_update_at": "2026-08-19T08:00:00Z",
        "data_quality": {
            "complete": False, "stale": False, "missing_fields": ["equity"],
            "summary": "本摘要只讀取已保存的快照。",
        },
    })

    normal = render_portfolio_snapshot(snapshot)
    debug = render_portfolio_snapshot(snapshot, debug=True)

    assert "------Debug模式------" not in normal
    assert "資料限制：" not in normal
    assert "------Debug模式------" in debug
    assert "內部運行代碼：HEALTHY" in debug
    assert "資料限制：目前未建立 帳戶權益。" in debug
    assert "資料說明：本摘要只讀取已保存的快照。" in debug


def test_trade_debug_mode_appends_sources_and_handles_empty_records():
    text = render_closed_trades([], project_name="Demo", debug=True)

    assert "目前尚無可列示" in text
    assert "------Debug模式------" in text
    assert "讀取已平倉紀錄：0 筆" in text
