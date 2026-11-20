# Tender Radar

Find, classify and rank **AI and digital-transformation tenders** across 10 target categories,
then decide fast whether to bid.

| Key | Target category |
|-----|-----------------|
| `genai` | AI / Generative AI implementation |
| `chatbot` | Chatbots and AI assistants |
| `automation` | Automation and workflow digitization |
| `analytics` | Data analytics and dashboards |
| `ocr` | OCR / document processing |
| `surveillance` | AI-based monitoring and surveillance analytics |
| `software` | Software development with AI integration |
| `poc` | PoC / pilot projects |
| `smartcity` | Smart city and citizen services |
| `modernization` | IT modernization projects that can include AI |

## What's in the project

```
config/categories.toml        keyword taxonomy + scoring weights (edit to tune, no code changes)
tender_radar/                 the engine: sources → dedupe → classify → flag → filter → rank → report
  sources/                    CSV, JSON, RSS/Atom loaders (auto-detected by extension / URL)
  classifier.py               transparent keyword scoring, every score is explainable
  pipeline.py                 dedupe, urgent/expired/pilot/multi-fit flags, filters, ranking
  report.py                   terminal table, CSV (bid tracker), JSON, interactive HTML dashboard
  cli.py                      `tender-radar scan | explain | categories`
data/sample_tenders.csv       20 fictional tenders (16 relevant + 4 decoys) for a demo
docs/category-playbooks.md    per-category solution blueprint, proposal checklist, pre-bid questions
docs/bid-no-bid-checklist.md  32-point go / no-go scorecard
tests/                        pytest suite
```

No third-party dependencies; Python 3.11+.

## Quick start

```bash
pip install -e .            # or just use: python -m tender_radar ...
tender-radar scan data/sample_tenders.csv --html out/report.html --csv out/report.csv
open out/report.html
```

```
Score  Category                      Days  Value      Title
35.1   OCR / document processing     38    ₹3.80 Cr   AI-based OCR and intelligent document processing of land rec…
33.9   Data analytics and dashboard  30    ₹2.10 Cr   Development of real-time dashboard and data analytics platfo…
33.5   Chatbots and AI assistants    5     ₹1.20 Cr   Selection of agency for AI chatbot and voice bot on WhatsApp…
…
```

### Common commands

```bash
# Only pilots and chatbots, worth at least ₹50 lakh
tender-radar scan exports/*.csv -c poc -c chatbot --min-value 5000000

# Many sources at once (CSV/JSON/XML paths or feed URLs, one per line)
cp sources.example.txt sources.txt && tender-radar scan sources.txt --html out/report.html

# Why did this tender score 31.2?
tender-radar explain data/sample_tenders.csv --id DEMO-006

# List categories and weights
tender-radar categories
```

## Feeding it real tenders

Export search results from the portals you use (GeM, CPPP / eProcure, state e-procurement portals,
paid aggregators) as CSV or JSON, or point it at an RSS/Atom feed. Column names are matched loosely,
for example `title` / `tender title` / `work description`, `deadline` / `bid end date` / `closing date`,
`value` / `estimated value` / `tender value`. Values like `4.5 Cr`, `85 lakh` or `45,00,000` and most
Indian date formats are understood.

## Scoring

- Each category has `keywords` (1 pt), `strong` phrases (3 pts) and `exclude` phrases (−4 pts).
- Matches in the **title** count double. The category `weight` sets business priority (GenAI 1.5×, chatbots and pilots 1.4×, …).
- Tender score = best category + 25 % of other matching categories (rewards multi-category AI scope).
- `global_exclude` drops pure civil works, furniture, stationery, housekeeping, etc.
- Flags: **urgent** (closes within `urgent_days`), **pilot**, **multi-fit** (3+ categories), **expired** (hidden by default).

Tune everything in `config/categories.toml`; run `tender-radar explain` to see the effect.

## Workflow

1. **Daily:** export portal searches, then `tender-radar scan sources.txt --html … --csv …`
2. **Triage:** open the dashboard and filter by category or the *urgent* flag.
3. **Qualify:** run promising tenders through `docs/bid-no-bid-checklist.md`.
4. **Respond:** start the proposal from the matching section of `docs/category-playbooks.md`.
5. **Track:** import the CSV into your bid tracker or CRM.

## Web app (Vercel)

`api/index.py` is a Vercel Python function that serves the dashboard. `vercel.json` routes every path to it.

- `GET /` shows the demo tenders, scored against today's date.
- Upload a CSV / JSON / RSS export in the page to scan your own tenders. Files are processed in memory and not stored.
- `GET /health` is a liveness check.

The Vercel project is linked to this GitHub repository, so every push redeploys.
Run it locally with `vercel dev`, or use the CLI as above.

## Tests

```bash
python -m pytest
```
