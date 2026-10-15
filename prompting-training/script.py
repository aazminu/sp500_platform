# %%
pip install --quiet --upgrade torch==2.1.0+cu118 torchvision==0.16.0+cu118 torchaudio==2.1.0+cu118 --extra-index-url https://download.pytorch.org/whl/cu118 typing_extensions bitsandbytes transformers peft accelerate psycopg2-binary pandas tqdm


# %%
 
import os
import json
import pandas as pd
from tqdm.notebook import tqdm
import torch
from datetime import datetime, timedelta

from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import PeftModel

# Chat-format tokens
B_INST, E_INST = "[INST]", "[/INST]"
B_SYS,  E_SYS  = "<<SYS>>\n", "\n<</SYS>>\n\n"

# 2) Updated SYSTEM_PROMPT for strict JSON output
SYSTEM_PROMPT = (
 "You are a portfolio optimization assistant.\n\n"
    "For a given stock snapshot, recommend how the allocation should be adjusted.\n"
    "Your response MUST be valid JSON matching this schema:\n"
    "{\n"
    '  "ticker": "<string>",\n'
    '  "snapshot": "<YYYY-MM-DD>",\n'
    '  "verdict":    "<Increase|Decrease|Hold|Add|Remove>",\n'
    '  "new_alloc_pct": <number>,\n'
    '  "reasoning":  "<short explanation>"\n'
    "}\n"
    "Example 1:\n"
    "{\n"
    '  "ticker": "AAPL",\n'
    '  "snapshot": "2023-01-15",\n'
    '  "verdict": "Increase",\n'
    '  "new_alloc_pct": 1.75,\n'
    '  "reasoning": "Strong earnings beat and positive guidance support a higher weight."\n'
    "}\n\n"
   " Do not include any extra keys or commentary."
    "At the end, emit only the JSON, no prose, no brackets, no commentary"
)

# %%
# Cell 3 — Load CSVs and pick one ticker
import json
import pandas as pd
tickers_df    = pd.read_csv("tickers.csv", parse_dates=["date_added"])
prices_df     = pd.read_csv("prices.csv", parse_dates=["price_date"])
labels_df     = pd.read_csv("analyst_labels.csv", parse_dates=["label_date"])
estimates_df  = pd.read_csv("analyst_estimates.csv", parse_dates=["report_date"])
grades_df     = pd.read_csv("grades_historical.csv", parse_dates=["rating_date"])
metrics_df    = pd.read_csv("key_metrics.csv", parse_dates=["date"])
profiles_df   = pd.read_csv("profiles.csv", converters={"profile_data": lambda x: json.loads(x)})
news_df       = pd.read_csv("stock_news.csv", parse_dates=["published_date"])
allocations_df= pd.read_csv("allocations.csv", parse_dates=["allocation_date"])

# Quick sanity-check
print("Tickers:",      tickers_df.shape)
print("Prices:",       prices_df.shape)
print("Labels:",       labels_df.shape)
print("Estimates:",    estimates_df.shape)
print("Grades:",       grades_df.shape)
print("Metrics:",      metrics_df.shape)
print("Profiles:",     profiles_df.shape)
print("News:",         news_df.shape)
print("Allocations:", allocations_df.shape)
unique_tickers = allocations_df['ticker'].str.strip().str.upper().unique()


# Print the total count
print("Total unique tickers:", len(unique_tickers))

# %%

def summarize_grades(ticker, upto):
    sub = grades_df[(grades_df.symbol==ticker) & (grades_df.rating_date <= upto)].tail(12)
    if sub.empty:
        return {}
    totals = sub[["analyst_ratings_buy","analyst_ratings_hold","analyst_ratings_sell"]].sum()
    pct = (totals / totals.sum() * 100).round(1).to_dict()
    return {
      "avg_buy_pct": pct["analyst_ratings_buy"],
      "avg_hold_pct": pct["analyst_ratings_hold"],
      "avg_sell_pct": pct["analyst_ratings_sell"]
    }

def get_latest_metric(ticker):
    sub = metrics_df[metrics_df.ticker==ticker].sort_values("date", ascending=False)
    if sub.empty:
        return {}
    r = sub.iloc[0]
    metrics = r.metrics
    if isinstance(metrics, str):
        metrics = json.loads(metrics)
    return metrics

