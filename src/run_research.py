
from __future__ import annotations
import argparse, json, warnings, sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "outputs"

PRICE_FILE = "synthetic_intraday_prices_500tickers_v2.csv"
META_FILE = "ticker_metadata_500tickers_v2.csv"
CONST_FILE = "index_constituents_500tickers_v2.csv"
EVENT_FILE = "scheduled_events_calendar_500tickers_v2.csv"
FEE_FILE = "fee_schedule_500tickers_v2.csv"

CFG = {
    "bar_minutes": 15,
    "initial_capital": 10_000_000.0,
    "long_gross_target": 0.50,
    "short_gross_target": 0.50,
    "selection_quantile": 0.05,
    "exit_quantile": 0.20,
    "max_names_per_side": 10,
    "max_position_weight": 0.05,
    "max_gross_exposure": 1.00,
    "max_net_exposure": 0.10,
    "max_holding_minutes": 180,
    "min_completed_signals": 30,
    "daily_loss_limit": 0.01,
    "slippage_bps_one_way": 2.0,
    # Passive quote: earn the half-spread instead of paying it, and do not add
    # crossing slippage. New trades are limited to the tightest quote quantile.
    "provide_liquidity": True,
    "tight_quote_quantile": 0.20,
    "event_blackout_minutes": 15,
    "breaking_news_blackout_minutes": 30,
    "trend_threshold": 0.50,
    "high_vol_scale": 0.50,
    "bars_per_day": 26,
    "trading_days_per_year": 252,
    # Hard data-quality gate thresholds. Applied to the reconstructed path, not the raw levels.
    "max_median_abs_1m_return_pct": 2.0,
    "max_fraction_abs_1m_return_over_20pct": 0.01,
    # Raw one-minute levels are independent redraws. Research prices compound the
    # within-bar open-to-close return from each session's first open.
    "price_path_assumption": "compound_within_bar_open_to_close_returns",
}

PRICE_PATH_NOTE = (
    "Raw one-minute price levels are independent redraws: OHLC inside each bar is tight, "
    "but the level jumps between minutes. Source files in data/raw/ are not modified. "
    "Each ticker-session, including INDEX, is rebuilt by anchoring at the first open and "
    "compounding the within-bar open-to-close return. High, low, bid, ask and adj_close "
    "are scaled with the open so relative ranges and quoted spreads stay unchanged. "
    "The quality gate is applied to this reconstructed path and still blocks the backtest "
    "if that path is implausible. Thresholds are not relaxed."
)


class DataQualityError(RuntimeError):
    """Raised when critical input-data checks fail and the backtest is blocked."""


def enforce_data_quality_gate(quality):
    """Block backtesting when one-minute equity price continuity is implausible."""
    reasons = []
    median_pct = quality.get("equity_one_minute_median_absolute_return_pct")
    over_20_fraction = quality.get("equity_one_minute_fraction_absolute_return_over_20pct")

    if median_pct is None or not np.isfinite(median_pct):
        reasons.append("Median absolute one-minute equity return is missing or non-finite.")
    elif median_pct > CFG["max_median_abs_1m_return_pct"]:
        reasons.append(
            f"Median absolute one-minute equity return is {median_pct:.4f}% "
            f"(limit: {CFG['max_median_abs_1m_return_pct']:.4f}%)."
        )

    if over_20_fraction is None or not np.isfinite(over_20_fraction):
        reasons.append("Fraction of absolute one-minute equity returns above 20% is missing or non-finite.")
    elif over_20_fraction > CFG["max_fraction_abs_1m_return_over_20pct"]:
        reasons.append(
            f"{over_20_fraction:.2%} of absolute one-minute equity returns exceed 20% "
            f"(limit: {CFG['max_fraction_abs_1m_return_over_20pct']:.2%})."
        )

    quality["backtest_blocked"] = bool(reasons)
    quality["backtest_block_reasons"] = reasons
    quality["quality_gate_thresholds"] = {
        "max_median_abs_1m_return_pct": CFG["max_median_abs_1m_return_pct"],
        "max_fraction_abs_1m_return_over_20pct": CFG["max_fraction_abs_1m_return_over_20pct"],
    }

    if reasons:
        message = (
            "DATA-QUALITY GATE FAILED. Strategy signal generation and backtesting have been stopped.\n"
            + "\n".join(f"  - {reason}" for reason in reasons)
            + "\nInspect outputs/data_quality.json and outputs/data_quality.csv. "
              "Correct or replace the source price data, then rerun. Do not simply suppress this gate."
        )
        raise DataQualityError(message)
    return quality


def write_data_quality_report(quality):
    """Persist validation diagnostics even when the hard gate blocks the run."""
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "data_quality.json").write_text(
        json.dumps(quality, indent=2), encoding="utf-8"
    )
    pd.DataFrame([
        {"check": key,
         "value": json.dumps(value) if isinstance(value, (dict, list)) else value}
        for key, value in quality.items()
    ]).to_csv(OUT / "data_quality.csv", index=False)

def equity_return_stats(frame):
    """Close-to-close one-minute equity return diagnostics, excluding INDEX."""
    ordered = frame.sort_values(["ticker", "date", "minute"])
    prev_close = ordered.groupby(["ticker", "date"], sort=False)["close"].shift(1)
    returns = (ordered["close"] / prev_close - 1).replace([np.inf, -np.inf], np.nan)
    equity_returns = returns.loc[(ordered["ticker"] != "INDEX") & returns.notna()].dropna()
    absolute = equity_returns.abs()
    if absolute.empty:
        nan = float("nan")
        return {
            "equity_one_minute_median_absolute_return_pct": nan,
            "equity_one_minute_p95_absolute_return_pct": nan,
            "equity_one_minute_p99_absolute_return_pct": nan,
            "equity_one_minute_fraction_absolute_return_over_5pct": nan,
            "equity_one_minute_fraction_absolute_return_over_20pct": nan,
        }
    return {
        "equity_one_minute_median_absolute_return_pct": float(absolute.median() * 100),
        "equity_one_minute_p95_absolute_return_pct": float(absolute.quantile(0.95) * 100),
        "equity_one_minute_p99_absolute_return_pct": float(absolute.quantile(0.99) * 100),
        "equity_one_minute_fraction_absolute_return_over_5pct": float((absolute > 0.05).mean()),
        "equity_one_minute_fraction_absolute_return_over_20pct": float((absolute > 0.20).mean()),
    }


