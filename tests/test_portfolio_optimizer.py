import os
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from portfolio_optimizer import (
    compute_active_share,
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

    # Symmetric -50% then +50% yields 0.75x equity (-25% geometric return)
    drag = compute_sharpe_and_sortino([-0.5, 0.5], risk_free_annual=0.0, periods_per_year=2)
    assert drag["annualized_return"] == pytest.approx(-25.0, abs=1e-4)


def test_compute_sharpe_empty_and_active_share():
    empty = compute_sharpe_and_sortino([])
    assert empty["sharpe_ratio"] == 0.0
    assert empty["max_drawdown_pct"] == 0.0

    assert compute_active_share({"AAPL": 0.6, "MSFT": 0.4}, {"AAPL": 0.6, "MSFT": 0.4}) == 0.0
    assert compute_active_share({"AAPL": 1.0}, {"NVDA": 1.0}) == 1.0
    assert compute_active_share({"AAPL": 0.5, "MSFT": 0.5}, {"AAPL": 0.25, "MSFT": 0.25, "GOOGL": 0.5}) == 0.5


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
    # When N * max_weight < 1.0 (e.g. 2 tickers with max_weight=0.25), relaxes cap to 1/N so weights sum to 1.0
    two_asset = optimize_conviction_weights({"AAPL": 90.0, "MSFT": 60.0}, {"AAPL": 20.0, "MSFT": 20.0}, max_weight=0.25)
    assert pytest.approx(sum(two_asset.values()), abs=1e-5) == 1.0
    assert two_asset == {"AAPL": 0.5, "MSFT": 0.5}
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

from backend.portfolio_optimizer import compute_max_drawdown_and_calmar


def test_compute_max_drawdown_and_calmar():
    prices = [100.0, 110.0, 99.0, 105.0, 120.0]
    res = compute_max_drawdown_and_calmar(prices, periods_per_year=4)
    assert abs(res["max_drawdown"] - 0.10) < 1e-6
    assert abs(res["annualized_return"] - 0.20) < 1e-6
    assert abs(res["calmar_ratio"] - 2.0) < 1e-4