def _compute_price_stats(df, since, upto):
    sub = df[(df.price_date >= since) & (df.price_date <= upto)]
    if len(sub) < 2:
        return {}
    change = (sub.close_price.iloc[-1] / sub.close_price.iloc[0] - 1) * 100
    return {
      "change_pct": round(change,2),
      "volatility": round(sub.close_price.pct_change().std()*100,2),
      "avg_vol": int(sub.volume.mean())
    }

def _top_news(df, since, upto, n=2):
    sub = df[(df.published_date >= since) & (df.published_date <= upto)]
    sub = sub.sort_values("published_date", ascending=False).head(n)
    return [
      {"title": r.title, "date": r.published_date.date().isoformat()}
      for _, r in sub.iterrows()
    ]

def _latest_label(ticker, upto):
    sub = labels_df[(labels_df.ticker==ticker) & (labels_df.label_date <= upto)]
    sub = sub.sort_values("label_date", ascending=False)
    if sub.empty:
        return {}
    r = sub.iloc[0]
    return {"rating": r.rating, "score": r.overall_score}

def _latest_estimate(ticker, upto):
    sub = estimates_df[(estimates_df.symbol==ticker) & (estimates_df.report_date <= upto)]
    sub = sub.sort_values("report_date", ascending=False)
    if sub.empty:
        return {}
    e = sub.iloc[0]
    return {"eps_avg": round(e.eps_avg,2), "rev_avg": int(e.revenue_avg)}


def get_previous_allocation(ticker, upto):
    # 1) Parse upto into a Timestamp
    upto_ts = pd.to_datetime(upto)

    # 2) Ensure the column is datetime
    if allocations_df['allocation_date'].dtype != 'datetime64[ns]':
        allocations_df['allocation_date'] = pd.to_datetime(
            allocations_df['allocation_date']
        )

    # 3) Filter
    mask = (
        (allocations_df['ticker'] == ticker) &
        (allocations_df['allocation_date'] <= upto_ts)
    )
    matched = allocations_df.loc[mask]

    print(f"Found {len(matched)} prior allocations for {ticker} up to {upto_ts.date()}")

    if matched.empty:
        # no history — return 0.0% or whatever default you prefer
        return 150

    # 4) Sort and take the latest
    latest = matched.sort_values('allocation_date', ascending=False).iloc[0]
    frac = float(latest['allocation_pct'])    # e.g. 0.000123
    pct  = frac * 100                         # → 0.0123%

    # 5) Preserve precision
    return round(pct, 4)
    
get_previous_allocation("MSFT", "2025-03-16")

# %%
from datetime import datetime, timedelta
def build_blocks(ticker, snapshot_date):
    blocks = {}
    # weekly window
    since = snapshot_date - timedelta(days=7)
    blocks["weekly"] = {
        "stats": _compute_price_stats(prices_df[prices_df.ticker==ticker], since, snapshot_date),
        "news": _top_news(news_df[news_df.symbol==ticker], since, snapshot_date)
    }
    # quarterly window
    since = snapshot_date - timedelta(days=90)
    blocks["quarterly"] = {
        "stats": _compute_price_stats(prices_df[prices_df.ticker==ticker], since, snapshot_date),
        "news": _top_news(news_df[news_df.symbol==ticker], since, snapshot_date)
    }
    # yearly window
    since = snapshot_date - timedelta(days=365)
    blocks["yearly"] = {
        "stats": _compute_price_stats(prices_df[prices_df.ticker==ticker], since, snapshot_date),
        "news": []  # drop news for yearly to save tokens
    }
    return blocks

# %%

# 5) Full prompt now takes snapshot_date
import json  # make sure this is imported
def build_full_prompt(ticker, snapshot_date):
    prof       = profiles_df[profiles_df.ticker==ticker].profile_data.iloc[0]
    prev_alloc = round(get_previous_allocation(ticker, snapshot_date), 2)
    blocks     = build_blocks(ticker, snapshot_date)
    payload = {
        "ticker": ticker,
        "snapshot": snapshot_date.date().isoformat(),
        "previous_allocation_pct": prev_alloc,
        "profile_summary": prof.get("sector",""),
        "weekly": blocks["weekly"],
        "quarterly": blocks["quarterly"],
        "yearly_return_pct": blocks["yearly"]["stats"].get("change_pct"),
        "latest_label": _latest_label(ticker, snapshot_date),
        "latest_est": _latest_estimate(ticker, snapshot_date),
        "grades_summary": summarize_grades(ticker, snapshot_date),
        "key_metrics": get_latest_metric(ticker)
    }
    user_prompt = f"DATA:\n{json.dumps(payload)}\n\nPlease produce the JSON response."
    return f"{B_INST} {B_SYS}{SYSTEM_PROMPT}{E_SYS}{user_prompt}{E_INST}"

