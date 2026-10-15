import { useState } from 'react';

const REPO = 'https://github.com/aazminu/sp500_platform';

const CONSTRAINTS = [
  {
    tag: 'No data',
    title: 'Nobody publishes the labels',
    text: 'The task is "what weight should this ticker carry next week." No dataset of correct answers exists, and there is none to buy.',
    answer:
      'So I generated one. FinGPT ran over 503 tickers at 3 historical dates for 1,509 pairs. The ceiling is baked in, since labels from the same model family can only ever teach format.',
  },
  {
    tag: 'No hardware',
    title: 'One GPU, and 7B does not fit',
    text: 'Llama-2-7B needs roughly 14 GB just to hold fp16 weights, before optimizer state, gradients, and activations. Full fine-tuning needs several times that.',
    answer:
      'So I froze the base, loaded it in 8-bit, and trained an adapter with gradient checkpointing and a 512-token cutoff. The run went from impossible to 1 h 43 m.',
  },
  {
    tag: 'No budget',
    title: 'The job runs once a week',
    text: 'A dedicated GPU bills for 168 hours a week to do a few minutes of work, and the market data plan caps out at 300 requests a minute.',
    answer:
      'So inference is serverless and billed per second, and ingestion is paced at 0.21 s per call to sit just under the cap. Design around the meter.',
  },
];

const TRADEOFFS = [
  {
    decision: '8-bit base, LoRA adapter',
    spec: 'bitsandbytes int8, base frozen',
    bought: 'A 7B fine-tune that fits one GPU and ships as an 80 MB adapter instead of a 13 GB model.',
    cost: 'Quantization error in every frozen layer, and an adapter can only nudge a model it cannot restructure.',
  },
  {
    decision: 'Gradient accumulation over a bigger batch',
    spec: 'micro-batch 4 × 8 steps = 32',
    bought: 'The gradient of a 32-example batch at the memory cost of a 4-example one, across 192 optimizer steps.',
    cost: 'Eight forward and backward passes per update. Memory stays flat, wall-clock does not.',
  },
  {
    decision: 'A deliberate prompt budget',
    spec: '512-token cutoff, 2 headlines at 100 chars',
    bought: 'Every example fits the training window, so nothing gets silently truncated mid-example.',
    cost: 'The model never sees full news flow, and the yearly block drops news entirely to stay inside the budget.',
  },
  {
    decision: 'Serverless inference',
    spec: 'RunPod async, temperature 0',
    bought: 'Nothing billed for the 168 hours a week the model is idle, and no server to keep patched.',
    cost: 'A cold start on every call, and a 300 s ceiling per ticker before the job is abandoned.',
  },
  {
    decision: 'Serial calls with no batching',
    spec: 'one job per ticker, ~503 a week',
    bought: 'The simplest failure model available: one ticker fails, one row is missing, and a re-run repairs it.',
    cost: 'All of the throughput. Nothing waits on a weekly job, so concurrency buys latency I have no use for. It is the first thing I would change if this ran daily.',
  },
  {
    decision: 'Rate limiting with a sleep',
    spec: '0.21 s between calls',
    bought: '~285 requests a minute, just under the 300 cap, in three lines and with no queue to operate.',
    cost: 'A full refresh is bounded by wall-clock rather than bandwidth, and the pacing is hardcoded per script.',
  },
];

