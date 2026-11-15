# BTCUSDT M5 – 4-hour MFE/MAE research

Based on the **V2 Liquidity Sweep + CHoCH** setup definition (`backtest_v2.py`). No orders are placed.

## GitHub Android installation

Copy `mfe_mae.py` and `backtest_v2.py` to the repository root, alongside `btc_m5.csv` (the historical candles). Add `.github/workflows/mfe-mae.yml` with exactly this path. Open **Actions → BTC M5 MFE MAE (4h) → Run workflow**. Download artifact **btc-mfe-mae-4h**.

## Results

- `excursions.csv`: MFE and MAE per confirmed signal over 48 candles from next M5 open, including entry bar; USD price moves and times.
- `overview.csv`: median MFE, MAE and times, separately for train (first 70%) and test (last 30%).
- `sl_tp_grid.csv`: first-touch outcomes for 6 stop distances × 7 take-profit distances, by window 100/500 and train/test. Percent distances are absolute percent of BTC entry price, **not** risk/reward ratios. Costs default to 6 bps fees + 2 bps slippage per side (16 bps round trip).

**Important limitations:** M5 OHLC cannot establish intrabar ordering; same-bar SL+TP hits are conservatively scored as SL and counted in `ambiguous_same_bar`. Intrabar gap execution and actual spread/orderbook fills are not modeled. MFE and MAE maxima can occur in either order; do not treat MFE/MAE ratio as realized RR. `sl_tp_grid.csv` is a *per-signal, independent hypothetical trade study*: signals may overlap, so aggregate grid metrics do not represent a deployable portfolio or capital allocation. Cost model subtracts fixed round-trip bps, not actual fills. Comparing 42 grids on test data creates selection bias; choose parameters using train and reserve untouched future data for validation. No claims of profitability.