def continuity_warning(stats):
    median_pct = stats["equity_one_minute_median_absolute_return_pct"]
    over_20 = stats["equity_one_minute_fraction_absolute_return_over_20pct"]
    return bool(
        (not np.isfinite(median_pct)) or median_pct > CFG["max_median_abs_1m_return_pct"]
        or (not np.isfinite(over_20)) or over_20 > CFG["max_fraction_abs_1m_return_over_20pct"]
    )


def reconstruct_continuous_session_paths(prices):
    """Stitch each session into a continuous path using within-bar returns.

    The printed close-to-close move is not used. Bar t is scaled so its open equals
    the reconstructed close of bar t-1, and its own open-to-close return is kept.
    The first bar of each ticker-session keeps its raw prices.
    """
    x = prices.sort_values(["ticker", "date", "minute", "timestamp"]).copy()
    x["minute"] = pd.to_numeric(x["minute"], errors="coerce")
    valid = x["open"].gt(0) & x["close"].gt(0)
    ratio = (x["close"] / x["open"]).where(valid, 1.0)
    cum = ratio.groupby([x["ticker"], x["date"]], sort=False).cumprod()
    prev_cum = cum / ratio
    first_open = x.groupby(["ticker", "date"], sort=False)["open"].transform("first")
    recon_open = first_open * prev_cum
    scale = (recon_open / x["open"]).where(x["open"].gt(0), 1.0)
    scale = scale.replace([np.inf, -np.inf], np.nan).fillna(1.0)
    for column in ("open", "high", "low", "close", "adj_close", "bid", "ask"):
        if column in x.columns:
            x[column] = x[column] * scale
    return x.reset_index(drop=True)


def load_inputs():
    prices = pd.read_csv(RAW / PRICE_FILE)
    metadata = pd.read_csv(RAW / META_FILE)
    constituents = pd.read_csv(RAW / CONST_FILE)
    events = pd.read_csv(RAW / EVENT_FILE)
    fees = pd.read_csv(RAW / FEE_FILE)
    return prices, metadata, constituents, events, fees

def validate_and_clean(prices, metadata, constituents, events, fees):
    p = prices.copy()
    p["timestamp"] = pd.to_datetime(p["timestamp"], errors="coerce")
    p["date"] = p["timestamp"].dt.date.astype(str)
    numeric = ["open","high","low","close","adj_close","bid","ask","volume"]
    for c in numeric:
        p[c] = pd.to_numeric(p[c], errors="coerce")
    # Continuity diagnostics on raw consecutive closes, before cleaning or reconstruction.
    raw_stats = equity_return_stats(p)
    duplicate_mask = p.duplicated(["timestamp","ticker"], keep=False)
    duplicate_groups = p.loc[duplicate_mask].groupby(["timestamp","ticker"])
    conflicting_duplicate_groups = int(
        duplicate_groups[numeric].nunique().max(axis=1).gt(1).sum()
    ) if duplicate_mask.any() else 0
    quality = {
        "raw_rows": int(len(p)),
        "raw_unique_tickers_including_index": int(p["ticker"].nunique()),
        "raw_equity_tickers": int(p.loc[p.ticker != "INDEX","ticker"].nunique()),
        "raw_sessions": int(p["date"].nunique()),
        "raw_duplicate_timestamp_ticker_rows": int(p.duplicated(["timestamp","ticker"]).sum()),
        "duplicate_timestamp_ticker_groups": int(duplicate_groups.ngroups),
        "conflicting_duplicate_key_groups": conflicting_duplicate_groups,
        "raw_crossed_quotes": int((p["bid"] > p["ask"]).sum()),
        "raw_missing_cells": int(p.isna().sum().sum()),
        "raw_invalid_ohlc_rows": int(((p.high < p.low) | (p.high < p.open) |
                                      (p.high < p.close) | (p.low > p.open) |
                                      (p.low > p.close)).sum()),
        **{f"raw_{key}": value for key, value in raw_stats.items()},
        "raw_price_continuity_warning": continuity_warning(raw_stats),
    }
    # Exact duplicate rows are dropped. If conflicting duplicate keys exist, keep the last
    # observation in file order and document the deterministic rule.
    p = p.drop_duplicates(subset=["timestamp","ticker"], keep="last")
    p = p.dropna(subset=["timestamp","ticker","open","high","low","close","volume"])
    p = p[(p.high >= p.low) & (p.high >= p.open) & (p.high >= p.close) &
          (p.low <= p.open) & (p.low <= p.close) & (p.volume >= 0)]
    p = p.sort_values(["ticker","timestamp"]).reset_index(drop=True)
    quality["clean_rows_after_dedup_and_ohlc_filter"] = int(len(p))
    quality["removed_duplicate_or_invalid_rows"] = int(quality["raw_rows"] - len(p))
    quality["clean_equity_tickers"] = int(p.loc[p.ticker != "INDEX","ticker"].nunique())
    quality["index_rows"] = int((p.ticker == "INDEX").sum())
    quality["sessions"] = sorted(p["date"].unique().tolist())
    quality["metadata_tickers"] = int(metadata.ticker.nunique())
    quality["constituent_weight_sum"] = float(constituents.index_weight.sum())
    quality["event_count"] = int(len(events))
    quality["fee_components"] = int(len(fees))
    # Rebuild a continuous session path. Raw files are not written back.
    p = reconstruct_continuous_session_paths(p)
    adjusted_stats = equity_return_stats(p)
    quality.update(adjusted_stats)
    quality["price_continuity_warning"] = continuity_warning(adjusted_stats)
    quality["price_path_assumption"] = CFG["price_path_assumption"]
    quality["price_path_note"] = PRICE_PATH_NOTE
    # Keep crossed quotes in the price table for OHLC research, but mark them unusable for spread.
    p["quote_valid"] = p["bid"].notna() & p["ask"].notna() & (p["bid"] > 0) & (p["ask"] >= p["bid"])
    return p, quality