const PIPELINE = [
  {
    n: 1,
    title: 'Build a dataset',
    text: 'No labelled weight data exists, so I generated it. FinGPT ran over historical market snapshots and wrote the answers.',
    facts: [
      ['Coverage', '503 tickers × 3 dates'],
      ['Examples', '1,509 pairs'],
      ['Published', 'mdot77/sp500p'],
    ],
  },
  {
    n: 2,
    title: 'Fine-tune with LoRA',
    text: 'The base stayed frozen and only a small adapter trained. That is what fit the job on one GPU, in 1 h 43 m.',
    facts: [
      ['Base', 'Llama-2-7B-chat'],
      ['Schedule', '4 epochs @ 2e-5'],
      ['Batch', '4 × 8 accum = 32'],
    ],
  },
  {
    n: 3,
    title: 'Quantize to fit',
    text: 'fp16 weights alone need ~14 GB, before optimizer state. Loading the frozen base in 8-bit is what made the run start.',
    facts: [
      ['Weights', 'int8 (bitsandbytes)'],
      ['Also', 'grad checkpointing'],
      ['Trained', 'adapter only, 80 MB'],
    ],
  },
  {
    n: 4,
    title: 'Serve it serverless',
    text: 'A weekly job does not need an idle GPU. RunPod spins one up per request and bills by the second.',
    facts: [
      ['Call', 'POST /run (async)'],
      ['Poll', '/status every 5s'],
      ['Sampling', 'temperature 0'],
    ],
  },
];

// Coordinates are laid out by hand against the 880 x 570 viewBox below.
const NODES = [
  {
    id: 'fmp',
    x: 30, y: 40, w: 190, h: 54,
    label: 'FMP API',
    sub: 'external',
    external: true,
    detail: 'Supplies all the market data: constituents, prices, market caps, fundamentals, and news. Calls are spaced 0.21s apart to stay inside the rate limit.',
    links: [['Rate limit', '0.21s between calls'], ['Feeds', '9 of the 12 ingestion scripts']],
  },
  {
    id: 'alpaca',
    x: 30, y: 300, w: 190, h: 54,
    label: 'Alpaca',
    sub: 'paper broker',
    external: true,
    detail: 'The paper brokerage. Takes the rebalancing orders, and is read back for live equity and positions. No real money moved through it.',
    links: [['Orders', 'dollar notional, day TIF'], ['Retries', '429 backoff, 3 attempts']],
  },
  {
    id: 'runall',
    x: 345, y: 40, w: 190, h: 54,
    label: 'run_all.py',
    sub: 'orchestrator',
    detail: 'The weekly entry point. Instead of a scheduler, each script has a row with its frequency and last success date, and whatever is overdue gets run.',
    links: [['Cadence', 'daily / weekly / quarterly / annual'], ['State', 'ingestion_metadata table']],
  },
  {
    id: 'db',
    x: 345, y: 170, w: 190, h: 54,
    label: 'Postgres',
    sub: 'the hub',
    detail: 'Holds the market data, the weekly model calls, and daily equity snapshots for the portfolio and SPY. Every write is an upsert, so re-running a job repairs gaps rather than duplicating rows.',
    links: [['Host', 'Render Postgres'], ['Writes', 'idempotent upserts']],
  },
  {
    id: 'llmjob',
    x: 660, y: 40, w: 190, h: 54,
    label: 'fetch_weekly_llm.py',
    sub: 'prompt builder',
    detail: 'Builds one prompt per ticker from price, volatility, previous weight, fundamentals, and two headlines, submits it, polls until done, and writes the reply back.',
    links: [['Submits', 'POST /run, then polls /status'], ['Ceiling', '5s interval, 300s max']],
  },
  {
    id: 'runpod',
    x: 660, y: 170, w: 190, h: 54,
    label: 'RunPod',
    sub: 'serverless GPU',
    detail: 'The fine-tuned model behind an async endpoint, spun up per request rather than rented for 168 idle hours a week. Temperature 0, for a consistent number rather than creative writing.',
    links: [['Model', 'Llama-2-7B + fine-tuned LoRA'], ['Mode', 'async submit, then poll']],
  },
  {
    id: 'trades',
    x: 345, y: 300, w: 190, h: 54,
    label: 'run_trades.py',
    sub: 'rebalancer',
    detail: 'Reads market-cap weights and moves the account toward them. Sells run first, then buys are scaled to the cash they freed. DRY_RUN defaults to on.',
    links: [['Targets', 'market-cap weights'], ['Safety', 'DRY_RUN=1 by default']],
  },
  {
    id: 'api',
    x: 345, y: 430, w: 190, h: 54,
    label: 'Flask API',
    sub: 'read layer',
    detail: 'A read-only JSON layer over Postgres and Alpaca. Most routes are thin; /performance/summary does the real work behind the Statistics page.',
    links: [['Stack', 'Flask + SQLAlchemy'], ['CORS', 'single allowed origin']],
  },
  {
    id: 'web',
    x: 660, y: 430, w: 190, h: 54,
    label: 'React frontend',
    sub: 'this site',
    detail: 'React on Vite. Recharts draws the charts, this diagram is hand-written SVG. Seven routes share one layout and one API client.',
    links: [['Build', 'Vite 7'], ['Charts', 'Recharts + hand-rolled SVG']],
  },
  {
    id: 'cache',
    x: 660, y: 512, w: 190, h: 40,
    label: 'Browser cache',
    detail: 'An in-memory Map backed by sessionStorage, wrapping every API call. Ten-minute lifetime; components mounting together share one request.',
    links: [['Where', 'frontend/src/api.js'], ['TTL', '10 minutes']],
  },
];

