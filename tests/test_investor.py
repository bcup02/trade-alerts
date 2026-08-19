from dataclasses import dataclass

from trade_alerts.investor import InvestorQueryController, render_portfolio_snapshot


@dataclass
class FakeProvider:
    project_id: str = "demo-btc"
    project_name: str = "Demo BTC 策略"
    portfolio_command: str = "查看 Demo 投資摘要"
    trade_command: str = "查看 Demo 交易紀錄"

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
    assert "策略停損規則｜觸發價：63250｜狀態：active" in text
    assert "7 天：1.5000 USDT" in text


def test_controller_accepts_only_whitelisted_query_commands():
    controller = InvestorQueryController([FakeProvider()])
    assert controller.handle("systemctl stop bot") is None
    assert controller.handle("查看投資摘要").text.startswith("投資摘要")
    assert "交易紀錄查詢" in controller.handle("查看交易紀錄").text
    response = controller.handle("查看 Demo 交易紀錄")
    assert "2026-08-19 16:00" in response.text
    assert "已實現損益：1.0000 USDT" in response.text


def test_multi_project_summary_returns_project_selection():
    other = FakeProvider(project_id="other", project_name="Other 策略", portfolio_command="查看 Other 投資摘要", trade_command="查看 Other 交易紀錄")
    text = InvestorQueryController([FakeProvider(), other]).handle("查看投資摘要").text
    assert "查看 Demo 投資摘要" in text
    assert "查看 Other 投資摘要" in text
