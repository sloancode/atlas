"""Strategy + risk configuration.

Owner's choices (2026-11-27): trade often, long AND short, any liquid US stock, news + price
patterns, bigger positions, sole goal profit. PAPER ONLY: the $100k Alpaca paper account is for
training and testing this strategy. Limits below were approved by the owner ("as proposed").
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class BotConfig:
    # --- Risk (owner-approved, enforced in code) ---
    risk_per_trade_pct: float = 1.0  # equity lost if a new trade hits its stop (before gaps)
    max_position_pct: float = 25.0  # of equity, per position at entry
    max_gross_pct: float = 150.0  # longs + shorts market value, as % of equity (margin)
    max_positions: int = 12
    max_new_trades_per_day: int = 20
    daily_loss_cap_pct: float = 3.0  # down this much vs yesterday's close: no new trades today
    drawdown_pause_pct: float = 15.0  # this far below peak equity: no new trades until reviewed
    min_equity_for_day_trading: float = 26_000.0  # US pattern-day-trader rule needs >= $25k
    allow_short: bool = True
    # --- Universe filters (any US stock that passes) ---
    min_price: float = 5.0
    # Alpaca's free data is the IEX feed, which sees ~2-3% of US volume: $1M/day on IEX is
    # roughly $35-50M/day consolidated. Daily bars and snapshots must both use feed=iex.
    min_avg_dollar_volume: float = 1_000_000.0
    # --- Signals ---
    min_news_score: int = 1  # |score| from the headline read, scale -2..+2
    news_pattern_points: int = 3  # of 5 price checks needed to confirm a news trade
    momentum_pattern_points: int = 5  # all 5 needed to trade on price alone (no news)
    gap_pct: float = 2.0  # move vs previous close that counts as a real move
    rel_volume: float = 1.5  # today's volume vs a normal day at this time of day
    breakout_days: int = 20
    # --- Orders and exits ---
    atr_days: int = 14
    stop_atr_mult: float = 0.5  # stop distance = 0.5 x daily ATR ...
    min_stop_pct: float = 1.5  # ... but at least 1.5% ...
    max_stop_pct: float = 6.0  # ... and at most 6% from the entry price
    target_r: float = 2.0  # take-profit at 2x the stop distance
    fallback_stop_pct: float = 5.0  # stop for a position that somehow has none
    max_hold_days: int = 3  # close a position after this many days unless it is up
    stale_min_gain_pct: float = 1.0  # "up" means at least this unrealized gain
    cooldown_minutes: int = 30  # no new entry in a symbol traded this recently
    first_entry_et: str = "09:45"
    last_entry_et: str = "15:30"  # no new entries in the last half hour
    order_prefix: str = "atlasn"
    # --- Learning (learning.py): size each signal kind by its last finished trades ---
    learn_window: int = 20  # most recent finished trades per kind that count
    learn_min_trades: int = 5  # below this, a kind trades at full size while it learns
    # --- Crypto, around the clock (owner asked to trade all hours, 2026-11-27) ---
    # Alpaca crypto is long-only and cash-only (no shorting, no margin); fees ~0.15-0.25%/side.
    crypto_pairs: tuple[str, ...] = (
        "BTC/USD",
        "ETH/USD",
        "SOL/USD",
        "XRP/USD",
        "DOGE/USD",
        "AVAX/USD",
        "LINK/USD",
        "LTC/USD",
        "BCH/USD",
        "DOT/USD",
        "UNI/USD",
        "AAVE/USD",
    )
    crypto_max_position_pct: float = 10.0  # of equity, per coin
    crypto_max_total_pct: float = 30.0  # of equity, all coins together
    crypto_ema_fast: int = 20  # hourly bars
    crypto_ema_slow: int = 50
    crypto_breakout_bars: int = 24  # new 24-hour high
    crypto_max_24h_gain_pct: float = 20.0  # don't chase anything up more than this in 24h
    crypto_stop_atr_mult: float = 2.0  # stop distance = 2 x hourly ATR ...
    crypto_min_stop_pct: float = 2.0  # ... at least 2% ...
    crypto_max_stop_pct: float = 8.0  # ... at most 8%
    crypto_cooldown_minutes: int = 60
    crypto_min_order_usd: float = 500.0  # skip crumbs left under the caps


DEFAULT = BotConfig()