const EDGES = [
  { id: 'e1', from: 'fmp', to: 'runall', d: 'M 222 67 L 341 67', label: 'market data', lx: 232, ly: 58 },
  { id: 'e2', from: 'runall', to: 'db', d: 'M 440 96 L 440 166', label: '9 fetchers', lx: 448, ly: 136 },
  { id: 'e3', from: 'db', to: 'llmjob', d: 'M 537 184 L 596 184 L 596 67 L 656 67', label: 'prompt per ticker', lx: 604, ly: 120 },
  { id: 'e4', from: 'llmjob', to: 'runpod', d: 'M 755 96 L 755 166', label: 'prompt', lx: 763, ly: 136 },
  { id: 'e5', from: 'runpod', to: 'db', d: 'M 656 200 L 539 200', label: 'JSON verdict stored', lx: 546, ly: 214, store: true },
  { id: 'e6', from: 'db', to: 'trades', d: 'M 440 226 L 440 296', label: 'market-cap weights', lx: 448, ly: 266 },
  {
    id: 'e7', from: 'runpod', to: 'trades',
    d: 'M 700 226 C 700 285, 620 300, 541 320',
    label: 'blocked by design', lx: 556, ly: 276,
    blocked: true, mark: [634, 290],
  },
  { id: 'e8', from: 'trades', to: 'alpaca', d: 'M 341 327 L 224 327', label: 'notional orders', lx: 232, ly: 318 },
  { id: 'e9', from: 'db', to: 'api', d: 'M 345 212 L 300 212 L 300 448 L 341 448', label: 'history + stats', lx: 206, ly: 280 },
  { id: 'e10', from: 'alpaca', to: 'api', d: 'M 125 356 L 125 470 L 341 470', label: 'live account', lx: 150, ly: 462 },
  { id: 'e11', from: 'api', to: 'web', d: 'M 537 457 L 656 457', label: 'JSON', lx: 574, ly: 448 },
  { id: 'e12', from: 'web', to: 'cache', d: 'M 755 486 L 755 508', label: '', lx: 0, ly: 0 },
];

function nodeClass(node, active, connected) {
  if (!active) return 'dg-node' + (node.external ? ' is-external' : '');
  const base = 'dg-node' + (node.external ? ' is-external' : '');
  if (node.id === active) return `${base} is-active`;
  return connected.has(node.id) ? base : `${base} is-dim`;
}

function edgeClass(edge, active) {
  const base = 'dg-edge' + (edge.blocked ? ' is-blocked' : '') + (edge.store ? ' is-store' : '');
  if (!active) return base;
  const touches = edge.from === active || edge.to === active;
  return touches ? `${base} is-on` : `${base} is-dim`;
}

