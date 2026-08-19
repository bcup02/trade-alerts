"""Read-only LINE/Telegram investor-query primitives for contract v1.

This module deliberately knows nothing about tokens, webhooks, subprocesses, or
trading actions. A host application supplies a whitelisted provider that returns
v1 portfolio snapshots and closed-trade records. The module only renders text.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
PORTFOLIO_COMMANDS = frozenset({"查看投資摘要", "投資摘要"})
TRADE_LIST_COMMANDS = frozenset({"查看交易紀錄"})


class InvestorProvider(Protocol):
    """A read-only source for one project conforming to the v1 contract."""

    project_id: str
    project_name: str
    portfolio_command: str
    trade_command: str

    def portfolio_snapshot(self) -> dict[str, Any]:
        ...

    def closed_trades(self) -> list[dict[str, Any]]:
        ...


@dataclass(frozen=True)
class QueryResult:
    text: str
    handled: bool = True


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=TAIPEI).astimezone(TAIPEI) if parsed.tzinfo is None else parsed.astimezone(TAIPEI)
    except (TypeError, ValueError):
        return None


def taipei_time(value: Any) -> str:
    parsed = _parse_time(value)
    return parsed.strftime("%Y-%m-%d %H:%M") if parsed else "時間未提供"


def _money(value: Any) -> str:
    return "資料未建立" if value is None else f"{float(value):.4f} USDT"


def _mode_label(mode: Any) -> str:
    return {
        "DRY_RUN": "模擬演練（不使用真實資金、不會送出交易所訂單）",
        "PAPER": "模擬盤",
        "LIVE": "實盤",
    }.get(str(mode), str(mode or "未提供"))


def _side_label(side: Any) -> str:
    return {"long": "看漲／買進方向", "short": "看跌／放空方向"}.get(str(side), "未提供")


def render_portfolio_snapshot(snapshot: dict[str, Any]) -> str:
    """Render a v1 portfolio snapshot into one channel-neutral text response."""
    lines = [
        "投資摘要",
        "",
        f"專案：{snapshot.get('project_name', snapshot.get('project_id', '未提供'))}",
        f"執行方式：{_mode_label(snapshot.get('execution_mode'))}",
        f"資料時間：{taipei_time(snapshot.get('as_of'))}（台北時間）",
        f"策略狀態：{snapshot.get('status', '未提供')}",
        f"策略權益：{_money(snapshot.get('equity'))}",
        f"累計已實現損益：{_money(snapshot.get('realized_pnl_total'))}",
    ]
    position = snapshot.get("open_position")
    if position:
        lines.extend([
            "目前部位：有持倉。",
            f"方向：{_side_label(position.get('side'))}",
            f"進場價：{position.get('entry_price', '資料未建立')}",
            f"最新標記價：{position.get('mark_price', '資料未建立')}",
            f"未實現損益：{_money(position.get('unrealized_pnl'))}",
            f"開倉時間：{taipei_time(position.get('opened_at'))}（台北時間）",
        ])
    else:
        lines.append("目前部位：沒有持倉。")

    protective_orders = snapshot.get("protective_orders") or []
    if protective_orders:
        stop = protective_orders[0]
        order_type = {"exchange_stop": "交易所停損單", "strategy_stop": "策略停損規則", "trailing_stop": "追蹤停損"}.get(stop.get("order_type"), "保護機制")
        lines.append(f"保護機制：{order_type}｜觸發價：{stop.get('stop_price', '資料未建立')}｜狀態：{stop.get('status', '未提供')}")
    else:
        lines.append("保護機制：目前沒有啟用中的保護單或策略停損。")

    performance = snapshot.get("performance") or {}
    lines.extend(["", "績效（USDT）"])
    for label, key in [("7 天", "7d"), ("30 天", "30d"), ("今年", "ytd"), ("1 年", "1y")]:
        window = performance.get(key, {})
        total = window.get("total_pnl")
        if total is None:
            lines.append(f"{label}：資料不足。")
        else:
            lines.append(f"{label}：{_money(total)}｜已平倉 {window.get('trade_count', 0)} 筆（勝 {window.get('win_count', 0)}／負 {window.get('loss_count', 0)}）")
    return "\n".join(lines)


def render_closed_trades(records: list[dict[str, Any]], *, project_name: str) -> str:
    """Render at most ten v1 closed-trade records in Taiwan local time."""
    lines = [f"{project_name}｜交易紀錄", "以下為策略／模擬交易紀錄，並非保證成交或投資建議。", ""]
    if not records:
        lines.append("目前尚無可列示的已平倉交易紀錄。")
        return "\n".join(lines)
    for trade in records[-10:]:
        lines.extend([
            f"{taipei_time(trade.get('closed_at'))}｜{_side_label(trade.get('side'))}｜{trade.get('symbol', '未提供')}",
            f"進場 {trade.get('entry_price', '資料未建立')}｜平倉 {trade.get('exit_price', '資料未建立')}｜{trade.get('contracts', '資料未建立')} 張",
            f"已實現損益：{_money(trade.get('realized_pnl'))}｜費用：{_money(trade.get('fees'))}｜原因：{trade.get('close_reason', '未提供')}",
        ])
    return "\n".join(lines)


class InvestorQueryController:
    """Whitelist-only router for two investor query commands and project choices."""

    def __init__(self, providers: list[InvestorProvider]):
        if not providers:
            raise ValueError("at least one investor provider is required")
        self._providers = {provider.project_id: provider for provider in providers}
        self._portfolio_commands = {provider.portfolio_command: provider for provider in providers}
        self._trade_commands = {provider.trade_command: provider for provider in providers}

    def handle(self, command: str) -> QueryResult | None:
        command = command.strip()
        if command in PORTFOLIO_COMMANDS:
            return self._portfolio_response()
        if command in TRADE_LIST_COMMANDS:
            return self._trade_menu_response()
        provider = self._portfolio_commands.get(command)
        if provider:
            return QueryResult(render_portfolio_snapshot(provider.portfolio_snapshot()))
        provider = self._trade_commands.get(command)
        if provider:
            return QueryResult(render_closed_trades(provider.closed_trades(), project_name=provider.project_name))
        return None

    def _portfolio_response(self) -> QueryResult:
        providers = list(self._providers.values())
        if len(providers) == 1:
            return QueryResult(render_portfolio_snapshot(providers[0].portfolio_snapshot()))
        lines = ["投資摘要查詢", "", "請選擇專案："]
        lines.extend(f"• {provider.project_name}：輸入「{provider.portfolio_command}」" for provider in providers)
        return QueryResult("\n".join(lines))

    def _trade_menu_response(self) -> QueryResult:
        lines = ["交易紀錄查詢", "", "請選擇專案："]
        lines.extend(f"• {provider.project_name}：輸入「{provider.trade_command}」" for provider in self._providers.values())
        return QueryResult("\n".join(lines))