def fee_map(fees):
    return dict(zip(fees["fee_component"], fees["value"]))

def make_15m_bars(clean_prices, metadata):
    p = clean_prices.copy()
    p["minute"] = pd.to_numeric(p["minute"], errors="coerce")
    p["bar_id"] = (p["minute"] // CFG["bar_minutes"]).astype(int)
    p["bar_timestamp"] = p["timestamp"].dt.floor("15min") + pd.Timedelta(minutes=14)
    # Align bars to each session's 09:30 start using the provided minute index.
    group_cols = ["ticker","date","bar_id"]
    p = p.sort_values(["ticker","date","timestamp"])
    agg = p.groupby(group_cols, sort=False).agg(
        timestamp=("bar_timestamp","last"),
        open=("open","first"), high=("high","max"), low=("low","min"),
        close=("close","last"), adj_close=("adj_close","last"),
        volume=("volume","sum"), bid=("bid","first"), ask=("ask","first"),
        quote_valid=("quote_valid","first"), minute_count=("minute","count")
    ).reset_index()
    # Quote half-spread: valid per-bar quote; otherwise ticker median, then global median.
    mid = (agg["bid"] + agg["ask"]) / 2
    agg["half_spread_bps"] = np.where(
        agg["quote_valid"] & (mid > 0),
        ((agg["ask"] - agg["bid"]) / mid) * 5000,
        np.nan
    )
    ticker_medians = agg.groupby("ticker")["half_spread_bps"].median()
    global_median = float(agg["half_spread_bps"].median())
    agg["half_spread_bps"] = agg["half_spread_bps"].fillna(agg["ticker"].map(ticker_medians)).fillna(global_median)
    agg["half_spread_bps"] = agg["half_spread_bps"].clip(lower=0)
    agg = agg.merge(metadata, on="ticker", how="left", validate="many_to_one")
    return agg.sort_values(["ticker","date","bar_id"]).reset_index(drop=True)

def add_features(bars):
    b = bars.copy()
    g = b.groupby(["ticker","date"], sort=False)
    b["ret_1"] = g["close"].pct_change(1)
    b["ret_4"] = g["close"].pct_change(4)  # 60-minute momentum on 15-minute bars
    b["ret_std_20"] = g["ret_1"].transform(lambda x: x.rolling(20, min_periods=8).std())
    b["momentum_score"] = b["ret_4"]
    b["meanrev_score"] = -b["ret_1"] / b["ret_std_20"].replace(0, np.nan)
    # Cross-sectional scores are ranked at each timestamp; no future observations are used.
    b["momentum_rank"] = b.groupby("timestamp")["momentum_score"].rank(pct=True)
    b["meanrev_rank"] = b.groupby("timestamp")["meanrev_score"].rank(pct=True)
    return b

def index_regimes(bars):
    idx = bars[bars.ticker == "INDEX"].copy().sort_values(["date","bar_id"])
    idx["ema12"] = idx.groupby("date")["close"].transform(lambda x: x.ewm(span=12, adjust=False).mean())
    idx["ema48"] = idx.groupby("date")["close"].transform(lambda x: x.ewm(span=48, adjust=False).mean())
    idx["tr_proxy"] = (idx["high"] - idx["low"]).groupby(idx["date"]).transform(
        lambda x: x.rolling(14, min_periods=5).mean()
    )
    idx["trend_strength"] = (idx["ema12"] - idx["ema48"]).abs() / idx["tr_proxy"].replace(0, np.nan)
    idx["index_ret"] = idx.groupby("date")["close"].pct_change()
    idx["rv20"] = idx.groupby("date")["index_ret"].transform(lambda x: x.rolling(20, min_periods=8).std())
    # Lagged rolling median avoids using the current observation to set its own threshold.
    idx["rv_median"] = idx.groupby("date")["rv20"].transform(
        lambda x: x.shift(1).rolling(20, min_periods=8).median()
    )
    idx["high_vol"] = idx["rv20"] > idx["rv_median"]
    idx["trend_regime"] = idx["trend_strength"] >= CFG["trend_threshold"]
    idx["regime"] = np.where(idx["high_vol"], "high_volatility",
                      np.where(idx["trend_regime"], "trending", "range_bound"))
    return idx[["timestamp","date","bar_id","trend_strength","high_vol","trend_regime","regime"]]

def event_blackout_mask(timestamps, events):
    ts = pd.Series(pd.to_datetime(timestamps))
    ev = events.copy()
    ev["timestamp"] = pd.to_datetime(ev["timestamp"], errors="coerce")
    blocked = np.zeros(len(ts), dtype=bool)
    for row in ev.dropna(subset=["timestamp"]).itertuples():
        window = CFG["breaking_news_blackout_minutes"] if "Breaking News" in str(row.event_type) else CFG["event_blackout_minutes"]
        delta = (ts - row.timestamp).abs()
        blocked |= (delta <= pd.Timedelta(minutes=window)).to_numpy()
    return blocked

def make_signals(features, regimes, events):
    b = features.merge(regimes, on=["timestamp","date","bar_id"], how="left")
    b["regime"] = b["regime"].fillna("unknown")
    b["strategy_score"] = np.nan
    b["strategy_mode"] = "none"
    # A: cross-sectional 60-minute momentum.
    b["score_A"] = b["momentum_score"]
    # B: short-horizon mean reversion, volatility-normalised.
    b["score_B"] = b["meanrev_score"]
    # C: momentum in trending conditions, mean reversion otherwise.
    b["score_C"] = np.where(b["trend_regime"].fillna(False), b["score_A"], b["score_B"])
    b["score_C"] = np.where(b["high_vol"].fillna(False), b["score_C"] * CFG["high_vol_scale"], b["score_C"])
    b["event_blocked"] = event_blackout_mask(b["timestamp"], events)
    return b

def build_weights(sig, strategy):
    b = sig.copy()
    score_col = {"A":"score_A","B":"score_B","C":"score_C"}[strategy]
    b["score"] = b[score_col]
    b["target_weight"] = 0.0
    b["hold_long"] = False
    b["hold_short"] = False
    # Keep a position while it remains in the outer exit band. That band is wider than the entry tail.
    scored = b["ticker"].ne("INDEX") & b["score"].notna()
    for ts, ix in b.loc[scored].groupby("timestamp").groups.items():
        scores = b.loc[ix, "score"]
        if scores.nunique(dropna=True) < 2:
            continue
        long_exit = scores.quantile(1 - CFG["exit_quantile"])
        short_exit = scores.quantile(CFG["exit_quantile"])
        b.loc[ix, "hold_long"] = scores >= long_exit
        b.loc[ix, "hold_short"] = scores <= short_exit
    # Tightest quotes are the lowest half-spread quantile of equities at that bar.
    b["tight_quote"] = False
    quoted = b["ticker"].ne("INDEX") & b["half_spread_bps"].notna()
    for ts, ix in b.loc[quoted].groupby("timestamp").groups.items():
        spreads = b.loc[ix, "half_spread_bps"].clip(lower=0)
        cutoff = spreads.quantile(CFG["tight_quote_quantile"])
        b.loc[ix, "tight_quote"] = spreads <= cutoff
    # No new trade when signals are unavailable, in event blackout windows, outside the
    # tight-quote group, or too late to complete a 15m round trip.
    eligible = b["ticker"].ne("INDEX") & b["score"].notna() & (~b["event_blocked"]) & b["tight_quote"]
    # Last two 15-minute bars of each session are not opened into.
    last_bar = b.groupby("date")["bar_id"].transform("max")
    eligible &= b["bar_id"] < (last_bar - 1)
    b["eligible"] = eligible
    for ts, ix in b.loc[eligible].groupby("timestamp").groups.items():
        rows = b.loc[ix]
        # New longs: most extreme names in the entry tail, capped per side.
        long_cut = rows["score"].quantile(1 - CFG["selection_quantile"])
        long_rows = rows[rows["score"] >= long_cut].sort_values("score", ascending=False)
        long_rows = long_rows.head(CFG["max_names_per_side"])
        # New shorts: most extreme names in the short entry tail, excluding hard-to-borrow names.
        short_pool = rows[(~rows["hard_to_borrow"].fillna(True)) &
                          (rows["locate_limit_shares"].fillna(0) > 0)]
        if len(short_pool):
            short_cut = short_pool["score"].quantile(CFG["selection_quantile"])
            short_rows = short_pool[short_pool["score"] <= short_cut].sort_values("score", ascending=True)
            short_rows = short_rows.head(CFG["max_names_per_side"])
        else:
            short_rows = short_pool
        if len(long_rows) == 0 or len(short_rows) == 0:
            continue
        # Equal-weight each side to 50% gross, then apply per-name cap.
        lw = min(CFG["long_gross_target"] / len(long_rows), CFG["max_position_weight"])
        sw = min(CFG["short_gross_target"] / len(short_rows), CFG["max_position_weight"])
        b.loc[long_rows.index, "target_weight"] = lw
        b.loc[short_rows.index, "target_weight"] = -sw
        # Regime C scales down gross in high-volatility regimes.
        if strategy == "C":
            hv = bool(rows["high_vol"].fillna(False).iloc[0])
            if hv:
                b.loc[long_rows.index, "target_weight"] *= CFG["high_vol_scale"]
                b.loc[short_rows.index, "target_weight"] *= CFG["high_vol_scale"]
    return b


def apply_constraints_and_backtest(weighted, fees, strategy):
    b = weighted.copy()
    fee = fee_map(fees)
    b = b.sort_values(["ticker","date","bar_id"]).reset_index(drop=True)
    grp = b.groupby(["ticker","date"], sort=False)

    # Signal at bar t close; enter at bar t+1 open; hold to bar t+2 open.
    # Require consecutive 15-minute bars so missing intervals are never silently bridged.
    b["entry_open"] = grp["open"].shift(-1)
    b["exit_open"] = grp["open"].shift(-2)
    b["entry_half_spread_bps"] = grp["half_spread_bps"].shift(-1)
    b["exit_half_spread_bps"] = grp["half_spread_bps"].shift(-2)
    b["entry_volume"] = grp["volume"].shift(-1)
    next_bar_id = grp["bar_id"].shift(-1)
    exit_bar_id = grp["bar_id"].shift(-2)
    contiguous = (next_bar_id == b["bar_id"] + 1) & (exit_bar_id == b["bar_id"] + 2)
    b["future_return"] = (b["exit_open"] / b["entry_open"] - 1).where(contiguous)

    # Translate target weights into tradable shares, respecting lot size, participation,
    # borrow availability and locate limits. NAV is a notional research unit.
    desired_shares = (b["target_weight"] * CFG["initial_capital"] / b["entry_open"]).replace([np.inf,-np.inf],np.nan).fillna(0)
    lot = b["lot_size"].fillna(1).clip(lower=1)
    max_part_shares = (b["entry_volume"].fillna(0) * b["max_participation_rate"].fillna(0)).clip(lower=0)
    max_part_lots = np.floor(max_part_shares / lot) * lot
    locate = b["locate_limit_shares"].fillna(0)
    cap_shares = np.where(desired_shares < 0, np.minimum(max_part_lots, locate), max_part_lots)
    rounded = np.floor(np.minimum(np.abs(desired_shares), cap_shares) / lot) * lot
    actual_shares = np.sign(desired_shares) * rounded
    actual_shares = np.where((actual_shares < 0) & b["hard_to_borrow"].fillna(True), 0, actual_shares)
    b["weight"] = (actual_shares * b["entry_open"] / CFG["initial_capital"]).replace([np.inf,-np.inf],np.nan).fillna(0)
    b["weight"] = b["weight"].clip(-CFG["max_position_weight"], CFG["max_position_weight"])

    # Apply portfolio gross/net exposure constraints at every signal timestamp.
    for ts, ix in b.groupby("timestamp").groups.items():
        w = b.loc[ix, "weight"].copy()
        gross = w.abs().sum()
        if gross > CFG["max_gross_exposure"]:
            w *= CFG["max_gross_exposure"] / gross
        net = w.sum()
        if abs(net) > CFG["max_net_exposure"]:
            long_gross = w[w > 0].sum()
            short_gross = -w[w < 0].sum()
            excess = abs(net) - CFG["max_net_exposure"]
            if long_gross > short_gross and long_gross > 0:
                w.loc[w > 0] *= max(0, (long_gross - excess) / long_gross)
            elif short_gross > 0:
                w.loc[w < 0] *= max(0, (short_gross - excess) / short_gross)
        b.loc[ix, "weight"] = w

    # Sequential execution simulation: at each next-bar open, the previous interval's
    # P&L is realised before the next target is executed. This makes the 1% daily loss
    # stop causal (no look-ahead in the stop decision).
    commission = float(fee.get("commission_bps_notional", 0))
    exchange = float(fee.get("exchange_fee_bps_notional", 0))
    sell_fee = float(fee.get("sec_fee_bps_sell_notional", fee.get("sec_fee_sell_notional", 0)))
    slip = 0.0 if CFG["provide_liquidity"] else CFG["slippage_bps_one_way"]
    spread_sign = -1.0 if CFG["provide_liquidity"] else 1.0
    long_finance = float(fee.get("financing_bps_annual_long_cash", 0))
    # Forecast used only as a cost hurdle. Momentum assumes the last 60-minute return continues.
    # Mean reversion assumes the last 15-minute return reverses. The hybrid uses the momentum
    # forecast in a trending regime and the reversal forecast otherwise.
    if strategy == "A":
        forecast = b["ret_4"]
    elif strategy == "B":
        forecast = -b["ret_1"]
    else:
        forecast = np.where(b["trend_regime"].fillna(False), b["ret_4"], -b["ret_1"])
    b["forecast_return"] = pd.to_numeric(pd.Series(np.asarray(forecast), index=b.index), errors="coerce")
    entry_spread = b["entry_half_spread_bps"].fillna(b["half_spread_bps"]).clip(lower=0)
    exit_spread = b["exit_half_spread_bps"].fillna(b["half_spread_bps"]).clip(lower=0)
    # provide_liquidity credits the half-spread (spread_sign is -1) instead of paying it.
    b["round_trip_cost"] = (
        2.0 * (commission + exchange + slip) + sell_fee + spread_sign * (entry_spread + exit_spread)
    ) / 10000.0
    # Completed tight-quote signal outcomes, net of each signal's own round trip.
    # A result is known two bars after the signal, so the entry rule never uses the trade it is deciding.
    signal_rows = (
        b["ticker"].ne("INDEX") & b["tight_quote"] & b["target_weight"].ne(0) & b["future_return"].notna()
    )
    directional_net = np.sign(b["target_weight"]) * b["future_return"] - b["round_trip_cost"]
    signal_outcomes = (
        pd.DataFrame({"timestamp": b.loc[signal_rows, "timestamp"], "net": directional_net.loc[signal_rows]})
        .groupby("timestamp")["net"]
        .agg(["sum", "count"])
    )
    annual_fraction = CFG["bar_minutes"] / (365.0 * 24 * 60)
    b["prev_weight"] = 0.0
    b["delta_weight"] = 0.0
    b["turnover"] = 0.0
    b["transaction_cost_return"] = 0.0
    b["financing_cost_return"] = 0.0
    b["gross_pnl_return"] = 0.0
    b["net_pnl_return"] = 0.0
    b["holding_age_bars"] = 0
    b["daily_stop_active"] = False

    prev_weights = {}
    holding_ages = {}
    prev_long_signal = {}
    prev_short_signal = {}
    ordered_ts = list(b.sort_values("timestamp")["timestamp"].drop_duplicates())
    ts_index = {timestamp: i for i, timestamp in enumerate(ordered_ts)}
    hist_sum = 0.0
    hist_count = 0
    next_to_ingest = 0
    current_date = None
    daily_equity = 1.0
    stopped = False
    previous_period_net = None

    for ts, ix in b.groupby("timestamp", sort=True).groups.items():
        g = b.loc[ix]
        date_value = str(g["date"].iloc[0])
        if date_value != current_date:
            current_date = date_value
            prev_weights = {}
            holding_ages = {}
            prev_long_signal = {}
            prev_short_signal = {}
            daily_equity = 1.0
            stopped = False
            previous_period_net = None
        # The previous signal's open-to-open return is now realised at this execution open.
        if previous_period_net is not None:
            daily_equity *= (1.0 + previous_period_net)
            if daily_equity - 1.0 <= -CFG["daily_loss_limit"]:
                stopped = True

        known_until = ts_index[ts] - 2
        while next_to_ingest <= known_until:
            past_ts = ordered_ts[next_to_ingest]
            next_to_ingest += 1
            if past_ts in signal_outcomes.index:
                hist_sum += float(signal_outcomes.at[past_ts, "sum"])
                hist_count += int(signal_outcomes.at[past_ts, "count"])
        expected_net = (hist_sum / hist_count) if hist_count else np.nan

        tickers = g.index[g["ticker"] != "INDEX"]
        signal_weight = g.loc[tickers, "weight"].copy()
        max_hold_bars = max(1, CFG["max_holding_minutes"] // CFG["bar_minutes"])
        max_names = int(CFG["max_names_per_side"])
        kept_weight = {}
        new_long = []
        new_short = []
        for row_idx in tickers:
            ticker = b.at[row_idx, "ticker"]
            prev_w = prev_weights.get(ticker, 0.0)
            age = holding_ages.get(ticker, 0)
            signal = 0.0 if stopped else float(signal_weight.loc[row_idx])
            hold_long = bool(b.at[row_idx, "hold_long"])
            hold_short = bool(b.at[row_idx, "hold_short"])
            if signal > 0:
                rank_changed = not prev_long_signal.get(ticker, False)
            elif signal < 0:
                rank_changed = not prev_short_signal.get(ticker, False)
            else:
                rank_changed = False
            # Open only when completed signals have, on average, earned more than their costs.
            clears_cost = (
                hist_count >= CFG["min_completed_signals"]
                and pd.notna(expected_net)
                and expected_net > 0
            )
            if prev_w > 0 and age < max_hold_bars and hold_long and not stopped:
                kept_weight[row_idx] = prev_w
            elif prev_w < 0 and age < max_hold_bars and hold_short and not stopped:
                kept_weight[row_idx] = prev_w
            elif prev_w != 0:
                kept_weight[row_idx] = 0.0
            elif signal > 0 and rank_changed and clears_cost and bool(b.at[row_idx, "tight_quote"]):
                new_long.append((row_idx, signal))
            elif signal < 0 and rank_changed and clears_cost and bool(b.at[row_idx, "tight_quote"]):
                new_short.append((row_idx, signal))
            else:
                kept_weight[row_idx] = 0.0
        long_open = sum(weight > 0 for weight in kept_weight.values())
        short_open = sum(weight < 0 for weight in kept_weight.values())
        new_long.sort(key=lambda item: item[1], reverse=True)
        new_short.sort(key=lambda item: item[1])
        accepted_long = []
        accepted_short = []
        for row_idx, signal in new_long:
            if long_open + len(accepted_long) < max_names:
                kept_weight[row_idx] = signal
                accepted_long.append((row_idx, signal))
            else:
                kept_weight[row_idx] = 0.0
        for row_idx, signal in new_short:
            if short_open + len(accepted_short) < max_names:
                kept_weight[row_idx] = signal
                accepted_short.append((row_idx, signal))
            else:
                kept_weight[row_idx] = 0.0

        def within_limits(weights):
            gross = sum(abs(weight) for weight in weights.values())
            net = sum(weights.values())
            return gross <= CFG["max_gross_exposure"] + 1e-9 and abs(net) <= CFG["max_net_exposure"] + 1e-9

        # Drop the weakest new name on the heavy side. Existing holdings keep their weight.
        while accepted_long or accepted_short:
            if within_limits(kept_weight):
                break
            long_sum = sum(weight for weight in kept_weight.values() if weight > 0)
            short_sum = -sum(weight for weight in kept_weight.values() if weight < 0)
            if long_sum >= short_sum and accepted_long:
                row_idx, _signal = accepted_long.pop()
            elif accepted_short:
                row_idx, _signal = accepted_short.pop()
            elif accepted_long:
                row_idx, _signal = accepted_long.pop()
            else:
                break
            kept_weight[row_idx] = 0.0
        desired = pd.Series(kept_weight, dtype=float).reindex(tickers).fillna(0.0)

        prev_w_series = pd.Series({i: prev_weights.get(b.at[i, "ticker"], 0.0) for i in tickers})
        delta = desired - prev_w_series
        entry_turnover = delta.abs()
        half_spread = g.loc[tickers, "entry_half_spread_bps"].fillna(g.loc[tickers, "half_spread_bps"]).clip(lower=0)
        entry_sell = delta < 0
        entry_cost_bps = commission + exchange + slip + spread_sign * half_spread + entry_sell.astype(float) * sell_fee
        entry_cost = entry_turnover * entry_cost_bps / 10000

        w = desired
        future_ret = g.loc[tickers, "future_return"].fillna(0)
        borrow_fee = g.loc[tickers, "borrow_fee_bps_annual"].fillna(0)
        finance = (
            w.clip(lower=0) * long_finance +
            w.clip(upper=0).abs() * borrow_fee
        ) / 10000 * annual_fraction

        # Force liquidation after the final complete holding interval of each session.
        max_bar = int(g["bar_id"].max())
        last_active = g.loc[tickers, "bar_id"] == (max_bar - 2)
        exit_turnover = w.abs().where(last_active, 0.0)
        exit_spread = g.loc[tickers, "exit_half_spread_bps"].fillna(g.loc[tickers, "half_spread_bps"]).clip(lower=0)
        exit_sell = w > 0
        exit_cost_bps = commission + exchange + slip + spread_sign * exit_spread + exit_sell.astype(float) * sell_fee
        exit_cost = exit_turnover * exit_cost_bps / 10000

        gross_pnl = w * future_ret
        total_cost = entry_cost + exit_cost
        net_pnl = gross_pnl - total_cost - finance
        total_turnover = entry_turnover + exit_turnover

        b.loc[tickers, "weight"] = w
        b.loc[tickers, "prev_weight"] = prev_w_series
        b.loc[tickers, "delta_weight"] = delta
        b.loc[tickers, "turnover"] = total_turnover
        b.loc[tickers, "transaction_cost_return"] = total_cost
        b.loc[tickers, "financing_cost_return"] = finance
        b.loc[tickers, "gross_pnl_return"] = gross_pnl
        b.loc[tickers, "net_pnl_return"] = net_pnl
        b.loc[tickers, "daily_stop_active"] = stopped

        # Position age for the next execution interval.
        new_prev = {}
        new_ages = {}
        for row_idx in tickers:
            ticker = b.at[row_idx, "ticker"]
            target = float(w.loc[row_idx])
            old = prev_weights.get(ticker, 0.0)
            old_age = holding_ages.get(ticker, 0)
            if target != 0:
                age = old_age + 1 if old != 0 and np.sign(old) == np.sign(target) else 1
                new_prev[ticker] = target
                new_ages[ticker] = age
        if bool(last_active.any()):
            # End-of-day liquidation: positions are flat after the last holding interval.
            new_prev = {}
            new_ages = {}
        prev_weights = new_prev
        holding_ages = new_ages
        prev_long_signal = {}
        prev_short_signal = {}
        for row_idx in tickers:
            ticker = b.at[row_idx, "ticker"]
            signal = float(signal_weight.loc[row_idx])
            if signal > 0:
                prev_long_signal[ticker] = True
            elif signal < 0:
                prev_short_signal[ticker] = True

        period_net = float(net_pnl.sum())
        previous_period_net = period_net if np.isfinite(period_net) else 0.0

    valid = b["future_return"].notna() & b["ticker"].ne("INDEX")
    portfolio = b.loc[valid].groupby(["timestamp","date","regime"], as_index=False).agg(
        gross_return=("gross_pnl_return","sum"),
        net_return=("net_pnl_return","sum"),
        transaction_cost=("transaction_cost_return","sum"),
        financing_cost=("financing_cost_return","sum"),
        turnover=("turnover","sum"),
        gross_exposure=("weight", lambda x: x.abs().sum()),
        net_exposure=("weight","sum"),
        active_names=("weight", lambda x: int((x != 0).sum())),
        daily_stop_active=("daily_stop_active","max")
    )
    bt = b.loc[valid & (b["weight"] != 0)].copy()
    if bt.empty:
        trades = pd.DataFrame(columns=[
            "ticker", "date", "episode_id", "bars_held", "mean_abs_weight",
            "pnl_contribution", "gross_contribution", "transaction_cost",
            "trade_return_bps", "holding_minutes",
        ])
    else:
        bt["direction"] = np.sign(bt["weight"])
        bt["episode_break"] = (
            (bt["ticker"] != bt["ticker"].shift()) |
            (bt["date"] != bt["date"].shift()) |
            (bt["direction"] != bt["direction"].shift()) |
            (bt["bar_id"] != bt.groupby(["ticker","date"]).bar_id.shift(1) + 1)
        )
        bt["episode_id"] = bt.groupby("ticker")["episode_break"].cumsum()
        trades = bt.groupby(["ticker","date","episode_id"], as_index=False).agg(
            bars_held=("weight","size"),
            mean_abs_weight=("weight", lambda x: x.abs().mean()),
            pnl_contribution=("net_pnl_return","sum"),
            gross_contribution=("gross_pnl_return","sum"),
            transaction_cost=("transaction_cost_return","sum")
        )
        trades["trade_return_bps"] = (
            trades["pnl_contribution"] /
            trades["mean_abs_weight"].replace(0,np.nan) * 10000
        )
        trades["holding_minutes"] = trades["bars_held"] * CFG["bar_minutes"]
    return b, portfolio.sort_values("timestamp"), trades

def performance_metrics(portfolio, trades):
    r = portfolio["net_return"].fillna(0)
    equity = (1 + r).cumprod()
    peak = equity.cummax()
    dd = equity / peak - 1
    periods_per_year = CFG["bars_per_day"] * CFG["trading_days_per_year"]
    vol = r.std(ddof=1)
    sharpe = (r.mean() / vol * np.sqrt(periods_per_year)) if vol and np.isfinite(vol) else np.nan
    wins = trades["trade_return_bps"] > 0 if len(trades) else pd.Series(dtype=bool)
    positive = trades.loc[trades.trade_return_bps > 0, "pnl_contribution"].sum() if len(trades) else 0
    negative = -trades.loc[trades.trade_return_bps < 0, "pnl_contribution"].sum() if len(trades) else 0
    pf = positive / negative if negative > 0 else (np.inf if positive > 0 else np.nan)
    daily = portfolio.groupby("date")["net_return"].sum()
    metrics = {
        "net_total_return_pct": float((equity.iloc[-1] - 1) * 100) if len(equity) else 0.0,
        "net_sharpe_annualized_indicative": float(sharpe) if np.isfinite(sharpe) else None,
        "maximum_drawdown_pct": float(dd.min() * 100) if len(dd) else 0.0,
        "profit_factor_trade_episodes": float(pf) if np.isfinite(pf) else None,
        "win_rate_trade_episodes_pct": float(wins.mean() * 100) if len(wins) else None,
        "average_trade_return_bps": float(trades["trade_return_bps"].mean()) if len(trades) else None,
        "average_trade_holding_minutes": float(trades["holding_minutes"].mean()) if len(trades) else None,
        "total_turnover_pct_nav": float(portfolio["turnover"].sum() * 100),
        "transaction_cost_bps_nav": float(portfolio["transaction_cost"].sum() * 10000),
        "financing_cost_bps_nav": float(portfolio["financing_cost"].sum() * 10000),
        "average_gross_exposure_pct": float(portfolio["gross_exposure"].mean() * 100),
        "average_net_exposure_pct": float(portfolio["net_exposure"].mean() * 100),
        "positive_trade_episodes": int((trades.trade_return_bps > 0).sum()) if len(trades) else 0,
        "negative_trade_episodes": int((trades.trade_return_bps < 0).sum()) if len(trades) else 0,
        "number_trade_episodes": int(len(trades)),
        "daily_stop_periods": int(portfolio["daily_stop_active"].sum()) if "daily_stop_active" in portfolio else 0,
        "number_sessions": int(portfolio["date"].nunique()),
        "daily_returns_pct": {str(k): float(v*100) for k,v in daily.items()},
    }
    portfolio = portfolio.copy()
    portfolio["equity"] = (1 + portfolio["net_return"]).cumprod()
    portfolio["drawdown"] = portfolio["equity"] / portfolio["equity"].cummax() - 1
    return metrics, portfolio

def run_all():
    OUT.mkdir(exist_ok=True)
    prices, metadata, constituents, events, fees = load_inputs()
    clean, quality = validate_and_clean(prices, metadata, constituents, events, fees)

    # Persist diagnostics first. The gate scores the reconstructed path. If that path
    # still fails, stop before bar construction, features, signals and backtesting.
    write_data_quality_report(quality)
    enforce_data_quality_gate(quality)
    write_data_quality_report(quality)

    bars = make_15m_bars(clean, metadata)
    features = add_features(bars)
    regimes = index_regimes(bars)
    signals = make_signals(features, regimes, events)
    all_metrics, all_portfolios, all_trades = [], {}, {}
    for strategy, name in [("A","Momentum"),("B","Mean reversion"),("C","Regime-switching hybrid")]:
        weighted = build_weights(signals, strategy)
        positions, portfolio, trades = apply_constraints_and_backtest(weighted, fees, strategy)
        metrics, portfolio = performance_metrics(portfolio, trades)
        metrics["experiment"] = strategy
        metrics["strategy"] = name
        all_metrics.append(metrics)
        all_portfolios[name] = portfolio
        all_trades[name] = trades
        trades.to_csv(OUT / f"trades_{strategy}.csv", index=False)
        portfolio.to_csv(OUT / f"portfolio_returns_{strategy}.csv", index=False)
        positions.loc[positions.ticker.ne("INDEX")].to_csv(OUT / f"positions_{strategy}.csv", index=False)
    summary = pd.DataFrame(all_metrics)
    summary.to_csv(OUT / "strategy_summary.csv", index=False)
    # Regime performance for all strategies.
    regime_rows = []
    for name, pf in all_portfolios.items():
        for regime, sub in pf.groupby("regime"):
            rr = sub["net_return"]
            regime_rows.append({
                "strategy": name, "regime": regime, "periods": len(sub),
                "net_return_pct": float(((1+rr).prod()-1)*100),
                "mean_15m_return_bps": float(rr.mean()*10000),
                "vol_15m_bps": float(rr.std(ddof=1)*10000) if len(rr)>1 else np.nan,
                "turnover_pct_nav": float(sub.turnover.sum()*100),
                "transaction_cost_bps_nav": float(sub.transaction_cost.sum()*10000)
            })
    regime_df = pd.DataFrame(regime_rows)
    regime_df.to_csv(OUT / "performance_by_regime.csv", index=False)
    # Benchmark-weight and sector exposure diagnostics from the supplied constituent and metadata files.
    exposure = []
    sector_rows = []
    for strategy, name in [("A","Momentum"),("B","Mean reversion"),("C","Regime-switching hybrid")]:
        pos = pd.read_csv(OUT / f"positions_{strategy}.csv")
        pos = pos[pos.ticker.ne("INDEX")].merge(
            constituents, on="ticker", how="left", validate="many_to_one"
        )
        if "sector" not in pos.columns:
            pos = pos.merge(metadata[["ticker","sector"]], on="ticker", how="left", validate="many_to_one")
        pos["index_weight"] = pos["index_weight"].fillna(0)
        snapshots = []
        for ts, sub in pos.groupby("timestamp"):
            long = sub[sub.weight > 0]
            short = sub[sub.weight < 0]
            snapshots.append({
                "timestamp": ts,
                "gross": sub.weight.abs().sum(),
                "net": sub.weight.sum(),
                "long_names": int((sub.weight > 0).sum()),
                "short_names": int((sub.weight < 0).sum()),
                "long_active_vs_index": long.weight.sum() - long.index_weight.sum(),
            })
        snap = pd.DataFrame(snapshots)
        exposure.append({
            "strategy": name,
            "average_gross_exposure_pct": float(snap.gross.mean()*100),
            "maximum_gross_exposure_pct": float(snap.gross.max()*100),
            "average_net_exposure_pct": float(snap.net.mean()*100),
            "average_long_names": float(snap.long_names.mean()),
            "average_short_names": float(snap.short_names.mean()),
            "average_long_side_active_weight_vs_index_pct": float(snap.long_active_vs_index.mean()*100),
        })
        sector = pos.groupby("sector", dropna=False).agg(
            average_net_weight=("weight","mean"),
            average_gross_weight=("weight", lambda x: x.abs().mean())
        ).reset_index()
        sector["strategy"] = name
        sector_rows.append(sector)
    pd.DataFrame(exposure).to_csv(OUT / "exposure_diagnostics.csv", index=False)
    pd.concat(sector_rows, ignore_index=True).to_csv(OUT / "sector_exposure.csv", index=False)
    # Figures
    plt.figure(figsize=(10,5))
    for name, pf in all_portfolios.items():
        plt.plot(pd.to_datetime(pf.timestamp), pf.equity, label=name)
    plt.title("Intraday strategy equity curves (net of modelled costs)")
    plt.xlabel("Timestamp"); plt.ylabel("Growth of $1"); plt.legend(); plt.tight_layout()
    plt.savefig(OUT / "equity_curves.png", dpi=160); plt.close()
    plt.figure(figsize=(10,5))
    for name, pf in all_portfolios.items():
        plt.plot(pd.to_datetime(pf.timestamp), pf.drawdown*100, label=name)
    plt.title("Intraday strategy drawdowns")
    plt.xlabel("Timestamp"); plt.ylabel("Drawdown (%)"); plt.legend(); plt.tight_layout()
    plt.savefig(OUT / "drawdowns.png", dpi=160); plt.close()
    if len(regime_df):
        pivot = regime_df.pivot(index="regime", columns="strategy", values="net_return_pct").fillna(0)
        ax = pivot.plot(kind="bar", figsize=(9,5))
        ax.set_title("Net return by market regime")
        ax.set_ylabel("Compounded return (%)")
        plt.tight_layout(); plt.savefig(OUT / "regime_performance.png", dpi=160); plt.close()
    # Data-quality report CSV.
    pd.DataFrame([{"check":k,"value":json.dumps(v) if isinstance(v,(list,dict)) else v} for k,v in quality.items()]).to_csv(OUT/"data_quality.csv", index=False)
    # Save run config.
    (OUT / "run_config.json").write_text(json.dumps(CFG, indent=2))
    return quality, summary, regime_df

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true", help="Run validation, all three strategies and outputs.")
    args = parser.parse_args()
    if args.run:
        try:
            quality, summary, regimes = run_all()
        except DataQualityError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(2)
        print("DATA QUALITY")
        print(json.dumps(quality, indent=2))
        print("\nSTRATEGY SUMMARY")
        print(summary[["experiment","strategy","net_total_return_pct","net_sharpe_annualized_indicative",
                       "maximum_drawdown_pct","profit_factor_trade_episodes",
                       "win_rate_trade_episodes_pct","average_trade_return_bps",
                       "total_turnover_pct_nav","transaction_cost_bps_nav"]].to_string(index=False))
        print("\nREGIME PERFORMANCE")
        print(regimes.to_string(index=False))