function ArchitectureDiagram() {
  const [active, setActive] = useState(null);

  const connected = new Set();
  if (active) {
    EDGES.forEach((e) => {
      if (e.from === active) connected.add(e.to);
      if (e.to === active) connected.add(e.from);
    });
  }

  const selected = NODES.find((n) => n.id === active);

  return (
    <div className="diagram-card">
      <div className="diagram-toolbar">
        <p className="diagram-hint">
          Select any box to trace what connects to it.
        </p>
        {active && (
          <button className="btn btn-sm" onClick={() => setActive(null)}>
            Clear selection
          </button>
        )}
      </div>

      <div className="diagram-scroll">
        <svg className="diagram-svg" viewBox="0 0 880 570" role="img"
          aria-label="Architecture diagram of the data pipeline">
          <defs>
            {/* Markers cannot inherit the referencing path's stroke, so there is one per state */}
            <marker id="dg-arrow" viewBox="0 0 10 10" refX="9" refY="5"
              markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--border-strong)" />
            </marker>
            <marker id="dg-arrow-on" viewBox="0 0 10 10" refX="9" refY="5"
              markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--primary)" />
            </marker>
          </defs>

          {EDGES.map((e) => {
            const on = active && (e.from === active || e.to === active);
            return (
              <g key={e.id} className={edgeClass(e, active)}>
                <path
                  d={e.d}
                  markerEnd={e.blocked ? undefined : `url(#dg-arrow${on ? '-on' : ''})`}
                />
                {e.mark && (
                  <>
                    <line className="dg-block-mark"
                      x1={e.mark[0] - 5} y1={e.mark[1] - 5}
                      x2={e.mark[0] + 5} y2={e.mark[1] + 5} />
                    <line className="dg-block-mark"
                      x1={e.mark[0] + 5} y1={e.mark[1] - 5}
                      x2={e.mark[0] - 5} y2={e.mark[1] + 5} />
                  </>
                )}
                {e.label && <text x={e.lx} y={e.ly}>{e.label}</text>}
              </g>
            );
          })}

          {NODES.map((n) => (
            <g
              key={n.id}
              className={nodeClass(n, active, connected)}
              onClick={() => setActive(active === n.id ? null : n.id)}
              onKeyDown={(ev) => {
                if (ev.key === 'Enter' || ev.key === ' ') {
                  ev.preventDefault();
                  setActive(active === n.id ? null : n.id);
                }
              }}
              tabIndex={0}
              role="button"
              aria-pressed={active === n.id}
            >
              <rect x={n.x} y={n.y} width={n.w} height={n.h} rx="8" />
              <text className="dg-title" x={n.x + 14} y={n.y + (n.sub ? 23 : 25)}>
                {n.label}
              </text>
              {n.sub && (
                <text className="dg-sub" x={n.x + 14} y={n.y + 40}>{n.sub}</text>
              )}
            </g>
          ))}
        </svg>
      </div>

      <div className="dg-detail">
        {selected ? (
          <>
            <div className="dg-detail-head">
              <h3 className="dg-detail-title">{selected.label}</h3>
              {selected.sub && <span className="dg-detail-path">{selected.sub}</span>}
            </div>
            <p>{selected.detail}</p>
            <div className="dg-detail-links">
              {selected.links.map(([k, v]) => (
                <div key={k} className="dg-detail-link">
                  {k}: <strong>{v}</strong>
                </div>
              ))}
            </div>
          </>
        ) : (
          <>
            <div className="dg-detail-head">
              <h3 className="dg-detail-title">Reading the diagram</h3>
            </div>
            <p>
              Arrows point the way data flows. The amber path crossed with an ✕ was never
              built: the model's weights are recorded, but the rebalance runs off the
              script instead. Dashed outlines are services I do not own.
            </p>
          </>
        )}
      </div>
    </div>
  );
}

