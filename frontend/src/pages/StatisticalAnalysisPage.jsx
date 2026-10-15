import { useState, useEffect, useMemo } from 'react';
import {
  BarChart, Bar, Cell, LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ReferenceLine, ResponsiveContainer
} from 'recharts';
import { getPerformanceSummary, getTreasuryRate } from '../api';

const pct = (value, decimals = 2, sign = false) => {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const formatted = `${(value * 100).toFixed(decimals)}%`;
  return sign && value >= 0 ? `+${formatted}` : formatted;
};

const num = (value, decimals = 3, sign = false) => {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const formatted = value.toFixed(decimals);
  return sign && value >= 0 ? `+${formatted}` : formatted;
};

// Dates arrive as plain "YYYY-MM-DD". Passing that to new Date() parses it as UTC
// midnight, which lands on the previous day in western timezones.
const parseDay = (value) => {
  if (!value) return null;
  const [y, m, d] = String(value).slice(0, 10).split('-').map(Number);
  return Number.isFinite(y) ? new Date(y, m - 1, d) : null;
};

const shortDate = (value) => {
  const d = parseDay(value);
  return d ? d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '';
};

const longDate = (value) => {
  const d = parseDay(value);
  return d ? d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '';
};

const deltaClass = (value, goodWhenPositive = true) => {
  if (value === null || value === undefined || Number.isNaN(value)) return '';
  const good = goodWhenPositive ? value >= 0 : value <= 0;
  return good ? 'positive' : 'negative';
};

const diff = (a, b) => {
  if (a === null || a === undefined || b === null || b === undefined) return null;
  return a - b;
};

