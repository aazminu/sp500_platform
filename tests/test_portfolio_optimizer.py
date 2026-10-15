import os
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from portfolio_optimizer import (
    compute_rebalance_orders,
    compute_returns_from_prices,
    compute_sharpe_and_sortino,
    optimize_conviction_weights,
)


def test_compute_returns_and_risk_metrics():
    prices = [100.0, 102.0, 101.0, 105.0, 108.0, 106.0, 110.0]
    rets = compute_returns_from_prices(prices)
    assert len(rets) == 6
    assert pytest.approx(rets[0], rel=1e-6) == 0.02

    metrics = compute_sharpe_and_sortino(rets, risk_free_annual=0.04)
    assert metrics["annualized_return"] > 0
    assert metrics["annualized_volatility"] > 0
    assert metrics["sharpe_ratio"] > 0
    assert metrics["sortino_ratio"] > 0
    assert 0 < metrics["max_drawdown_pct"] < 5.0


def test_compute_sharpe_empty_and_single():
    empty = compute_sharpe_and_sortino([])
    assert empty["sharpe_ratio"] == 0.0
    assert empty["max_drawdown_pct"] == 0.0


def test_optimize_conviction_weights_respects_cap_and_normalizes():
    convictions = {"NVDA": 95.0, "MSFT": 80.0, "AAPL": 75.0, "GOOGL": 70.0, "AMZN": 65.0}
    vols = {"NVDA": 35.0, "MSFT": 18.0, "AAPL": 20.0, "GOOGL": 22.0, "AMZN": 25.0}
    weights = optimize_conviction_weights(convictions, vols, max_weight=0.30)

    assert len(weights) == 5
    assert pytest.approx(sum(weights.values()), abs=1e-4) == 1.0
    for w in weights.values():
        assert w <= 0.300001
    # MSFT has higher conviction/vol ratio than NVDA due to lower volatility
    assert weights["MSFT"] > weights["NVDA"]


def test_optimize_conviction_weights_edge_cases():
    assert optimize_conviction_weights({}, {}) == {}
    assert optimize_conviction_weights({"AAPL": 0.0, "TSLA": -5.0}, {}) == {}
    with pytest.raises(ValueError):
        optimize_conviction_weights({"AAPL": 80}, {}, max_weight=0.0)


def test_compute_rebalance_orders_orders_sells_before_buys():
    orders = compute_rebalance_orders(
        portfolio_equity=10000.0,
        current_positions={"AAPL": 4000.0, "MSFT": 1000.0},
        target_weights={"AAPL": 0.20, "MSFT": 0.50, "NVDA": 0.30},
        latest_prices={"AAPL": 200.0, "MSFT": 400.0, "NVDA": 120.0},
        min_trade_notional=50.0,
    )
    assert [o["side"] for o in orders] == ["SELL", "BUY", "BUY"]
    assert orders[0] == {"ticker": "AAPL", "side": "SELL", "qty": 10, "estimated_notional": 2000.0}
    assert orders[1] == {"ticker": "MSFT", "side": "BUY", "qty": 10, "estimated_notional": 4000.0}
    assert orders[2] == {"ticker": "NVDA", "side": "BUY", "qty": 25, "estimated_notional": 3000.0}