const LEARNINGS = [
  {
    title: 'The fine-tune only bought consistency',
    text: 'My training data came from the same model family I was fine-tuning, so it could not teach the model anything new, only make it consistent. I got reliable JSON instead of an essay, which is a formatting win with no forecasting value.',
  },
  {
    title: 'Three examples per ticker is not much',
    text: '1,509 pairs sounds like a lot until you divide by 503 tickers. Enough to teach a response shape, nowhere near enough to teach it about a business.',
  },
  {
    title: 'LoRA plus 8-bit made this possible at all',
    text: 'Training all 7 billion parameters was never an option on my hardware. Freezing the base and training a small adapter turned an impossible job into a 1 h 43 m one, and produced 80 MB instead of 13 GB.',
  },
  {
    title: 'The cadence justified every infrastructure choice',
    text: '503 predictions once a week, with nobody waiting on the result. That single fact is what makes serverless beat a rented GPU, a serial loop beat a worker pool, and a metadata table beat a real scheduler. Move to daily and all three answers change.',
  },
  {
    title: 'A metadata table beat a real scheduler',
    text: 'Each job has a row with its frequency and last success date, and the orchestrator runs whatever is overdue. Easy to inspect, and self-healing: a failed job just stays overdue.',
  },
  {
    title: 'Keep the model out of the order path',
    text: 'Weights were stored weekly but nothing downstream could act on them, so a bad number has no route to the broker. The cost is that the traded results only grade the rebalancing script.',
  },
  {
    title: 'Caching should not have been an afterthought',
    text: 'Every page load re-ran the bootstrap from scratch. Ten-minute caching in the browser took forty lines and made the site feel instant.',
  },
];

