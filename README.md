
# European Intraday Strategy Lab

Reproducible research project comparing three intraday strategies on the supplied synthetic dataset:

- **A — Momentum**
- **B — Mean reversion**
- **C — Regime-switching hybrid**

The project uses only the five supplied CSV files. It does not fetch external prices, calendars, consensus estimates or other market data.

## Dataset

Place the five supplied CSV files in `data/raw/`:

- `synthetic_intraday_prices_500tickers_v2.csv`
- `ticker_metadata_500tickers_v2.csv`
- `index_constituents_500tickers_v2.csv`
- `scheduled_events_calendar_500tickers_v2.csv`
- `fee_schedule_500tickers_v2.csv`

## Run

Create an environment and install dependencies:

```bash
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows PowerShell
# .venv\Scripts\Activate.ps1

pip install -r requirements.txt
python run_project.py
```

All generated tables and figures are written to `outputs/`.


## Hard price-continuity quality gate

The supplied one-minute file does not contain a continuous price path. Inside each bar the open,
high, low and close agree (median absolute open-to-close return about 0.08%), but the price level
is redrawn every minute (median absolute close-to-close return about 62.7%; about 80.5% of those
moves exceed 20%). The raw files cannot be replaced, and the thresholds are not relaxed.

Research assumption, applied in `validate_and_clean()` before the gate:

- Leave `data/raw/` unchanged.
- For each ticker-session, including `INDEX`, anchor at the first open.
- Compound that bar's own open-to-close return forward.
- Scale high, low, bid, ask and adjusted close with the open, so relative ranges and quoted spreads stay the same.
- Drop the raw gap from one minute's close to the next minute's open. That gap is a level redraw, not a return.

The gate then scores this reconstructed path. It still blocks the strategy pipeline when either
threshold fails. Default thresholds in `src/run_research.py` (`CFG`):

- Median absolute one-minute equity return must be no greater than **2.0%**.
- No more than **1.0%** of absolute one-minute equity returns may exceed **20%**.

If either threshold is breached, the script writes `outputs/data_quality.json` and
`outputs/data_quality.csv`, prints the failure reasons and exits with status code 2. It does not
generate new strategy metrics, positions, trades or charts. Raw and reconstructed diagnostics are
both stored. Do not lower the thresholds to force a backtest to run.

Run the gate tests with:

```bash
python -m unittest discover -s tests -v
```

## Common experimental assumptions

- Raw data: supplied 1-minute bars; deduplicated, rebuilt into a continuous session path from within-bar returns, then aggregated to 15-minute bars.
- Universe: all 500 supplied equity tickers; `INDEX` is used for market regime classification.
- Rebalance: a new name is opened only when its rank newly enters the top or bottom 5% and that side has a free slot. A name that was already in the entry set is not chased. An open name keeps its weight until its rank leaves the outer 20%, the holding limit is reached, or the session ends.
- Signal timing: signal is computed using the completed bar; execution is assumed at the next 15-minute bar open.
- Holding interval: next bar open to the following bar open (15 minutes per interval). Positions stay on until the score leaves the exit band, the holding limit is reached, or the session ends. No overnight positions.
- Portfolio: long/short; new entries from the top and bottom 5% of scores, at most 10 names per side; an open position is kept while it remains in the outer 20%. Target 50% long and 50% short gross.
- Position constraints: maximum 5% NAV per name, 100% gross exposure, 10% net exposure.
- Capital: $10,000,000 notional research NAV (currency is not specified in the synthetic data; `$` is a neutral notional unit, not a claim about instrument currency).
- Risk: 1% daily loss stop is evaluated on realised open-to-open interval P&L; after the threshold is breached, subsequent targets are flattened at the next scheduled execution. A position is also flattened after 180 minutes (twelve 15-minute intervals) if it is still open.
- Shorting: hard-to-borrow names are excluded from short candidates; locate limits are applied.
- Execution: the book supplies liquidity and is assumed filled at its own quote. The half-spread is earned on entry and on exit, and crossing slippage is not charged. Commission, exchange fee and sell-side fee are still paid. A new name must be in the tightest 20% of equity quotes at that bar, measured by half-spread. A new trade is opened only after at least 30 completed tight-quote signals, and only when the average of those signals is positive after fees and the spread credit. A signal's result is used only once it is known, two bars after the signal. Invalid or crossed quotes still fall back to the ticker median, then the global median.
- Fees: commission, exchange, sell-side fee, financing and borrow conventions are read from the supplied fee schedule and ticker metadata.
- Participation: ticker-specific maximum participation rate is applied to next-bar aggregated volume; shares are rounded down to lot size.
- Event risk: no new position is initiated within ±15 minutes of scheduled events and ±30 minutes of a "Breaking News Window". Event direction/impact is unknown, so no directional event signal is inferred.
- Regime: index EMA spread divided by a rolling true-range proxy; high volatility is identified using a lagged rolling median. Strategy C uses momentum in trending regimes, mean reversion otherwise, and halves gross target in high-volatility regimes.

## Strategy definitions

### A — Momentum
Cross-sectional rank of 60-minute return (`close / close.shift(4) - 1` on 15-minute bars). New longs are the strongest names in the top 5% and new shorts are the weakest names in the bottom 5%, with at most 10 names per side. A name already held is kept while it remains in the outer 20%, subject to shortability and execution constraints.

### B — Mean reversion
Negative one-bar return divided by the rolling 20-bar standard deviation of one-bar returns. Long the most negative standardised moves and short the most positive, subject to constraints.

### C — Regime-switching hybrid
Uses the momentum score when the index regime is trending; otherwise uses the mean-reversion score. In high-volatility regimes, target gross exposure is scaled by 50%.

## Data cleaning and limitations

- Duplicate `(timestamp, ticker)` keys are deduplicated deterministically by keeping the last row; conflicting duplicate-key groups are counted in the quality report.
- Invalid OHLC rows are removed.
- Crossed quotes are not used directly for spread estimation; fallback spread estimates are used.
- The dataset contains only five sessions (10–14 November 2025). Raw close-to-close continuity fails (median absolute one-minute equity return about 62.7%). Backtests use the reconstructed path described above, so results rank the three strategies only under that assumption. Sharpe is annualised mechanically and is indicative only; five sessions cannot establish a reliable long-run Sharpe, drawdown distribution or profitability.
- Synthetic data does not establish live-market alpha. Results are conditional on the simulated data-generating process.
- The implementation is a research prototype, not a production trading system. It does not model queue priority, partial fills, market impact beyond the explicit slippage assumption, exchange-specific auction mechanics or intrabar stop execution.
- The data do not specify instrument currency, so NAV is treated as a common notional unit.
- The event calendar contains timestamps and labels only; no actual/consensus data or event direction is provided.

## Outputs

- `strategy_summary.csv`: headline performance and risk metrics.
- `performance_by_regime.csv`: performance by trending/range-bound/high-volatility regime.
- `trades_A.csv`, `trades_B.csv`, `trades_C.csv`: approximate continuous-position episodes.
- `portfolio_returns_*.csv`: portfolio interval returns.
- `positions_*.csv`: instrument-level target/executed weights and diagnostics.
- `equity_curves.png`, `drawdowns.png`, `regime_performance.png`.
- `data_quality.json` and `data_quality.csv`.

## Reproducibility

The script is deterministic. It records the common configuration in `outputs/run_config.json`. All three strategies are run from the same cleaned bars and the same execution/cost model.
