# Bot Improvements Roadmap

This document tracks planned enhancements beyond the immediate optimizations already implemented.

## Implemented (recent)
- Z-score based breakout with EWMA volatility (`mode`, `z_threshold`, `ewm_lambda`)
- ATR-like SL/TP using recent absolute price moves (`atr_window_sec`, `alpha_sl`, `beta_tp`)
- Spot SELL normalization (minTradeDumping/max) and BUY `minAmount` checks
- Idempotent orders via `clientOrderId`
- Daily loss cap and cool-off on consecutive losses
- Cross-profile state resume; improved DEBUG diagnostics; file log filtered to important events

## Next Iterations
1. WebSocket price feed (public) with REST fallback
   - Reduce latency and noise; stabilize z-score and ATR estimation
2. CUSUM change detection (optional alternative to N-tick confirmation)
   - Parameters: h threshold (in sigma); directionality
3. Hysteresis scaled by volatility
   - Make exit hysteresis proportional to current sigma instead of fixed percent
4. Risk-parity sizing
   - Adjust `position_usdt` per symbol to target constant monetary SL (≈ α × ATR)
5. Quantile-controlled signal cadence
   - Adapt z-threshold to target a daily opportunity rate per symbol
6. PnL net of fees tracking
   - Parse fees from fills (if available) and log net PnL
7. Token-bucket RPS controller (shared across workers)
   - Replace stride+jitter for finer rate-limit control
8. Auto regime switching per symbol
   - Momentum vs contrarian based on recent outcome stats

## Nice-to-have
- Web dashboard (FastAPI) for status, config, logs, and symbol refresh
- Symbol health checks (spread filter, endpoint quality)
- Backtesting harness for parameter calibration