export default function SystemDesign() {
  return (
    <div className="design-page">
      <header className="page-header">
        <div className="page-header-text">
          <p className="page-eyebrow">Technical overview</p>
          <h1>System Design</h1>
          <p className="page-desc">
            What I did not have, what that forced, how the pieces connect, and what I would
            do differently.
          </p>
        </div>
      </header>

      <section>
        <h2 className="section-title">What I was working against</h2>
        <p className="design-lede mb-lg">
          Almost every interesting decision here was made for me by a constraint. Three of
          them shaped the whole system.
        </p>
        <div className="constraint-grid">
          {CONSTRAINTS.map((c) => (
            <article key={c.tag} className="constraint-card">
              <div className="constraint-tag">{c.tag}</div>
              <h3 className="constraint-title">{c.title}</h3>
              <p className="constraint-text">{c.text}</p>
              <p className="constraint-answer">{c.answer}</p>
            </article>
          ))}
        </div>
      </section>

      <section>
        <h2 className="section-title">The model pipeline</h2>
        <p className="design-lede mb-lg">
          Four stages, each solving a problem created by the one before it.
        </p>
        <div className="pipeline">
          {PIPELINE.map((s) => (
            <article key={s.n} className="pipeline-stage">
              <div className="pipeline-num">{s.n}</div>
              <h3 className="pipeline-title">{s.title}</h3>
              <p className="pipeline-text">{s.text}</p>
              <dl className="pipeline-facts">
                {s.facts.map(([k, v]) => (
                  <div key={k} className="pipeline-fact">
                    <dt>{k}</dt>
                    <dd>{v}</dd>
                  </div>
                ))}
              </dl>
            </article>
          ))}
        </div>
        <div className="callout">
          <p>
            <span className="callout-title">On quantization</span>
            Quantization here happened at training time. The frozen base loaded in 8-bit
            so the run fit in memory, while the adapter trained at full precision. No GPTQ,
            AWQ, or GGUF build was ever exported.
          </p>
        </div>
      </section>

      <section>
        <h2 className="section-title">What each decision cost</h2>
        <p className="design-lede mb-lg">
          Every one of these bought something and gave something up. The right-hand column is
          the part worth being honest about.
        </p>
        <div className="card">
          <div className="table-container">
            <table className="performance-table">
              <thead>
                <tr>
                  <th>Decision</th>
                  <th>What it bought</th>
                  <th>What it cost</th>
                </tr>
              </thead>
              <tbody>
                {TRADEOFFS.map((t) => (
                  <tr key={t.decision}>
                    <td className="metric-name">
                      <div className="metric-title">{t.decision}</div>
                      <div className="metric-desc">{t.spec}</div>
                    </td>
                    <td className="stat-read">{t.bought}</td>
                    <td className="stat-read">{t.cost}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section>
        <h2 className="section-title">How the pieces connect</h2>
        <p className="design-lede mb-lg">
          Ten components, running once a week unattended. Data enters on the left, settles in
          Postgres, and leaves through the API.
        </p>
        <ArchitectureDiagram />
      </section>

      <section>
        <h2 className="section-title">Why the model does not place trades</h2>
        <div className="card">
          <p className="text-muted mb-lg">
            The one arrow deliberately missing from the diagram.
          </p>
          <div className="spec-list">
            <div className="spec-row">
              <div className="spec-key">What executes</div>
              <div className="spec-val">
                <code>run_trades.py</code>, rebalancing to <strong>market-cap weights</strong>
              </div>
            </div>
            <div className="spec-row">
              <div className="spec-key">What the model does</div>
              <div className="spec-val">
                Produces a weight per ticker each week, stored and compared on the Weight
                Analysis page
              </div>
            </div>
            <div className="spec-row">
              <div className="spec-key">Why the gap</div>
              <div className="spec-val">
                A model can return a malformed number or a ticker that is not in the index.
                A deterministic order path means <strong>no single generation can move money</strong>
              </div>
            </div>
            <div className="spec-row">
              <div className="spec-key">Second safeguard</div>
              <div className="spec-val">
                <code>DRY_RUN</code> defaults to <strong>1</strong>, so the script previews
                unless explicitly switched to live
              </div>
            </div>
            <div className="spec-row">
              <div className="spec-key">The trade-off</div>
              <div className="spec-val">
                The equity curve only measures the rebalancing script
              </div>
            </div>
          </div>
        </div>
      </section>

      <section>
        <h2 className="section-title">Caching</h2>
        <div className="card">
          <p className="text-muted mb-lg">
            For most of the year there was none. The data changes weekly, yet every click
            re-queried Postgres and re-ran the statistics. The fix lives in the browser.
          </p>
          <div className="spec-list">
            <div className="spec-row">
              <div className="spec-key">Where</div>
              <div className="spec-val">
                <code>frontend/src/api.js</code>, wrapping every backend call
              </div>
            </div>
            <div className="spec-row">
              <div className="spec-key">Two layers</div>
              <div className="spec-val">
                An in-memory <strong>Map</strong>, backed by <strong>sessionStorage</strong>{' '}
                so a reload keeps the data
              </div>
            </div>
            <div className="spec-row">
              <div className="spec-key">Lifetime</div>
              <div className="spec-val">10 minutes</div>
            </div>
            <div className="spec-row">
              <div className="spec-key">Deduplication</div>
              <div className="spec-val">
                Components mounting at once share one in-flight request
              </div>
            </div>
            <div className="spec-row">
              <div className="spec-key">Failures</div>
              <div className="spec-val">Never cached, so a retry always hits the network</div>
            </div>
          </div>
        </div>
      </section>

      <section>
        <h2 className="section-title">What I learned</h2>
        <div className="card">
          <div className="learn-list">
            {LEARNINGS.map((l, i) => (
              <article key={l.title} className="learn-item">
                <div className="learn-num">{String(i + 1).padStart(2, '0')}</div>
                <div>
                  <h3 className="learn-title">{l.title}</h3>
                  <p className="learn-text">{l.text}</p>
                </div>
              </article>
            ))}
          </div>
          <p className="prompt-note">
            Every claim here is checkable against the source, since{' '}
            <a href={REPO} target="_blank" rel="noopener noreferrer">
              the repository is public
            </a>
            .
          </p>
        </div>
      </section>
    </div>
  );
}
