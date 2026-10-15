import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { getAccountInfo, getPositions, getHistory, getPerformanceSummary } from '../api';

function money(value) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(value || 0);
}

function signedPct(value) {
  if (value == null || Number.isNaN(value)) return '—';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(1)}%`;
}

function pctClass(value) {
  if (value > 0) return 'text-success';
  if (value < 0) return 'text-danger';
  return 'text-muted';
}

// Mirrors the payload built in ingestion/fetch_weekly_llm.py:create_prompt_for_ticker
const PROMPT_FIELDS = [
  { k: 'ticker', v: '"AAPL"', t: 'str' },
  { k: 'snapshot', v: '"2026-08-17"', t: 'str', note: 'the week being priced' },
  { k: 'previous_allocation_pct', v: '620', t: 'num', note: 'basis points, so 6.20%' },
  { k: 'latest_price', v: '241.84', t: 'num' },
  { k: 'yearly_return_pct', v: '18.6', t: 'num' },
  { k: 'weekly_volatility', v: '0.0143', t: 'num', note: 'std dev of daily returns' },
  { k: 'weekly_avg_vol', v: '52831900', t: 'num', note: 'average share volume' },
  { k: 'pe_ratio', v: '34.2', t: 'num', indent: true },
  { k: 'market_cap', v: '3590000000000', t: 'num', indent: true },
  { k: 'debt_to_equity', v: '1.45', t: 'num', indent: true },
  { k: 'profile_summary', v: '"Apple Inc. designs, manufactures and markets smartphones..."', t: 'str', note: 'first sentence only' },
  { k: 'recent_news_headlines', v: '["Apple ships M5 MacBook Pro", "App Store revenue up 12%"]', t: 'str', note: 'max 2, truncated' },
];

function Field({ k, v, t, note, indent }) {
  return (
    <>
      {indent ? '    ' : '  '}
      <span className="tok-key">"{k}"</span>
      <span className="tok-punc">: </span>
      <span className={t === 'num' ? 'tok-num' : 'tok-str'}>{v}</span>
      <span className="tok-punc">,</span>
      {note && <span className="tok-note">{'  // ' + note}</span>}
      {'\n'}
    </>
  );
}

export default function PortfolioSnapshot() {
  const [account, setAccount] = useState(null);
  const [positions, setPositions] = useState([]);
  const [history, setHistory] = useState(null);
  const [perf, setPerf] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        setLoading(true);
        const [accountData, positionsData, historyData] = await Promise.all([
          getAccountInfo(),
          getPositions(),
          getHistory('all').catch(() => null),
        ]);
        if (cancelled) return;
        setAccount(accountData);
        setPositions(positionsData || []);
        setHistory(historyData);
        setError(null);
        setLoading(false);

        const perfData = await getPerformanceSummary({ boots: 200 }).catch(() => null);
        if (!cancelled) setPerf(perfData);
      } catch (err) {
        if (!cancelled) {
          setError('Could not load the paper account. Is the backend running?');
          setLoading(false);
        }
      }
    }

    load();
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return (
      <div className="loading">
        <div className="spinner"></div>
        Loading the experiment overview...
      </div>
    );
  }

  if (error) {
    return (
      <div className="error">
        {error}
      </div>
    );
  }

  const equity = account?.equity || 0;
  const cash = account?.cash || 0;
  const startEquity = history?.kpis?.start_equity;
  const totalReturn = history?.kpis?.ytd_return;
  const vsSpy = perf?.cumulative_performance?.outperformance != null
    ? perf.cumulative_performance.outperformance * 100
    : null;
  const spyReturn = perf?.cumulative_performance?.benchmark != null
    ? perf.cumulative_performance.benchmark * 100
    : null;

  const topHoldings = [...positions]
    .sort((a, b) => b.market_value - a.market_value)
    .slice(0, 8);
  const maxValue = topHoldings[0]?.market_value || 1;

  return (
    <div className="home-page">
      <header className="page-header">
        <div className="page-header-text">
          <p className="page-eyebrow">Paper trading · Aug 2025 – Aug 2026</p>
          <h1>Overview</h1>
        </div>
      </header>

      <p className="home-summary mb-xl">
        This was a paper-traded, weekly-rebalanced ETF built on the S&amp;P 500.
        Each week a language model looked at prices, news, and company stats and set
        new weights for the names in the index. Those weights were scored against the
        market rather than traded. As a safeguard, the rebalance itself runs off a
        deterministic script so no single generation can move the account. Everything
        ran through an Alpaca paper account with no real money. The weekly loop ran for
        a year and is now over. This page is the leftover record: what the fund looks
        like now, how it did versus SPY, and how the system was built.
      </p>

      <section className="mb-xl">
        <h2 className="section-title">How it ended</h2>
        <div className="grid grid-4">
          <div className="card">
            <p className="stat-label">Paper account now</p>
            <div className="stat-value">{money(equity)}</div>
            {startEquity != null && (
              <p className="stat-note">Started at {money(startEquity)}</p>
            )}
          </div>
          <div className="card">
            <p className="stat-label">Total return</p>
            <div className={`stat-value ${pctClass(totalReturn)}`}>
              {signedPct(totalReturn)}
            </div>
            <p className="stat-note">Over the full year</p>
          </div>
          <div className="card">
            <p className="stat-label">Versus SPY</p>
            <div className={`stat-value ${pctClass(vsSpy)}`}>
              {vsSpy == null ? '—' : signedPct(vsSpy)}
            </div>
            <p className="stat-note">
              {spyReturn == null ? 'S&P 500 ETF as the benchmark' : `SPY was ${signedPct(spyReturn)}`}
            </p>
          </div>
          <div className="card">
            <p className="stat-label">What it holds</p>
            <div className="stat-value">{positions.length} stocks</div>
            <p className="stat-note">{money(cash)} sitting in cash</p>
          </div>
        </div>
        <p className="text-sm text-muted mt-md mb-0">
          Charts and the full statistical write-up are on{' '}
          <Link to="/portfolio/history">History</Link> and{' '}
          <Link to="/portfolio/statistics">Statistics</Link>.
        </p>
      </section>

      <section>
        <h2 className="section-title">Where the money sits now</h2>
        <div className="card">
          <p className="text-muted mb-lg">
            The account weights every position by market cap. These are the eight
            largest positions in it. How the model would have weighted the same names is
            on <Link to="/portfolio/analysis">Weight Analysis</Link>.
          </p>
          {topHoldings.length === 0 ? (
            <p className="text-muted mb-0">No open positions.</p>
          ) : (
            <div className="holding-list">
              {topHoldings.map((pos) => {
                const weight = equity > 0 ? (pos.market_value / equity) * 100 : 0;
                return (
                  <div key={pos.symbol} className="holding-row">
                    <div className="holding-symbol">{pos.symbol}</div>
                    <div className="holding-track">
                      <div
                        className="holding-fill"
                        style={{ width: `${Math.max(4, (pos.market_value / maxValue) * 100)}%` }}
                      />
                    </div>
                    <div className="holding-value">{money(pos.market_value)}</div>
                    <div className="holding-pct">{weight.toFixed(1)}%</div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </section>

      <section className="mt-xl">
        <h2 className="section-title">The model</h2>
        <div className="card">
          <p className="text-muted mb-lg">
            Nothing here called a general-purpose chat API. The weights were a{' '}
            <strong>LoRA fine-tune</strong>, a small adapter trained on top of a frozen
            base model, and it learned from a <strong>synthetic dataset</strong> I generated
            myself, because no labelled "what weight should this stock get" data exists.
          </p>
          <div className="spec-list">
            <div className="spec-row">
              <div className="spec-key">Base model</div>
              <div className="spec-val"><strong>Llama-2-7B-chat</strong>, frozen</div>
            </div>
            <div className="spec-row">
              <div className="spec-key">Starting adapter</div>
              <div className="spec-val">
                FinGPT forecaster LoRA (Dow 30), finance-tuned but never exposed to the S&amp;P 500
              </div>
            </div>
            <div className="spec-row">
              <div className="spec-key">Training data</div>
              <div className="spec-val">
                <strong>~1,500 synthetic prompt/response pairs</strong> I generated across the
                S&amp;P 500, each one an allocation call with a short justification
              </div>
            </div>
            <div className="spec-row">
              <div className="spec-key">Fine-tune</div>
              <div className="spec-val">4 epochs at a 2e-5 learning rate, adapter weights only</div>
            </div>
            <div className="spec-row">
              <div className="spec-key">Serving</div>
              <div className="spec-val">RunPod GPU endpoint, called once per ticker per week</div>
            </div>
          </div>
          <p className="prompt-note">
            Only the adapter was trained, so the whole fine-tune is an 80 MB file rather than a
            full 7-billion-parameter copy. That is the practical appeal of LoRA: it fits on one
            GPU and takes hours rather than days.
          </p>
        </div>
      </section>

      <section className="mt-xl">
        <h2 className="section-title">What the model saw each week</h2>
        <div className="card">
          <p className="text-muted mb-lg">
            Every ticker got the same prompt in three parts: an instruction in plain English,
            one block of numbers pulled from the database, and a strict output shape. Here it
            is trimmed down for AAPL.
          </p>

          <div className="prompt-block">
            <div>
              <p className="prompt-part-label">1. The instruction, in plain English</p>
              <pre className="prompt-code wrap">{`You are a portfolio optimization assistant.

