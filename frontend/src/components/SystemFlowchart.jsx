import { useState } from 'react';

const STEPS = [
  {
    id: 'collect',
    n: 1,
    title: 'Collect the week’s stock data',
    plain: 'Every week a scheduled job pulled prices, news, and analyst data for the S&P 500 and saved it in Postgres.',
    details: [
      'Ticker list, daily prices, market cap, and news',
      'Analyst ratings and company metrics',
      'Stored in the same database the rest of the app reads',
    ],
    link: { label: 'See the weekly job', href: 'https://github.com/aazminu/sp500_platform/blob/main/ingestion/run_all.py' },
  },
  {
    id: 'decide',
    n: 2,
    title: 'Ask the model how to weight each stock',
    plain: 'That data was turned into a short prompt per ticker. A fine-tuned LLM replied with Increase, Decrease, Hold, Add, or Remove, plus a new weight. Those answers were recorded and scored, but on purpose they were never sent to the broker.',
    details: [
      'Prompt built from price, news, and fundamentals',
      'Model hosted on RunPod',
      'JSON replies stored so we could compare weeks',
    ],
    link: { label: 'See the prompt code', href: 'https://github.com/aazminu/sp500_platform/blob/main/ingestion/fetch_weekly_llm.py' },
  },
  {
    id: 'trade',
    n: 3,
    title: 'Rebalance the paper account',
    plain: 'The trading job compared the current paper portfolio to plain S&P 500 market-cap weights and sent buy/sell orders through Alpaca. The model was kept out of this step as a safeguard, so one bad generation could never reshape the account.',
    details: [
      'Targets came from market cap alone',
      'Sells first, then buys scaled to the cash freed up',
      'Fractional shares, paper trading only',
      'Dry-run mode on by default; orders preview unless switched live',
    ],
    link: { label: 'See the trade script', href: 'https://github.com/aazminu/sp500_platform/blob/main/ingestion/run_trades.py' },
  },
  {
    id: 'show',
    n: 4,
    title: 'Show the results here',
    plain: 'This site reads the Alpaca account and the database so you can see holdings, history, and how the model differed from a plain S&P 500 weight.',
    details: [
      'Overview page = live paper account',
      'History and Statistics = daily performance vs SPY',
      'Weight Analysis = model vs market-cap weights',
    ],
    link: { label: 'See the frontend', href: 'https://github.com/aazminu/sp500_platform/tree/main/frontend' },
  },
];

function Step({ step, open, onToggle }) {
  return (
    <article className="story-step">
      <div className="story-step-num" aria-hidden="true">{step.n}</div>
      <div className="story-step-body">
        <h2 className="story-step-title">{step.title}</h2>
        <p className="story-step-text">{step.plain}</p>
        <button
          type="button"
          className="story-more"
          aria-expanded={open}
          onClick={onToggle}
        >
          {open ? 'Hide details' : 'More detail'}
        </button>
        {open && (
          <div className="story-details">
            <ul>
              {step.details.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
            {step.link && (
              <a className="story-link" href={step.link.href} target="_blank" rel="noopener noreferrer">
                {step.link.label} →
              </a>
            )}
          </div>
        )}
      </div>
    </article>
  );
}

export default function SystemFlowchart() {
  const [openId, setOpenId] = useState(null);

  return (
    <div className="story-page">
      <header className="page-header">
        <div className="page-header-text">
          <p className="page-eyebrow">The weekly loop · Aug 2025 – Aug 2026</p>
          <h1>How it worked</h1>
          <p className="page-desc">
            This was a year-long paper-trading experiment. Once a week, four things happened in order.
            Read top to bottom. Open a step only if you want extra detail.
          </p>
        </div>
      </header>

      <div className="story-steps">
        {STEPS.map((step) => (
          <Step
            key={step.id}
            step={step}
            open={openId === step.id}
            onToggle={() => setOpenId(openId === step.id ? null : step.id)}
          />
        ))}
      </div>
    </div>
  );
}