export default function StatisticalAnalysisPage() {
  const [performanceData, setPerformanceData] = useState(null);
  const [treasuryRate, setTreasuryRate] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [chartTab, setChartTab] = useState('weekly');

  useEffect(() => {
    loadPerformanceData();
  }, []);

  const loadPerformanceData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [treasuryData, summary] = await Promise.all([
        getTreasuryRate(),
        getPerformanceSummary({})
      ]);
      setTreasuryRate(treasuryData);
      setPerformanceData(summary);
    } catch (err) {
      console.error('Error loading performance data:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const weeklySeries = performanceData?.weekly_series ?? [];

  const chartData = useMemo(() => {
    let compounded = 1;
    return weeklySeries.map((week) => {
      const oz = week.portfolio_return ?? 0;
      const spy = week.benchmark_return ?? 0;
      compounded *= (1 + oz) / (1 + spy);
      return {
        date: week.date,
        label: shortDate(week.date),
        delta: (week.excess_return ?? 0) * 100,
        oz: oz * 100,
        spy: spy * 100,
        cumulative: (compounded - 1) * 100
      };
    });
  }, [weeklySeries]);

  if (loading) {
    return (
      <div className="performance-report">
        <div className="loading-spinner">
          <div className="spinner"></div>
          <p>Loading performance statistics...</p>
        </div>
      </div>
    );
  }

  if (error || !performanceData) {
    return (
      <div className="performance-report">
        <div className="error-message">
          <h2>Could not load performance data</h2>
          <p>{error || 'No statistics were returned by the API.'}</p>
          <button onClick={loadPerformanceData} className="btn btn-primary">
            Try again
          </button>
        </div>
      </div>
    );
  }

  const daily = performanceData.daily_returns ?? {};
  const weekly = performanceData.weekly_returns ?? {};
  const cumulative = performanceData.cumulative_performance ?? {};
  const risk = performanceData.risk ?? {};
  const tests = performanceData.statistical_tests?.weekly ?? {};
  const dailyTests = performanceData.statistical_tests?.daily ?? {};
  const period = performanceData.period ?? {};

  const weeksCount = period.weeks ?? weeklySeries.length;
  const winRate = performanceData.win_rate_weekly ?? performanceData.win_rate;
  const winWeeks = winRate != null ? Math.round(winRate * weeksCount) : null;
  const pValue = tests.p_value;
  const pBoot = tests.p_value_bootstrap;
  const ci = tests.bootstrap_ci ?? [];
  const outperf = cumulative.outperformance_compounded ?? cumulative.outperformance;
  const significant = pValue != null && pValue <= 0.05;

  const sharpeDelta = diff(daily.portfolio?.sharpe_annualized, daily.benchmark?.sharpe_annualized);
  const mddDelta = diff(daily.portfolio?.max_drawdown, daily.benchmark?.max_drawdown);

  const CustomTooltip = ({ active, payload }) => {
    if (!active || !payload?.length) return null;
    const point = payload[0].payload;
    return (
      <div className="chart-tooltip">
        <div className="chart-tooltip-title">Week of {longDate(point.date)}</div>
        <div className="chart-tooltip-row">
          <span>Oracle Zero</span><strong>{point.oz.toFixed(2)}%</strong>
        </div>
        <div className="chart-tooltip-row">
          <span>SPY</span><strong>{point.spy.toFixed(2)}%</strong>
        </div>
        <div className="chart-tooltip-row">
          <span>Delta</span>
          <strong className={point.delta >= 0 ? 'text-success' : 'text-danger'}>
            {point.delta >= 0 ? '+' : ''}{point.delta.toFixed(2)} pp
          </strong>
        </div>
        {chartTab === 'cumulative' && (
          <div className="chart-tooltip-row">
            <span>Running gap</span>
            <strong className={point.cumulative >= 0 ? 'text-success' : 'text-danger'}>
              {point.cumulative >= 0 ? '+' : ''}{point.cumulative.toFixed(2)}%
            </strong>
          </div>
        )}
      </div>
    );
  };

  return (
    <div>
      <header className="page-header">
        <div className="page-header-text">
          <p className="page-eyebrow">Oracle Zero vs SPY</p>
          <h1>Statistics</h1>
          <p className="page-desc">
            {weeksCount} weeks against the benchmark, and whether the difference means
            anything.
          </p>
        </div>
      </header>

      <div className="disclaimer">
        <p>
          <strong>Disclaimer:</strong> {weeksCount} weeks of data, ending{' '}
          {longDate(period.end)}. Too short a sample to say anything about long-term
          performance.
        </p>
      </div>

      {/* ---------------------------------------------------- the numbers --- */}
      <div className="card mb-lg">
        <div className="card-header">
          <h2 className="card-title">Returns and risk</h2>
          <span className="text-sm text-muted">
            Risk-free rate {treasuryRate ? `${treasuryRate.treasury_rate_percent.toFixed(2)}%` : '—'} (3-month Treasury, period average)
          </span>
        </div>
        <div className="table-container">
          <table className="performance-table">
            <thead>
              <tr>
                <th>Metric</th>
                <th>SPY</th>
                <th>Oracle Zero</th>
                <th>Delta</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="metric-name">
                  <div className="metric-title">Cumulative return</div>
                  <div className="metric-desc">Since August 25, 2025</div>
                </td>
                <td className="spy-value">{pct(cumulative.benchmark, 2, true)}</td>
                <td className="oz-value">{pct(cumulative.portfolio, 2, true)}</td>
                <td className={`delta-value ${deltaClass(outperf)}`}>{pct(outperf, 2, true)}</td>
              </tr>
              <tr>
                <td className="metric-name">
                  <div className="metric-title">Weekly return</div>
                  <div className="metric-desc">Average week ± volatility</div>
                </td>
                <td className="spy-value">
                  {pct(weekly.benchmark?.mean, 2, true)} ± {pct(weekly.benchmark?.std, 2)}
                </td>
                <td className="oz-value">
                  {pct(weekly.portfolio?.mean, 2, true)} ± {pct(weekly.portfolio?.std, 2)}
                </td>
                <td className={`delta-value ${deltaClass(weekly.excess?.mean)}`}>
                  {pct(weekly.excess?.mean, 3, true)}
                </td>
              </tr>
              <tr>
                <td className="metric-name">
                  <div className="metric-title">Daily return</div>
                  <div className="metric-desc">Per trading day</div>
                </td>
                <td className="spy-value">
                  {pct(daily.benchmark?.mean, 3, true)} ± {pct(daily.benchmark?.std, 2)}
                </td>
                <td className="oz-value">
                  {pct(daily.portfolio?.mean, 3, true)} ± {pct(daily.portfolio?.std, 2)}
                </td>
                <td className={`delta-value ${deltaClass(daily.excess?.mean)}`}>
                  {pct(daily.excess?.mean, 3, true)}
                </td>
              </tr>
              <tr>
                <td className="metric-name">
                  <div className="metric-title">Sharpe ratio</div>
                  <div className="metric-desc">Return per unit of risk, annualized</div>
                </td>
                <td className="spy-value">{num(daily.benchmark?.sharpe_annualized, 2, true)}</td>
                <td className="oz-value">{num(daily.portfolio?.sharpe_annualized, 2, true)}</td>
                <td className={`delta-value ${deltaClass(sharpeDelta)}`}>{num(sharpeDelta, 2, true)}</td>
              </tr>
              <tr>
                <td className="metric-name">
                  <div className="metric-title">Max drawdown</div>
                  <div className="metric-desc">Deepest peak-to-trough fall</div>
                </td>
                <td className="spy-value">{pct(daily.benchmark?.max_drawdown, 2)}</td>
                <td className="oz-value">{pct(daily.portfolio?.max_drawdown, 2)}</td>
                <td className={`delta-value ${deltaClass(mddDelta, false)}`}>{pct(mddDelta, 2, true)}</td>
              </tr>
              <tr>
                <td className="metric-name">
                  <div className="metric-title">Beta</div>
                  <div className="metric-desc">Move per 1% move in SPY</div>
                </td>
                <td className="spy-value">1.00</td>
                <td className="oz-value">{num(risk.beta, 2)}</td>
                <td className="delta-value">{num(diff(risk.beta, 1), 2, true)}</td>
              </tr>
              <tr>
                <td className="metric-name">
                  <div className="metric-title">Alpha</div>
                  <div className="metric-desc">Annualized return beyond what beta explains</div>
                </td>
                <td className="spy-value">—</td>
                <td className="oz-value">{pct(risk.alpha_annualized, 2, true)}</td>
                <td className={`delta-value ${deltaClass(risk.alpha_annualized)}`}>
                  {pct(risk.alpha_annualized, 2, true)}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* ------------------------------------------------ is it for real? --- */}
      <div className="card mb-lg">
        <div className="card-header">
          <h2 className="card-title">Is the difference real?</h2>
          <span className={`pill ${significant ? 'pill-success' : ''}`}>
            {significant ? 'Significant at 5%' : 'Not significant'}
          </span>
        </div>
        <p className="section-explanation">
          Every test asks the same one-sided question: is the average weekly edge over SPY
          greater than zero, or is it noise?
        </p>
        <div className="table-container">
          <table className="performance-table">
            <thead>
              <tr>
                <th>Test</th>
                <th>Value</th>
                <th>What it means</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="metric-name">
                  <div className="metric-title">Mean weekly edge</div>
                  <div className="metric-desc">Oracle Zero minus SPY, per week</div>
                </td>
                <td className={`oz-value ${deltaClass(weekly.excess?.mean)}`}>
                  {pct(weekly.excess?.mean, 3, true)}
                </td>
                <td className="stat-read">What every row below tests.</td>
              </tr>
              <tr>
                <td className="metric-name">
                  <div className="metric-title">t-statistic</div>
                  <div className="metric-desc">Edge divided by its standard error</div>
                </td>
                <td className="oz-value">{num(tests.t_statistic, 3, true)}</td>
                <td className="stat-read">±2 is roughly where a result starts to look unusual.</td>
              </tr>
              <tr>
                <td className="metric-name">
                  <div className="metric-title">p-value (t-test)</div>
                  <div className="metric-desc">One-sided, {tests.degrees_freedom ?? '—'} degrees of freedom</div>
                </td>
                <td className={`oz-value ${significant ? 'positive' : ''}`}>{num(pValue, 3)}</td>
                <td className="stat-read">
                  Odds of an edge this large from a strategy with none. Below 0.05 is the bar.
                </td>
              </tr>
              <tr>
                <td className="metric-name">
                  <div className="metric-title">p-value (bootstrap)</div>
                  <div className="metric-desc">
                    {(performanceData.statistical_tests?.bootstrap_iterations ?? 10000).toLocaleString()} resamples
                    under the null
                  </div>
                </td>
                <td className="oz-value">{num(pBoot, 3)}</td>
                <td className="stat-read">
                  Same question, no normality assumed. It agrees with the t-test.
                </td>
              </tr>
              <tr>
                <td className="metric-name">
                  <div className="metric-title">95% confidence interval</div>
                  <div className="metric-desc">Plausible range for the true edge</div>
                </td>
                <td className="oz-value">
                  [{pct(ci[0], 3, true)}, {pct(ci[1], 3, true)}]
                </td>
                <td className="stat-read">
                  {ci[0] != null && ci[1] != null && ci[0] < 0 && ci[1] > 0
                    ? 'Straddles zero, so no edge is consistent with the data.'
                    : 'Sits entirely on one side of zero.'}
                </td>
              </tr>
              <tr>
                <td className="metric-name">
                  <div className="metric-title">Win rate</div>
                  <div className="metric-desc">Weeks finishing ahead of SPY</div>
                </td>
                <td className={`oz-value ${deltaClass((winRate ?? 0) - 0.5)}`}>
                  {pct(winRate, 1)}
                </td>
                <td className="stat-read">
                  {winWeeks != null ? `${winWeeks} of ${weeksCount} weeks. ` : ''}
                  A coin flip sits at 50%.
                </td>
              </tr>
              <tr>
                <td className="metric-name">
                  <div className="metric-title">Information ratio</div>
                  <div className="metric-desc">Annualized edge per unit of tracking error</div>
                </td>
                <td className={`oz-value ${deltaClass(weekly.excess?.information_ratio_annualized)}`}>
                  {num(weekly.excess?.information_ratio_annualized, 2, true)}
                </td>
                <td className="stat-read">Payoff for deviating from the index at all.</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div className="pvalue-disclaimer">
          <p>
            <strong>On reading these:</strong> a p-value above 0.05 does not prove the two
            are identical, only that {weeksCount} weeks is not enough data to tell them apart.
          </p>
        </div>
      </div>

      {/* ------------------------------------------------- weekly deltas --- */}
      <div className="card mb-lg">
        <div className="card-header">
          <h2 className="card-title">Weekly deltas</h2>
        </div>
        <p className="section-explanation">
          Each bar is one week of Oracle Zero minus SPY, in percentage points. Purple beat
          the index, red lagged it.
        </p>

        <div className="chart-tabs">
          <button
            className={`chart-tab ${chartTab === 'weekly' ? 'active' : ''}`}
            onClick={() => setChartTab('weekly')}
          >
            Week by week
          </button>
          <button
            className={`chart-tab ${chartTab === 'cumulative' ? 'active' : ''}`}
            onClick={() => setChartTab('cumulative')}
          >
            Running gap
          </button>
        </div>

        {chartData.length === 0 ? (
          <p className="text-muted text-center py-xl">No weekly data available.</p>
        ) : chartTab === 'weekly' ? (
          <ResponsiveContainer width="100%" height={360}>
            <BarChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
              <XAxis
                dataKey="label"
                stroke="var(--muted)"
                tick={{ fontSize: 11 }}
                tickMargin={10}
                interval={Math.max(0, Math.ceil(chartData.length / 9) - 1)}
              />
              <YAxis
                stroke="var(--muted)"
                tick={{ fontSize: 11 }}
                tickMargin={8}
                width={56}
                tickFormatter={(v) => `${v.toFixed(1)}pp`}
              />
              <Tooltip content={<CustomTooltip />} cursor={{ fill: 'var(--surface-2)' }} />
              <ReferenceLine y={0} stroke="var(--border-strong)" />
              <Bar dataKey="delta" radius={[2, 2, 2, 2]}>
                {chartData.map((point) => (
                  <Cell
                    key={point.date}
                    fill={point.delta >= 0 ? 'var(--primary)' : 'var(--danger)'}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <ResponsiveContainer width="100%" height={360}>
            <LineChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
              <XAxis
                dataKey="label"
                stroke="var(--muted)"
                tick={{ fontSize: 11 }}
                tickMargin={10}
                interval={Math.max(0, Math.ceil(chartData.length / 9) - 1)}
              />
              <YAxis
                stroke="var(--muted)"
                tick={{ fontSize: 11 }}
                tickMargin={8}
                width={56}
                tickFormatter={(v) => `${v.toFixed(1)}%`}
              />
              <Tooltip content={<CustomTooltip />} />
              <ReferenceLine y={0} stroke="var(--border-strong)" />
              <Line
                type="monotone"
                dataKey="cumulative"
                stroke="var(--primary)"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}

        <p className="chart-note">
          {chartTab === 'weekly'
            ? `Largest single-week gain over SPY: ${num(Math.max(...chartData.map((d) => d.delta)), 2, true)} pp. Largest shortfall: ${num(Math.min(...chartData.map((d) => d.delta)), 2, true)} pp.`
            : 'The compounded gap, week by week. It ends where the cumulative delta in the first table does.'}
        </p>
      </div>

      {/* ------------------------------------------------------ takeaways --- */}
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Takeaways</h2>
        </div>
        <div className="learn-list">
          <div className="learn-item">
            <div className="learn-num">01</div>
            <div>
              <h3 className="learn-title">It tracked the index rather than beating it</h3>
              <p className="learn-text">
                {pct(cumulative.portfolio, 2, true)} against SPY's {pct(cumulative.benchmark, 2, true)} over{' '}
                {weeksCount} weeks. That is a gap of {pct(outperf, 2, true)}, or about{' '}
                {pct(weekly.excess?.mean, 3, true)} per week.
              </p>
            </div>
          </div>
          <div className="learn-item">
            <div className="learn-num">02</div>
            <div>
              <h3 className="learn-title">That gap is indistinguishable from noise</h3>
              <p className="learn-text">
                The t-test gives p = {num(pValue, 3)}, the bootstrap p = {num(pBoot, 3)}. Two methods,
                one answer, and the 95% interval [{pct(ci[0], 3, true)}, {pct(ci[1], 3, true)}] contains zero.
              </p>
            </div>
          </div>
          <div className="learn-item">
            <div className="learn-num">03</div>
            <div>
              <h3 className="learn-title">The risk profile matched too</h3>
              <p className="learn-text">
                Beta {num(risk.beta, 2)}, Sharpe {num(daily.portfolio?.sharpe_annualized, 2)} against SPY's{' '}
                {num(daily.benchmark?.sharpe_annualized, 2)}, drawdown {pct(daily.portfolio?.max_drawdown, 2)} versus{' '}
                {pct(daily.benchmark?.max_drawdown, 2)}. It matched the index on the way there as well as
                at the end.
              </p>
            </div>
          </div>
          <div className="learn-item">
            <div className="learn-num">04</div>
            <div>
              <h3 className="learn-title">What these numbers actually grade</h3>
              <p className="learn-text">
                The account rebalanced to market-cap weights; the model's weights were recorded
                but never traded. Landing within a fraction of a percent of SPY is the expected
                result, and it is what happened.
              </p>
            </div>
          </div>
          <div className="learn-item">
            <div className="learn-num">05</div>
            <div>
              <h3 className="learn-title">What this cannot tell you</h3>
              <p className="learn-text">
                At {pct(weekly.excess?.std, 2)} weekly tracking error, an edge worth 1% a year would take
                over a decade to separate from noise. Returns also come from total equity, which
                does not net out deposits.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
