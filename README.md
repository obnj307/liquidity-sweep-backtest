# BTC Liquidity Sweep + CHoCH V2 — Research backtest

Run locally or in GitHub Actions with Python 3.11 (standard library only):

```bash
python backtest_v2.py --csv btc_m5.csv --out results
```

Outputs: `summary_v2.csv`, `trades_v2.csv`. No trading or Telegram messages.

Rules: confirmed 5-left/5-right swing pivots, minimum pivot prominence 0.5 previous ATR(14), minimum sweep penetration 0.1 ATR, return within 0.5 ATR of level, consumed levels, fixed CHoCH threshold from 12 preceding bars, CHoCH within 6 candles, stop beyond sweep extreme by 0.1 ATR, next-bar-open entry, RR 1/1.5/2, target distance >= 2x modeled roundtrip costs, 48-bar maximum hold. Conservative SL-first on ambiguous intrabar touches. 70% train / 30% chronological test. Fees 6 bps/side, slippage 2 bps/side.

Limitations: heuristic CHoCH definition, no intrabar path, funding/spread not separately modeled, 180-day sample, limited trade count, no parameter selection/optimization. Compounded returns assume full-notional reinvestment and are not a realistic risk-sized portfolio model. No claim of profitable strategy.