For a given stock snapshot, recommend how the allocation
should be adjusted. Allocation percentages are scaled by 100,
so 150 means 1.5%. Reply with JSON only. No commentary.`}</pre>
            </div>

            <div>
              <p className="prompt-part-label">2. The data points, one snapshot per ticker</p>
              <pre className="prompt-code">
                <span className="tok-punc">{'{\n'}</span>
                {PROMPT_FIELDS.slice(0, 7).map((f) => <Field key={f.k} {...f} />)}
                {'  '}
                <span className="tok-key">"key_metrics"</span>
                <span className="tok-punc">{': {\n'}</span>
                {PROMPT_FIELDS.slice(7, 10).map((f) => <Field key={f.k} {...f} />)}
                <span className="tok-punc">{'  },\n'}</span>
                {PROMPT_FIELDS.slice(10).map((f) => <Field key={f.k} {...f} />)}
                <span className="tok-punc">{'}'}</span>
              </pre>
            </div>

            <div>
              <p className="prompt-part-label">3. The only shape it was allowed to answer in</p>
              <pre className="prompt-code">
                <span className="tok-punc">{'{\n  '}</span>
                <span className="tok-key">"verdict"</span>
                <span className="tok-punc">: </span>
                <span className="tok-str">"Increase"</span>
                <span className="tok-punc">,</span>
                <span className="tok-note">{'      // Increase | Decrease | Hold | Add | Remove'}</span>
                {'\n  '}
                <span className="tok-key">"new_alloc_pct"</span>
                <span className="tok-punc">: </span>
                <span className="tok-num">680</span>
                <span className="tok-punc">,</span>
                <span className="tok-note">{'          // basis points, so 6.80%'}</span>
                {'\n  '}
                <span className="tok-key">"reasoning"</span>
                <span className="tok-punc">: </span>
                <span className="tok-str">"..."</span>
                <span className="tok-note">{'              // one short sentence'}</span>
                {'\n'}
                <span className="tok-punc">{'}'}</span>
              </pre>
            </div>
          </div>

          <p className="prompt-note">
            The rigid JSON shape is the reason the fine-tune was needed at all. A stock model
            will happily write an essay; this one had to return a number the trading job could
            act on without a human reading it.
          </p>
        </div>
      </section>
    </div>
  );
}
