import React, { useState, useEffect } from 'react';
import { getHistory } from '../api';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

// The experiment ended on 2026-08-24. These are the final full-year allocation moves,
// measured once against the allocations table and frozen here rather than recomputed,
// the underlying window cannot change any more.
const WINDOW = { start: '2025-08-25', end: '2026-08-24' };
const INDEX_GROWTH_PCT = 22.1;   // total S&P 500 market cap, $60.3T -> $73.7T

const ALLOCATION_MOVES = [
  {
    ticker: 'GOOGL / GOOG', name: 'Alphabet', sector: 'Communication Services',
    startPct: 8.379, endPct: 11.579, deltaPp: 3.199,
    capStartB: 2527.3, capEndB: 4264.0, capChgPct: 68.7,
    verdicts: 'Increase ×85, Hold ×17',
    why: 'Grew three times faster than the index. Both share classes carry the same weight, so Alphabet\'s combined share of the portfolio went from 8.4% to 11.6%, the single largest shift of the year.',
  },
  {
    ticker: 'MSFT', name: 'Microsoft', sector: 'Technology',
    startPct: 6.213, endPct: 4.936, deltaPp: -1.277,
    capStartB: 3748.2, capEndB: 3635.5, capChgPct: -3.0,
    verdicts: 'Hold ×26, Increase ×24',
    why: 'The only megacap to shrink outright while the index added 22%. It lost ground twice over: down in absolute terms, and further down relative to everything around it.',
  },
  {
    ticker: 'META', name: 'Meta Platforms', sector: 'Communication Services',
    startPct: 3.144, endPct: 1.919, deltaPp: -1.226,
    capStartB: 1896.8, capEndB: 1413.2, capChgPct: -25.5,
    verdicts: 'Hold ×32, Increase ×18, Decrease ×2',
    why: 'Lost a quarter of its market value, the biggest weight decline that came from an actual fall in the stock rather than from being outgrown.',
  },
  {
    ticker: 'MU', name: 'Micron Technology', sector: 'Technology',
    startPct: 0.216, endPct: 1.398, deltaPp: 1.183,
    capStartB: 130.2, capEndB: 1029.9, capChgPct: 691.3,
    verdicts: 'Increase ×46, Hold ×6',
    why: 'From $130B to over $1T, the largest cap expansion in the index by a wide margin. It went from a rounding error in the portfolio to a full percentage point.',
  },
  {
    ticker: 'AAPL', name: 'Apple', sector: 'Technology',
    startPct: 5.612, endPct: 6.218, deltaPp: 0.606,
    capStartB: 3385.3, capEndB: 4579.5, capChgPct: 35.3,
    verdicts: 'Increase ×36, Hold ×13',
    why: 'Grew about half again as fast as the index. No dramatic move, just steady outpacing, which is enough to add weight in a cap-weighted portfolio.',
  },
  {
    ticker: 'AMD', name: 'Advanced Micro Devices', sector: 'Technology',
    startPct: 0.440, endPct: 1.021, deltaPp: 0.581,
    capStartB: 265.1, capEndB: 751.9, capChgPct: 183.6,
    verdicts: 'Increase ×43, Hold ×9',
    why: 'Nearly tripled, crossing 1% of the portfolio. One of five semiconductor names in this table.',
  },
  {
    ticker: 'ORCL', name: 'Oracle', sector: 'Technology',
    startPct: 1.095, endPct: 0.562, deltaPp: -0.533,
    capStartB: 660.3, capEndB: 413.8, capChgPct: -37.3,
    verdicts: 'Hold ×32, Increase ×19, Decrease ×1',
    why: 'Gave back the AI-infrastructure premium it was carrying at the start of the window, losing over a third of its market cap and half its weight.',
  },
  {
    ticker: 'LLY', name: 'Eli Lilly', sector: 'Healthcare',
    startPct: 1.035, endPct: 1.507, deltaPp: 0.472,
    capStartB: 624.3, capEndB: 1109.8, capChgPct: 77.8,
    verdicts: 'Increase ×39, Hold ×12',
    why: 'The only non-technology name among the year\'s biggest movers, and the only one that crossed $1T without a semiconductor story behind it.',
  },
  {
    ticker: 'INTC', name: 'Intel', sector: 'Technology',
    startPct: 0.178, endPct: 0.605, deltaPp: 0.427,
    capStartB: 107.3, capEndB: 445.6, capChgPct: 315.4,
    verdicts: 'Increase ×42, Hold ×8',
    why: 'More than quadrupled off a low base. Even after that run it finished the year under 1% of the portfolio, which is how far it had fallen beforehand.',
  },
  {
    ticker: 'NFLX', name: 'Netflix', sector: 'Communication Services',
    startPct: 0.859, endPct: 0.456, deltaPp: -0.403,
    capStartB: 517.9, capEndB: 335.8, capChgPct: -35.2,
    verdicts: 'Hold ×31, Increase ×12, Add ×6',
    why: 'Down about a third. Read the market cap rather than the share price here, because Netflix split its stock inside this window and the raw price change looks far worse than the business did.',
  },
  {
    ticker: 'NVDA', name: 'Nvidia', sector: 'Technology',
    startPct: 7.263, endPct: 6.936, deltaPp: -0.327,
    capStartB: 4381.3, capEndB: 5108.8, capChgPct: 16.6,
    verdicts: 'Increase ×45, Hold ×7',
    why: 'The instructive one. Nvidia grew 16.6% and still lost weight, because the index grew 22.1%. In a cap-weighted portfolio you give up ground by growing slower than everyone else, even without shrinking.',
  },
  {
    ticker: 'LRCX', name: 'Lam Research', sector: 'Technology',
    startPct: 0.214, endPct: 0.523, deltaPp: 0.309,
    capStartB: 129.1, capEndB: 385.1, capChgPct: 198.4,
    verdicts: 'Increase ×50, Hold ×2',
    why: 'Semiconductor equipment, up roughly threefold on the same wave that carried Micron and AMD.',
  },
  {
    ticker: 'AMAT', name: 'Applied Materials', sector: 'Technology',
    startPct: 0.217, endPct: 0.521, deltaPp: 0.304,
    capStartB: 130.7, capEndB: 383.5, capChgPct: 193.4,
    verdicts: 'Increase ×43, Hold ×8',
    why: 'Moved almost in lockstep with Lam Research: same industry, near-identical gain, ending within 0.01% of the same weight.',
  },
];