# Test
print(build_full_prompt("AAPL", pd.to_datetime("2025-04-10")))

# %%
import os; os.environ["HF_TOKEN"] = ""
!pip install --quiet huggingface_hub && huggingface-cli login --token "$HF_TOKEN"

# %%
# Cell X — Load model in FP16 (requires ~14 GB VRAM)
# Cell X — Load model in FP16 (requires ~14 GB VRAM)
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft         import PeftModel

# 1) Tokenizer
tokenizer = AutoTokenizer.from_pretrained(
    "meta-llama/Llama-2-7b-chat-hf",
    trust_remote_code=True
)
tokenizer.pad_token = tokenizer.eos_token

# 2) Base model in FP16
base = AutoModelForCausalLM.from_pretrained(
    "meta-llama/Llama-2-7b-chat-hf",
    device_map="auto",
    torch_dtype=torch.float16,
    trust_remote_code=True
)

# 3) Attach your LoRA adapter
model = PeftModel.from_pretrained(
    base,
    "FinGPT/fingpt-forecaster_dow30_llama2-7b_lora",
    torch_dtype=torch.float16,
    trust_remote_code=True
)

model.eval()

max_ctx = model.config.max_position_embeddings
print(f"Context window is {max_ctx} tokens")
model.eval()


# %%
import re
import json
from IPython.display import display, Markdown
from transformers import GenerationConfig

def clean_and_extract_json(raw: str) -> dict:
    # 1) Remove any "[$]" markers
    cleaned = raw.replace('[$]', '')
    # 2) Extract the first JSON object (non-greedy)
    m = re.search(r'(\{.*?\})', cleaned, re.DOTALL)
    if not m:
        raise ValueError("No JSON object found in cleaned text")
    json_str = m.group(1)
    # 3) Parse to dict (to validate and remove stray whitespace)
    return json.loads(json_str)


gen_config = GenerationConfig(
     max_new_tokens = 1024,
#    min_new_tokens=512,
    do_sample=False,
    temperature=0.0,
    top_p=1.0,
    repetition_penalty=1.0,
    eos_token_id=tokenizer.eos_token_id,
    pad_token_id=tokenizer.eos_token_id,
)

tickers_list = tickers_df['ticker'].unique()

OUTFILE = "output.csv"
first_write = not os.path.exists(OUTFILE)
today = pd.to_datetime("today").normalize()
three_years_ago = today - pd.Timedelta(days=365*3)
snapshot_dates = [
        three_years_ago,
        three_years_ago + pd.Timedelta(days=365),
        three_years_ago + pd.Timedelta(days=365*2),
    ]

for ticker in tickers_list:
    results = []
   
    for sd in tqdm(snapshot_dates, desc=f"Snapshots for {ticker}"):
        prompt = build_full_prompt(ticker, sd)
        inputs = tokenizer(
            prompt, return_tensors="pt", truncation=True,
            max_length=model.config.max_position_embeddings,
            padding="longest"
        )
        if torch.cuda.is_available():
            inputs = {k: v.to(model.device) for k, v in inputs.items()}
    
        tokens = tokenizer.encode(prompt)
        print(f"\nSnapshot {sd.date().isoformat()} — Prompt uses {len(tokens)} tokens "
              f"({len(tokens)/max_ctx*100:.1f}% of window)\n")
    
       
        
        out_ids = model.generate(
                **inputs,
                generation_config=gen_config,
                use_cache=True
            )
            
        raw = tokenizer.decode(out_ids[0], skip_special_tokens=True)
        cleaned = raw.replace("[$]", "")
        body = cleaned.split(E_INST, 1)[-1].strip()
        print(f"Raw response attempt: {repr(body)}")
    
        try:
            obj = clean_and_extract_json(raw)
            resp = json.dumps(obj, indent=2)
        except Exception:
            resp = body
        
        print("Response JSON:\n", resp)
        display(Markdown(f"```json\n{resp}\n```"))
        results.append({
            "ticker": ticker,
            "snapshot": sd.date().isoformat(),
            "prompt": prompt,
            "response": resp
        })
    df = pd.DataFrame(results)
    df.to_csv(
            OUTFILE,
            mode="a",
            header=first_write,  # only write header once
            index=False
        )
    first_write = False
    print(f"✅ Appended {len(results)} rows for {ticker} to {OUTFILE}")

# %%


# %%



