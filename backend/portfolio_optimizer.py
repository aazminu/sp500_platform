"""
Walk-forward portfolio optimization, risk-adjusted performance metrics,
and rebalance order generation for the S&P 500 platform.
"""
from __future__ import annotations

import math
import statistics
from typing import Dict, List, Sequence


def compute_returns_from_prices(close_prices: Sequence[float]) -> List[float]:
    """Compute period-over-period simple returns from chronological close prices."""
    returns: List[float] = []
    for i in range(1, len(close_prices)):
        prev_p = float(close_prices[i - 1])
        curr_p = float(close_prices[i])
        if prev_p > 0:
            returns.append((curr_p - prev_p) / prev_p)
    return returns


def compute_sharpe_and_sortino(
    returns: Sequence[float],
    risk_free_annual: float = 0.04,
    periods_per_year: int = 252,
) -> Dict[str, float]:
    """Compute annualized return, volatility, Sharpe ratio, Sortino ratio, and max drawdown."""
    if not returns:
        return {
            "annualized_return": 0.0,
            "annualized_volatility": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "max_drawdown_pct": 0.0,
        }

    rf_per_period = (1.0 + risk_free_annual) ** (1.0 / periods_per_year) - 1.0
    excess = [r - rf_per_period for r in returns]
    mean_ret = sum(returns) / len(returns)
    ann_return = (1.0 + mean_ret) ** periods_per_year - 1.0

    if len(returns) >= 2:
        std_ret = statistics.stdev(returns)
    else:
        std_ret = 0.0
    ann_vol = std_ret * math.sqrt(periods_per_year)

    mean_excess = sum(excess) / len(excess)
    sharpe = (mean_excess / std_ret) * math.sqrt(periods_per_year) if std_ret > 1e-12 else 0.0

    downside_sq = [min(0.0, r - rf_per_period) ** 2 for r in returns]
    downside_dev = math.sqrt(sum(downside_sq) / len(downside_sq))
    sortino = (
        (mean_excess / downside_dev) * math.sqrt(periods_per_year)
        if downside_dev > 1e-12
        else 0.0
    )

    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns:
        equity *= 1.0 + r
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    return {
        "annualized_return": round(ann_return * 100.0, 4),
        "annualized_volatility": round(ann_vol * 100.0, 4),
        "sharpe_ratio": round(sharpe, 4),
        "sortino_ratio": round(sortino, 4),
        "max_drawdown_pct": round(max_dd * 100.0, 4),
    }


def optimize_conviction_weights(
    llm_convictions: Dict[str, float],
    volatilities: Dict[str, float],
    max_weight: float = 0.25,
) -> Dict[str, float]:
    """
    Combine LLM conviction scores [0..100] with inverse-volatility scaling
    and enforce a per-asset maximum weight cap via iterative water-filling.
    Returns normalized weights summing to 1.0 (or empty dict if no positive signal).
    """
    if not llm_convictions:
        return {}
    if max_weight <= 0 or max_weight > 1.0:
        raise ValueError("max_weight must be in (0, 1]")

    raw_scores: Dict[str, float] = {}
    for ticker, score in llm_convictions.items():
        s = max(0.0, float(score))
        if s <= 0:
            continue
        vol = max(0.5, float(volatilities.get(ticker, 20.0)))
        raw_scores[ticker] = s / vol

    total_raw = sum(raw_scores.values())
    if total_raw <= 0:
        return {}

    weights = {t: val / total_raw for t, val in raw_scores.items()}

    # Iterative cap-and-redistribute (up to len(weights) passes)
    capped: set[str] = set()
    for _ in range(len(weights)):
        over = [t for t, w in weights.items() if t not in capped and w > max_weight + 1e-9]
        if not over:
            break
        for t in over:
            weights[t] = max_weight
            capped.add(t)
        remaining_budget = 1.0 - sum(weights[t] for t in capped)
        uncapped = [t for t in weights if t not in capped]
        uncapped_sum = sum(weights[t] for t in uncapped)
        if remaining_budget <= 0 or uncapped_sum <= 0:
            break
        for t in uncapped:
            weights[t] = (weights[t] / uncapped_sum) * remaining_budget

    # Final normalization if cap * N >= 1.0
    total_w = sum(weights.values())
    if total_w > 0 and abs(total_w - 1.0) > 1e-6 and len(weights) * max_weight >= 1.0:
        weights = {t: w / total_w for t, w in weights.items()}

    return {t: round(w, 6) for t, w in weights.items()}


def compute_rebalance_orders(
    portfolio_equity: float,
    current_positions: Dict[str, float],
    target_weights: Dict[str, float],
    latest_prices: Dict[str, float],
    min_trade_notional: float = 25.0,
) -> List[Dict[str, object]]:
    """
    Compute whole-share SELL and BUY rebalance orders needed to transition
    from `current_positions` (market value per ticker) to `target_weights`.
    SELL orders are ordered first so cash is freed before BUY execution.
    """
    if portfolio_equity <= 0:
        return []

    all_tickers = sorted(set(current_positions.keys()) | set(target_weights.keys()))
    sells: List[Dict[str, object]] = []
    buys: List[Dict[str, object]] = []

    for ticker in all_tickers:
        price = float(latest_prices.get(ticker, 0.0))
        if price <= 0:
            continue
        curr_val = float(current_positions.get(ticker, 0.0))
        target_val = float(target_weights.get(ticker, 0.0)) * portfolio_equity
        delta_val = target_val - curr_val
        if abs(delta_val) < min_trade_notional:
            continue
        shares = int(abs(delta_val) // price)
        if shares <= 0:
            continue
        order = {
            "ticker": ticker,
            "side": "BUY" if delta_val > 0 else "SELL",
            "qty": shares,
            "estimated_notional": round(shares * price, 2),
        }
        if delta_val < 0:
            sells.append(order)
        else:
            buys.append(order)

    return sells + buys
