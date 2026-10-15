// src/api.js
const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:5000';

// The underlying data only changes when the weekly ingestion job runs, so a response
// stays valid far longer than a page visit. Caching makes tab-to-tab navigation
// instant and keeps the expensive /performance/summary endpoint from re-running its
// bootstrap resampling every time someone clicks back to Statistics.
const TTL_MS = 10 * 60 * 1000;
// Bump the prefix whenever a response shape changes, so cached entries written by an
// older build are never handed to a newer component.
const STORE_PREFIX = 'oz2:';

const memory = new Map();
const inFlight = new Map();

function readCache(key) {
  const hit = memory.get(key);
  if (hit) return hit;
  try {
    const raw = sessionStorage.getItem(STORE_PREFIX + key);
    if (!raw) return null;
    const entry = JSON.parse(raw);
    memory.set(key, entry);
    return entry;
  } catch {
    return null;
  }
}

function writeCache(key, value) {
  const entry = { at: Date.now(), value };
  memory.set(key, entry);
  try {
    sessionStorage.setItem(STORE_PREFIX + key, JSON.stringify(entry));
  } catch {
    // Storage can be full or blocked; the in-memory copy still serves this session.
  }
}

export function clearApiCache() {
  memory.clear();
  try {
    Object.keys(sessionStorage)
      .filter((k) => k.startsWith(STORE_PREFIX))
      .forEach((k) => sessionStorage.removeItem(k));
  } catch {
    // Nothing to clear if storage is unavailable.
  }
}

async function cached(key, fetcher, { force = false } = {}) {
  if (force) {
    memory.delete(key);
    try {
      sessionStorage.removeItem(STORE_PREFIX + key);
    } catch {
      // Ignore; the in-memory delete above is enough.
    }
  } else {
    const hit = readCache(key);
    if (hit && Date.now() - hit.at < TTL_MS) return hit.value;
  }

  // If two components mount at once, they share one network request.
  if (inFlight.has(key)) return inFlight.get(key);

  const request = fetcher()
    .then((value) => {
      writeCache(key, value);
      return value;
    })
    .finally(() => inFlight.delete(key));

  inFlight.set(key, request);
  return request;
}

// Failed requests are never written to the cache, so a retry always hits the network.
async function getJson(path, pick) {
  try {
    const response = await fetch(`${API_BASE}${path}`);
    const data = await response.json();
    if (data.status && data.status !== 'ok') {
      throw new Error(data.error || `Request failed: ${path}`);
    }
    return pick ? pick(data) : data;
  } catch (error) {
    console.error(`Error fetching ${path}:`, error);
    throw error;
  }
}

export function getAllStocks() {
  return cached('stocks', () => getJson('/api/stocks', (d) => d.stocks));
}

export function getStockInfo(ticker) {
  return cached(`stock:${ticker}`, () =>
    getJson(`/api/stocks/${ticker}/info`, (d) => d.info)
  );
}

export function getPromptData(ticker) {
  return cached(`prompt:${ticker}`, () =>
    getJson(`/api/stocks/${ticker}/prompt`, (d) => d.data)
  );
}

// Portfolio Management Functions
export function getAccountInfo() {
  return cached('account', () => getJson('/api/account', (d) => d.account));
}

export function getPositions() {
  return cached('positions', () => getJson('/api/positions', (d) => d.positions));
}

export function getHistory(timeframe = 'ytd') {
  return cached(`history:${timeframe}`, () =>
    getJson(`/api/history?timeframe=${timeframe}`)
  );
}

export function getOrderHistory() {
  return cached('orders', () => getJson('/api/history/orders', (d) => d.orders));
}

export function getActivityHistory() {
  return cached('activities', () =>
    getJson('/api/history/activities', (d) => d.activities)
  );
}

export function getPortfolioAnalysis({ force = false } = {}) {
  return cached('portfolio-analysis', () => getJson('/portfolio-analysis'), { force });
}

// Performance Statistics Functions
export function getPerformanceSummary(params = {}) {
  const queryParams = new URLSearchParams();
  if (params.since) queryParams.append('since', params.since);
  if (params.weeks) queryParams.append('weeks', params.weeks);
  if (params.rf_annual !== undefined) queryParams.append('rf_annual', params.rf_annual);
  if (params.boots) queryParams.append('boots', params.boots);
  const query = queryParams.toString();

  return cached(`performance:${query}`, () =>
    getJson(`/api/performance/summary?${query}`, (d) => d.performance)
  );
}

export function getPerformanceQuick() {
  return cached('performance:quick', () =>
    getJson('/api/performance/quick', (d) => d.quick_stats)
  );
}

export function getTreasuryRate() {
  return cached('treasury-rate', () => getJson('/api/treasury-rate'));
}
