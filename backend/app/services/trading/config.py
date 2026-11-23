"""Strategy + risk configuration (owner's choices: trend-following swing, moderate risk, hourly)."""

from dataclasses import dataclass, field

UNIVERSE: tuple[str, ...] = (
    # Broad + sector ETFs, gold, long bonds
    "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU",
    "XLB", "XLC", "SMH", "GLD", "TLT",
    # Liquid large caps
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "TSLA", "JPM", "LLY", "V",
    "COST", "WMT", "XOM", "UNH", "NFLX", "AMD", "ORCL", "HD",
)  # fmt: skip


@dataclass(frozen=True)
class BotConfig:
    universe: tuple[str, ...] = UNIVERSE
    benchmark: str = "SPY"
    # Risk (moderate)
    max_position_pct: float = 10.0  # of equity, at entry
    max_positions: int = 10
    stop_loss_pct: float = 8.0  # protective GTC stop below average entry price
    drawdown_pause_pct: float = 10.0  # from peak equity: no new buys while at/after this
    max_new_buys_per_day: int = 3
    cooldown_days: int = 7  # calendar days before re-buying a symbol after a sell
    allow_short: bool = False  # never changed by the planner
    allow_margin: bool = False  # buys are limited by settled cash, not buying power
    # Signals
    fast: int = 50
    slow: int = 200
    slope_lookback: int = 10  # SMA50 must be higher than it was this many sessions ago
    rs_window: int = 126  # ~6 months, relative to the benchmark
    max_below_high_pct: float = 25.0  # skip names more than this far below their high
    trend_exit_hour_et: int = 15  # trend-break exits only from 15:00 ET (end-of-day rule)
    order_prefix: str = "atlas"
    extra: dict = field(default_factory=dict)


DEFAULT = BotConfig()
