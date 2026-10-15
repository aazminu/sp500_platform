import { useState, useEffect } from 'react';
import { getPortfolioAnalysis } from '../api';

export default function PortfolioAnalysis() {
  const [portfolioData, setPortfolioData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchPortfolioAnalysis();
  }, []);

  const fetchPortfolioAnalysis = async ({ force = false } = {}) => {
    try {
      setLoading(true);
      setPortfolioData(await getPortfolioAnalysis({ force }));
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const formatCurrency = (amount) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0
    }).format(amount);
  };

  const formatNumber = (num) => {
    return new Intl.NumberFormat('en-US').format(num);
  };

  const getDifferenceColor = (difference) => {
    if (difference > 0) return 'text-success';
    if (difference < 0) return 'text-danger';
    return 'text-muted';
  };

  const getDifferenceIcon = (difference) => {
    if (difference > 0) return '↗';
    if (difference < 0) return '↘';
    return '→';
  };

  if (loading) {
    return (
      <div className="loading">
        <div className="spinner"></div>
        Loading portfolio analysis...
      </div>
    );
  }

  if (error) {
    return (
      <div className="error">
        <h3>Error Loading Portfolio Analysis</h3>
        <p>{error}</p>
        <button onClick={() => fetchPortfolioAnalysis({ force: true })} className="btn btn-primary mt-md">
          Retry
        </button>
      </div>
    );
  }

  if (!portfolioData) {
    return (
      <div className="text-center py-xl">
        <h3>No Portfolio Data Available</h3>
        <p className="text-muted">Unable to load portfolio analysis data.</p>
      </div>
    );
  }

  return (
    <div>
      <header className="page-header">
        <div className="page-header-text">
          <p className="page-eyebrow">Model vs market cap</p>
          <h1>Weight Analysis</h1>
          <p className="page-desc">
            The ten largest gaps between plain S&amp;P 500 market-cap weights and the weights
            the model asked for.
          </p>
        </div>
        <button onClick={() => fetchPortfolioAnalysis({ force: true })} className="btn btn-sm">
          Refresh
        </button>
      </header>

      <div className="grid grid-3 mb-xl">
        <div className="card">
          <p className="stat-label">Market-cap weight (top 10)</p>
          <div className="stat-value">{(portfolioData.summary.total_fmp_allocation * 100).toFixed(2)}%</div>
        </div>
        <div className="card">
          <p className="stat-label">Model weight (top 10)</p>
          <div className="stat-value">{(portfolioData.summary.total_llm_allocation * 100).toFixed(2)}%</div>
        </div>
        <div className="card">
          <p className="stat-label">Total difference</p>
          <div className={`stat-value ${getDifferenceColor(portfolioData.summary.total_difference)}`}>
            {getDifferenceIcon(portfolioData.summary.total_difference)} {(portfolioData.summary.total_difference * 100).toFixed(2)}%
          </div>
        </div>
      </div>

      <div className="card mb-lg">
        <div className="table-container">
          <table className="table table-compact w-full">
            <thead>
              <tr>
                <th>Rank</th>
                <th>Ticker</th>
                <th>Company</th>
                <th>Sector</th>
                <th>FMP Allocation</th>
                <th>LLM Allocation</th>
                <th>Difference</th>
                <th>% Diff</th>
                <th>FMP Date</th>
                <th>LLM Date</th>
              </tr>
            </thead>
            <tbody>
              {portfolioData.top_positions.map((position) => (
                <tr key={position.ticker}>
                  <td>
                    <span className="pill pill-primary">#{position.rank}</span>
                  </td>
                                     <td>
                     <span className={`font-semibold pill ${getDifferenceColor(position.allocation_difference) === 'text-success' ? 'pill-success' : getDifferenceColor(position.allocation_difference) === 'text-danger' ? 'pill-danger' : 'pill'}`}>
                       {position.ticker}
                     </span>
                   </td>
                  <td>{position.company_name}</td>
                  <td>{position.sector}</td>
                  <td>{(position.fmp_allocation_pct * 100).toFixed(4)}%</td>
                  <td>{(position.llm_allocation_pct * 100).toFixed(4)}%</td>
                  <td className={getDifferenceColor(position.allocation_difference)}>
                    {(position.allocation_difference * 100).toFixed(4)}%
                  </td>
                  <td className={getDifferenceColor(position.percentage_diff)}>
                    {position.percentage_diff > 0 ? '+' : ''}{position.percentage_diff.toFixed(2)}%
                  </td>
                  <td className="text-sm text-muted">
                    {position.allocation_date ? new Date(position.allocation_date).toLocaleDateString() : 'N/A'}
                  </td>
                  <td className="text-sm text-muted">
                    {position.llm_date ? new Date(position.llm_date).toLocaleDateString() : 'N/A'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h4 className="mb-md">Legend</h4>
        <div className="flex gap-lg flex-wrap">
          <div className="flex items-center gap-sm">
            <span className="pill pill-success font-semibold">AAPL</span>
            <span className="text-sm font-medium">LLM recommends higher allocation than FMP</span>
          </div>
          <div className="flex items-center gap-sm">
            <span className="pill pill-danger font-semibold">MSFT</span>
            <span className="text-sm font-medium">LLM recommends lower allocation than FMP</span>
          </div>
          <div className="flex items-center gap-sm">
            <span className="pill font-semibold">GOOGL</span>
            <span className="text-sm font-medium">No difference in recommendations</span>
          </div>
        </div>
      </div>
    </div>
  );
}
