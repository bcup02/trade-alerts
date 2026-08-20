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
PORTFOLIO_COMMANDS = frozenset({"查看投資摘要", "投資摘要", "查看告警狀態", "告警狀態"})
TRADE_LIST_COMMANDS = frozenset({"查看交易紀錄"})


class InvestorProvider(Protocol):
    """A read-only source for one project conforming to the v1 contract."""

    project_id: str
    project_name: str
    portfolio_command: str
    trade_command: str
    action_commands: dict[str, str]

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
    return {"long": "看漲／買進", "short": "看跌／放空"}.get(str(side), "方向未提供")


def _status_label(status: Any) -> str:
    return {
        "HEALTHY": "系統正常",
        "FLAT": "目前無持倉",
        "OPEN": "目前持有部位",
        "SAFE_HALT": "安全暫停，等待人工處理",
        "STALE": "資料可能過期",
        "ERROR": "系統發生錯誤，請檢查",
    }.get(str(status), "狀態未提供")


def _protection_status_label(status: Any) -> str:
    return {
        "active": "啟用中",
        "triggered": "已觸發",
        "cancelled": "已取消",
        "missing": "未確認／未建立",
        "unknown": "狀態未確認",
    }.get(str(status), "狀態未提供")


def _field_label(field: Any) -> str:
    return {
        "equity": "帳戶權益",
        "mark_price": "最新標記價",
        "unrealized_pnl": "未實現損益",
        "last_update_at": "最近更新時間",
    }.get(str(field), str(field))


def _record_type_label(record_type: Any) -> str:
    return {
        "strategy": "策略交易",
        "maintenance_verification": "驗證交易（非策略）",
    }.get(str(record_type), "已平倉紀錄")


def _trade_direction_label(side: Any) -> str:
    return {"long": "看漲", "short": "看跌"}.get(str(side), "方向未提供")


def _entry_label(side: Any) -> str:
    return {"long": "買進", "short": "放空"}.get(str(side), "開倉")