const History = () => {
  const [historyData, setHistoryData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [timeframe, setTimeframe] = useState('ytd');

  const fetchData = async () => {
    try {
      setLoading(true);
      const history = await getHistory(timeframe);
      setHistoryData(history);
      setError(null);
    } catch (err) {
      setError('Failed to fetch history data');
      console.error('Error fetching history data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [timeframe]);

  const formatCurrency = (value) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0
    }).format(value);
  };

  const formatPercentage = (value) => {
    return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
  };

  const formatDate = (dateString) => {
    // A bare "YYYY-MM-DD" parses as UTC midnight, which reads as the previous day
    // in any timezone behind UTC, so build the date from its parts instead.
    const iso = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(dateString ?? ''));
    const date = iso
      ? new Date(Number(iso[1]), Number(iso[2]) - 1, Number(iso[3]))
      : new Date(dateString);
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric'
    });
  };

  const formatDateTime = (dateString) => {
    return new Date(dateString).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const getPLColor = (value) => {
    if (value > 0) return 'text-success';
    if (value < 0) return 'text-danger';
    return 'text-muted';
  };

  const formatCap = (billions) => {
    if (billions >= 1000) return `$${(billions / 1000).toFixed(2)}T`;
    return `$${Math.round(billions)}B`;
  };

  // Calculate timeframe-specific KPIs from chart data
  const calculateTimeframeKPIs = () => {
    if (!historyData?.history || historyData.history.length === 0) {
      return null;
    }

    const history = historyData.history;
    const startEquity = history[0].equity;
    const currentEquity = history[history.length - 1].equity;
    const pl = currentEquity - startEquity;
    const returnPercent = (pl / startEquity) * 100;

    return {
      start_equity: startEquity,
      current_equity: currentEquity,
      pl: pl,
      return_percent: returnPercent
    };
  };

  const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
      return (
        <div className="card" style={{ padding: 'var(--space-sm)', border: '1px solid var(--border)' }}>
          <p className="text-sm font-medium mb-xs">{formatDate(label)}</p>
          <p className="text-sm">
            Equity: {formatCurrency(payload[0].value)}
          </p>
        </div>
      );
    }
    return null;
  };

  if (loading && !historyData) {
    return (
      <div className="loading">
        <div className="spinner"></div>
        Loading history data...
      </div>
    );
  }

  if (error) {
    return (
      <div className="error">
        {error}
        <button onClick={fetchData} className="btn btn-primary mt-md">Retry</button>
      </div>
    );
  }

  return (
    <div>
      <header className="page-header">
        <div className="page-header-text">
          <p className="page-eyebrow">Paper account</p>
          <h1>History</h1>
          <p className="page-desc">
            Account equity over time, and the positions whose weight moved most across the
            full year.
          </p>
        </div>
        <div className="segmented-control">
          <button
            className={timeframe === 'all' ? 'active' : ''}
            onClick={() => setTimeframe('all')}
          >
            All Time
          </button>
          <button
            className={timeframe === 'ytd' ? 'active' : ''}
            onClick={() => setTimeframe('ytd')}
          >
            YTD
          </button>
          <button
            className={timeframe === '3m' ? 'active' : ''}
            onClick={() => setTimeframe('3m')}
          >
            3M
          </button>
          <button
            className={timeframe === '1m' ? 'active' : ''}
            onClick={() => setTimeframe('1m')}
          >
            1M
          </button>
          <button
            className={timeframe === '1w' ? 'active' : ''}
            onClick={() => setTimeframe('1w')}
          >
            1W
          </button>
        </div>
      </header>

      {/* Equity Chart */}
      <div className="card mb-lg">
        <h2 className="section-title">Equity performance</h2>
        {historyData?.history && historyData.history.length > 0 ? (
          <ResponsiveContainer width="100%" height={400}>
            <LineChart data={historyData.history}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                          <XAxis 
              dataKey="date" 
              tickFormatter={formatDate}
              interval="preserveStartEnd"
              stroke="var(--muted)"
              tick={{ fontSize: 12 }}
              tickMargin={10}
              minTickGap={50}
            />
            <YAxis 
              tickFormatter={formatCurrency}
              domain={['dataMin - 1000', 'dataMax + 1000']}
              stroke="var(--muted)"
              tick={{ fontSize: 12 }}
              tickMargin={10}
              width={80}
            />
              <Tooltip content={<CustomTooltip />} />
              <Line 
                type="monotone" 
                dataKey="equity" 
                stroke="var(--primary)" 
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 6, fill: 'var(--primary)' }}
              />
            </LineChart>
          </ResponsiveContainer>
                 ) : (
           <div className="text-center py-xl">
             <p className="text-muted">No chart data available</p>
             <p className="text-sm text-muted">History data: {JSON.stringify(historyData?.history)}</p>
             
             {/* Simple fallback chart with just current equity */}
             {historyData?.debug && (
               <div className="mt-md">
                 <h4 className="text-sm font-medium mb-sm">Simple Chart (Current Equity Only):</h4>
                 <div className="bg-light border rounded p-md">
                   <div className="text-2xl font-bold text-primary">
                     ${historyData.debug.real_current_equity?.toFixed(2)}
                   </div>
                   <p className="text-sm text-muted">Current Portfolio Value</p>
                 </div>
               </div>
             )}
             
             {historyData?.debug && (
               <div className="mt-md p-md bg-light border rounded">
                 <h4 className="text-sm font-medium mb-sm">Debug Info:</h4>
                 <div className="text-xs text-muted">
                   <p>Account Created: {historyData.debug.account_created}</p>
                   <p>Current Cash: ${historyData.debug.current_cash?.toFixed(2)}</p>
                   <p>Current Equity: ${historyData.debug.current_equity?.toFixed(2)}</p>
                   <p>Start Equity: ${historyData.debug.start_equity?.toFixed(2)}</p>
                   <p>End Equity: ${historyData.debug.end_equity?.toFixed(2)}</p>
                   <p>Real Current Equity: ${historyData.debug.real_current_equity?.toFixed(2)}</p>
                   <p>Start Date: {historyData.debug.start_date}</p>
                   <p>End Date: {historyData.debug.end_date}</p>
                   <p>Data Points: {historyData.debug.data_points}</p>
                 </div>
               </div>
             )}
           </div>
         )}
      </div>

      {/* KPI Row */}
      {historyData?.history && historyData.history.length > 0 && (() => {
        const timeframeKPIs = calculateTimeframeKPIs();
        return timeframeKPIs ? (
          <div className="grid grid-4 mb-xl">
            <div className="card">
              <p className="stat-label">Start equity</p>
              <div className="stat-value">{formatCurrency(timeframeKPIs.start_equity)}</div>
            </div>
            <div className="card">
              <p className="stat-label">Current equity</p>
              <div className="stat-value">{formatCurrency(timeframeKPIs.current_equity)}</div>
            </div>
            <div className="card">
              <p className="stat-label">P&L</p>
              <div className={`stat-value ${getPLColor(timeframeKPIs.pl)}`}>
                {formatCurrency(timeframeKPIs.pl)}
              </div>
            </div>
            <div className="card">
              <p className="stat-label">Return</p>
              <div className={`stat-value ${getPLColor(timeframeKPIs.return_percent)}`}>
                {formatPercentage(timeframeKPIs.return_percent)}
              </div>
            </div>
          </div>
        ) : null;
      })()}

      {/* Largest allocation changes over the full year */}
      <div className="card">
        <div className="tabs mb-lg">
          <ul className="tab-list">
            <li className="tab-item active">Largest allocation changes</li>
          </ul>
        </div>

        <p className="section-explanation">
          The thirteen positions whose portfolio weight moved most between{' '}
          {formatDate(WINDOW.start)} and {formatDate(WINDOW.end)}, the full length of the
          experiment. Weights are market-cap driven, so a position gains weight only by
          growing faster than the index did, and the index grew{' '}
          <strong>{INDEX_GROWTH_PCT}%</strong> over this window. That figure is the bar
          every row below is measured against.
        </p>

        <div className="table-container">
          <table className="performance-table">
            <thead>
              <tr>
                <th>Position</th>
                <th>Weight</th>
                <th>Change</th>
                <th>Market cap</th>
                <th>Model said</th>
              </tr>
            </thead>
            <tbody>
              {ALLOCATION_MOVES.map((move) => (
                <tr key={move.ticker}>
                  <td className="metric-name">
                    <div className="metric-title">
                      {move.ticker} <span className="move-company">{move.name}</span>
                    </div>
                    <div className="metric-desc">{move.why}</div>
                  </td>
                  <td className="spy-value">
                    {move.startPct.toFixed(2)}%
                    <span className="move-arrow">→</span>
                    {move.endPct.toFixed(2)}%
                  </td>
                  <td className={`delta-value ${move.deltaPp >= 0 ? 'positive' : 'negative'}`}>
                    {move.deltaPp >= 0 ? '+' : ''}{move.deltaPp.toFixed(2)} pp
                  </td>
                  <td className="oz-value">
                    <div>{formatCap(move.capStartB)} → {formatCap(move.capEndB)}</div>
                    <div className={`text-sm ${move.capChgPct >= INDEX_GROWTH_PCT ? 'text-success' : 'text-danger'}`}>
                      {move.capChgPct >= 0 ? '+' : ''}{move.capChgPct}%
                    </div>
                  </td>
                  <td className="stat-read">{move.verdicts}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default History;
