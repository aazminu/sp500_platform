import { useState } from 'react';

const PHASES = [
  {
    id: 'data',
    n: 1,
    when: 'Start',
    title: 'Pull three years of S&P 500 data',
    plain: 'I used the Financial Modeling Prep API to download prices, market caps, news, and analyst estimates, then stored them in Postgres on Render.',
    details: [
      'Python scripts, one table per data type',
      'Daily prices, weekly grades, quarterly estimates',
      'Same database the live weekly job later updated',
    ],
  },
  {
    id: 'model',
    n: 2,
    when: 'Next',
    title: 'Pick a finance model and build training prompts',
    plain: 'I started from a finance-tuned model on Hugging Face, then generated 1,500+ prompt/response pairs covering the S&P 500 so I could fine-tune and evaluate it.',
    details: [
      'Prompts used real metrics from the database',
      'Each reply had to be valid JSON with a verdict and a weight',
      'Notebooks live in the prompting-training folder',
    ],
    links: [
      { label: 'Prompt generation notebook', href: 'https://github.com/aazminu/sp500_platform/blob/main/prompting-training/FInal-Data-Gen.ipynb' },
    ],
  },
  {
    id: 'validate',
    n: 3,
    when: 'Then',
    title: 'Test and host the model',
    plain: 'After validation and fine-tuning, the model ran as an API on RunPod so the weekly job could call it without a local GPU.',
    details: [
      'Domain checks on S&P 500 names',
      'RunPod endpoint for real-time inference',
    ],
    links: [
      { label: 'Fine-tuning notebook', href: 'https://github.com/aazminu/sp500_platform/blob/main/prompting-training/fine-tuning-updated.ipynb' },
    ],
  },
  {
    id: 'live',
    n: 4,
    when: 'Go live',
    title: 'Put it on a weekly schedule',
    plain: 'A cron job ran the full loop: refresh the data, call the model and store its answer, then rebalance the Alpaca paper account to market-cap weights.',
    details: [
      'Weekly cadence for a full year',
      'Model output recorded and scored, kept out of the order path on purpose',
      'Paper trading with fractional shares',
      'No live money',
    ],
  },
  {
    id: 'site',
    n: 5,
    when: 'This site',
    title: 'Build the dashboard you are on now',
    plain: 'The React app shows the paper portfolio, daily performance versus SPY, and where the model disagreed with market-cap weights.',
    details: [
      'React + Vite frontend',
      'Flask API in front of Postgres and Alpaca',
    ],
    links: [
      { label: 'Frontend code', href: 'https://github.com/aazminu/sp500_platform/tree/main/frontend' },
    ],
  },
];

function Phase({ phase, open, onToggle }) {
  return (
    <article className="story-step">
      <div className="story-step-num" aria-hidden="true">{phase.n}</div>
      <div className="story-step-body">
        <p className="story-when">{phase.when}</p>
        <h2 className="story-step-title">{phase.title}</h2>
        <p className="story-step-text">{phase.plain}</p>
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
              {phase.details.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
            {phase.links?.map((link) => (
              <a key={link.href} className="story-link" href={link.href} target="_blank" rel="noopener noreferrer">
                {link.label} →
              </a>
            ))}
          </div>
        )}
      </div>
    </article>
  );
}

export default function BuildTimeline() {
  const [openId, setOpenId] = useState(null);

  return (
    <div className="story-page">
      <header className="page-header">
        <div className="page-header-text">
          <p className="page-eyebrow">Build order · year-long experiment</p>
          <h1>How I built it</h1>
          <p className="page-desc">
            Five steps, in the order I actually did them. You can read this as a short story without clicking anything.
          </p>
        </div>
      </header>

      <div className="story-steps">
        {PHASES.map((phase) => (
          <Phase
            key={phase.id}
            phase={phase}
            open={openId === phase.id}
            onToggle={() => setOpenId(openId === phase.id ? null : phase.id)}
          />
        ))}
      </div>
    </div>
  );
}
