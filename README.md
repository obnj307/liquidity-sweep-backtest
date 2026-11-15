# BTCUSDT Liquidity Sweep Backtest

Research-only Python 3.11 script, no trading and no Telegram messages.

Run `python backtest.py --days 180` to download 180 days of Bitget USDT perpetual M5 candles and evaluate 12 variants.
Run `python backtest.py --days 0` to attempt the full accessible history (can take a long time).
Run `python backtest.py --reuse` to re-evaluate an existing btc_m5.csv without downloading.

Outputs: `summary.csv`, `trades.csv`, `btc_m5.csv`.

Rules: 3-left/3-right confirmed swing points, sweep by >=0.1 ATR(14), close back within 0.5 ATR, single or approximate equal highs/lows, 100/500-bar pivot-age windows. Next-bar-open entry, stop at sweep candle extreme, take profit at 1/1.5/2 R, maximum 48 bars holding, stop-first on ambiguous candles. At most one open position per strategy variant. Costs default 6 bps fee and 2 bps slippage per side (illustrative; set to your actual fees).

Limitations: A single M5 candle does not reveal intrabar execution order. This is a conservative approximation, not a broker execution simulation. No funding or liquidation modeling. Full history depends on Bitget API availability. No results are claimed without actual data. Multiple variants are exploratory and require out-of-sample testing before using in live signals.
