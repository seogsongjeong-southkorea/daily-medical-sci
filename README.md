# Top Medical Journal Online-First Briefing

Streamlit app for a recent 7-day briefing across JAMA, Lancet, BMJ, and NEJM families.

## What this app does
- Pulls recent articles from configured publisher RSS feeds.
- Tries to enrich each item with public Crossref metadata when a DOI is available.
- Prioritizes **published-online** dates when available.
- Shows **First online**, **Issue / print**, **Best available date**, and **Date source**.
- Builds short paper cards with:
  - likely trend relevance
  - likely journal fit
  - result / conclusion summary
  - caution note
- Adds a weekly trend summary from the current 7-day window.

## Project structure
- `app.py` — main Streamlit app
- `data/journals.yaml` — journal families and RSS sources
- `utils/journal_data.py` — feed fetching, DOI extraction, Crossref enrichment, date logic
- `utils/scoring.py` — trend tags, design signals, summary text, trend clustering
- `.streamlit/config.toml` — Streamlit configuration
- `requirements.txt` — Python dependencies

## Local run
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit Community Cloud
1. Create a GitHub repository.
2. Upload all files in this folder.
3. Go to Streamlit Community Cloud.
4. Connect your GitHub account.
5. Choose the repository and set the entry point to `app.py`.
6. Deploy.

## Notes
- This app uses public publisher RSS metadata and public Crossref enrichment when available.
- The “why this seems timely” and “why it may fit the journal” text is interpretive and should not be read as the actual editor decision rationale.
- Feed coverage and date completeness can vary by journal.