def render_portfolio_snapshot(snapshot: dict[str, Any]) -> str:
    """Render a v1 portfolio snapshot into one channel-neutral text response."""
    lines = [
        "投資摘要",
        "",
        f"專案：{snapshot.get('project_name', snapshot.get('project_id', '未提供'))}",
        f"執行方式：{_mode_label(snapshot.get('execution_mode'))}",
        f"資料時間：{taipei_time(snapshot.get('as_of'))}（台北時間）",
        f"策略狀態：{_status_label(snapshot.get('status'))}",
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
        order_type = {"exchange_stop": "交易所停損單", "strategy_stop": "策略停損規則", "trailing_stop": "交易所追蹤停損"}.get(stop.get("order_type"), "保護機制")
        if stop.get("order_type") == "trailing_stop" and stop.get("callback_pct") is not None:
            try:
                callback = f"｜回撤設定：{float(stop['callback_pct']) * 100:.2f}%"
            except (TypeError, ValueError):
                callback = ""
            lines.append(f"保護機制：{order_type}{callback}｜狀態：{_protection_status_label(stop.get('status'))}")
            if stop.get("reference_stop_price") is not None:
                lines.append(f"策略參考停損點：{stop.get('reference_stop_price')}（非固定交易所觸發價）")
        else:
            lines.append(f"保護機制：{order_type}｜觸發價：{stop.get('stop_price', '資料未建立')}｜狀態：{_protection_status_label(stop.get('status'))}")
        if stop.get("description"):
            lines.append(f"保護說明：{stop['description']}")
    else:
        lines.append("保護機制：目前沒有啟用中的保護單或策略停損。")

    data_quality = snapshot.get("data_quality") or {}
    if not data_quality.get("complete", True):
        missing = data_quality.get("missing_fields") or []
        if missing:
            lines.append(f"資料限制：目前未建立 {', '.join(_field_label(field) for field in missing)}。")
        summary = data_quality.get("summary")
        if isinstance(summary, str) and summary.strip():
            lines.append(f"資料說明：{summary.strip()}")
        if data_quality.get("stale"):
            lines.append("資料提醒：最近快照可能已過期，請等待下一次策略工作流程完成後再查詢。")

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


def _contracts(value: Any) -> str:
    if value is None:
        return "資料未建立"
    try:
        return f"{float(value):g} 張"
    except (TypeError, ValueError):
        return f"{value} 張"


def render_closed_trades(records: list[dict[str, Any]], *, project_name: str) -> str:
    """Render the five most recent closed trades in the investor-approved layout."""
    lines = [project_name, "", "最近 5 筆交易紀錄如下："]
    if not records:
        lines.extend(["", "目前尚無可列示的已平倉交易紀錄。"])
        return "\n".join(lines)

    for index, trade in enumerate(reversed(records[-5:]), start=1):
        side = trade.get("side")
        record_type = trade.get("record_type")
        reason = _record_type_label(record_type) if record_type == "maintenance_verification" else trade.get("close_reason", "原因未提供")
        lines.extend([
            "",
            f"#{index} {trade.get('symbol', '標的未提供')}｜{_trade_direction_label(side)}（UTC+8）",
            f"{_entry_label(side)}：{taipei_time(trade.get('opened_at'))}",
            f"平倉：{taipei_time(trade.get('closed_at'))}",
            f"部位：{_contracts(trade.get('contracts', trade.get('quantity')))}",
            f"進場：{trade.get('entry_price', '資料未建立')}",
            f"出場：{trade.get('exit_price', '資料未建立')}",
            f"手續費：{_money(trade.get('fees'))}",
            f"已實現損益：{_money(trade.get('realized_pnl'))}",
            f"結束原因：{reason}",
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
        self._action_commands: dict[str, tuple[InvestorProvider, str]] = {}
        for provider in providers:
            for action, command in provider.action_commands.items():
                if action not in {"status", "pause", "resume"}:
                    raise ValueError(f"unsupported project action: {action}")
                if command in self._action_commands:
                    raise ValueError(f"duplicate project action command: {command}")
                self._action_commands[command] = (provider, action)

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

    def project_action_options(self, action: str) -> list[tuple[str, str]]:
        """Return fixed provider-specific commands for one approved action type."""
        return [
            (provider.project_name, command)
            for command, (provider, provider_action) in self._action_commands.items()
            if provider_action == action
        ]

    def resolve_project_action(self, command: str) -> tuple[InvestorProvider, str] | None:
        """Resolve a provider-specific action command without executing it."""
        return self._action_commands.get(command)

    def previous_menu_command(self, command: str) -> str | None:
        """Return the parent menu command for a provider-specific query."""
        if command in self._portfolio_commands:
            return "查看投資摘要"
        if command in self._trade_commands:
            return "查看交易紀錄"
        return None

    def project_options(self, command: str) -> list[tuple[str, str]]:
        """Return fixed (label, command) pairs for a project-selection command.

        Channel adapters use this method to build clickable choices from the same
        whitelist that the text controller uses. Unknown commands expose no options.
        """
        if command in PORTFOLIO_COMMANDS:
            return [(provider.project_name, provider.portfolio_command) for provider in self._providers.values()]
        if command in TRADE_LIST_COMMANDS:
            return [(provider.project_name, provider.trade_command) for provider in self._providers.values()]
        return []

    def _portfolio_response(self) -> QueryResult:
        lines = ["投資摘要查詢", "", "請選擇專案："]
        lines.extend(f"• {label}" for label, _provider_command in self.project_options("查看投資摘要"))
        return QueryResult("\n".join(lines))

    def _trade_menu_response(self) -> QueryResult:
        lines = ["交易紀錄查詢", "", "請選擇專案："]
        lines.extend(f"• {label}" for label, _provider_command in self.project_options("查看交易紀錄"))
        return QueryResult("\n".join(lines))
