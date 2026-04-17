from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from utils.journal_data import fetch_articles, load_journal_config
from utils.scoring import (
    article_type_guess,
    detect_design,
    limitations_summary,
    novelty_summary,
    pick_trend_tags,
    result_conclusion_summary,
    trend_cluster_summary,
)

APP_DIR = Path(__file__).parent
CONFIG_PATH = APP_DIR / "data" / "journals.yaml"

st.set_page_config(page_title="Top Medical Journal Online-First Briefing", page_icon="🩺", layout="wide")


def fmt_dt(dt):
    return dt.strftime("%Y-%m-%d") if dt else "N/A"


st.title("🩺 Top Medical Journal Online-First Briefing")
st.caption("Recent 7-day online-first style briefing for JAMA, Lancet, BMJ, and NEJM families.")

with st.sidebar:
    st.header("Filters")
    journals = load_journal_config(str(CONFIG_PATH))
    families = sorted({j["family"] for j in journals})
    selected_families = st.multiselect("Journal families", families, default=families)
    family_journals = [j["journal"] for j in journals if j["family"] in selected_families]
    selected_journals = st.multiselect("Specific journals", family_journals, default=family_journals)
    days_back = st.slider("Recent online publication window (days)", min_value=1, max_value=30, value=7)
    keyword = st.text_input("Topic keyword filter", placeholder="e.g. MASLD, depression, AI")
    show_only_with_abstract = st.checkbox("Show only items with abstract text", value=False)
    show_only_with_doi = st.checkbox("Show only items with DOI", value=False)
    max_items = st.slider("Maximum papers", min_value=10, max_value=300, value=60, step=10)
    refresh = st.button("Refresh now")


@st.cache_data(ttl=3600, show_spinner=False)
def get_payload(days_back: int):
    journal_cfg = load_journal_config(str(CONFIG_PATH))
    return fetch_articles(journal_cfg, days_back=days_back)


if refresh:
    get_payload.clear()

with st.spinner("Fetching recent papers and building the weekly briefing..."):
    payload = get_payload(days_back)

raw_articles = payload["articles"]
journal_status = payload["journal_status"]

rows = []
for art in raw_articles:
    if art["family"] not in selected_families or art["journal"] not in selected_journals:
        continue
    text_blob = f"{art['title']} {art['abstract']} {art['journal']} {' '.join(art.get('subjects', []))}".lower()
    if keyword and keyword.lower() not in text_blob:
        continue
    if show_only_with_abstract and not art["abstract"]:
        continue
    if show_only_with_doi and not art["doi"]:
        continue

    tags = pick_trend_tags(art["title"], art["abstract"])
    rows.append(
        {
            "Checked on": fmt_dt(art["checked_at"]),
            "First online": fmt_dt(art["published_online"]),
            "Issue / print": fmt_dt(art["published_print"]),
            "RSS date": fmt_dt(art["rss_date"]),
            "Best available date": fmt_dt(art["best_date"]),
            "Date source": art["date_source"],
            "Source mode": art.get("source_mode", "rss"),
            "Family": art["family"],
            "Journal": art["journal"],
            "Title": art["title"],
            "DOI": art["doi"],
            "Link": art["link"],
            "Article Type": article_type_guess(art["title"], art["abstract"], art["article_type"]),
            "Study Design Signal": detect_design(f"{art['title']} {art['abstract']}"),
            "Trend Tags": ", ".join(tags),
            "trend_tags_list": tags,
            "Why this seems timely": novelty_summary(art["title"], art["abstract"], art["journal"], art["family"]),
            "Result / conclusion summary": result_conclusion_summary(art["title"], art["abstract"]),
            "Cautions": limitations_summary(art["title"], art["abstract"]),
            "Abstract Available": bool(art["abstract"]),
        }
    )

brief_df = pd.DataFrame(rows).head(max_items)

st.markdown(
    f"Showing papers from the last **{days_back} days** based on the best available publication date, with priority given to **Crossref published-online**, then **published-print**, then **RSS published/updated**, and finally **Crossref created** when needed."
)

if brief_df.empty:
    st.warning("No papers matched the current filters.")
    st.dataframe(pd.DataFrame(journal_status), use_container_width=True, hide_index=True)
    st.stop()

trend_summaries = trend_cluster_summary(brief_df.to_dict("records"))
all_tags = [tag for tags in brief_df["trend_tags_list"].tolist() for tag in tags]

col1, col2, col3, col4 = st.columns(4)
col1.metric("Papers shown", len(brief_df))
col2.metric("With abstracts", int(brief_df["Abstract Available"].sum()))
col3.metric("Journals selected", len(selected_journals))
col4.metric("Trend signals", len(set(all_tags)))

st.info(
    "This app uses publisher RSS feeds plus Crossref fallback retrieval when a feed is empty or inaccessible. "
    "The sections on why a paper seems timely or why it may fit a journal are interpretive summaries, not the actual editor decision rationale."
)

family_counts = brief_df["Family"].value_counts().to_dict()
missing_families = [fam for fam in selected_families if family_counts.get(fam, 0) == 0]
if missing_families:
    st.error("No articles were recovered for: " + ", ".join(missing_families) + ". Check the recovery table below.")

with st.expander("Journal recovery status"):
    st.dataframe(pd.DataFrame(journal_status), use_container_width=True, hide_index=True)

left, right = st.columns([1.4, 1])
with left:
    st.subheader("This week's trend summary")
    if trend_summaries:
        for item in trend_summaries:
            st.markdown(f"**{item['tag']}** · {item['count']} papers")
            st.write(item["summary"])
    else:
        st.write("No clear repeated trend cluster was detected from the current set of papers.")

with right:
    st.subheader("Top recurring tags")
    if all_tags:
        tag_df = pd.Series(all_tags).value_counts().rename_axis("Trend").reset_index(name="Count")
        st.dataframe(tag_df, use_container_width=True, hide_index=True)
    else:
        st.write("No trend tags identified yet.")

st.subheader("Table view")
show_cols = [
    "Best available date",
    "First online",
    "Issue / print",
    "Date source",
    "Source mode",
    "Family",
    "Journal",
    "Title",
    "Article Type",
    "Study Design Signal",
    "Trend Tags",
    "Abstract Available",
]
st.dataframe(brief_df[show_cols], use_container_width=True, hide_index=True)

csv = brief_df.drop(columns=["trend_tags_list"]).to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "Download briefing as CSV",
    data=csv,
    file_name="top_medical_journal_online_first_briefing.csv",
    mime="text/csv",
)

st.subheader("Paper cards")
for _, row in brief_df.iterrows():
    with st.container(border=True):
        st.markdown(f"### [{row['Title']}]({row['Link']})")
        meta_cols = st.columns(6)
        meta_cols[0].markdown(f"**Journal**  \n{row['Journal']}")
        meta_cols[1].markdown(f"**First online**  \n{row['First online']}")
        meta_cols[2].markdown(f"**Issue / print**  \n{row['Issue / print']}")
        meta_cols[3].markdown(f"**Best date**  \n{row['Best available date']}")
        meta_cols[4].markdown(f"**Date source**  \n{row['Date source']}")
        meta_cols[5].markdown(f"**Recovered via**  \n{row['Source mode']}")

        meta_cols2 = st.columns(4)
        meta_cols2[0].markdown(f"**Checked on**  \n{row['Checked on']}")
        meta_cols2[1].markdown(f"**Type**  \n{row['Article Type']}")
        meta_cols2[2].markdown(f"**Design signal**  \n{row['Study Design Signal']}")
        meta_cols2[3].markdown(f"**Family**  \n{row['Family']}")

        if row["DOI"]:
            st.markdown(f"**DOI:** `{row['DOI']}`")
        if row["Trend Tags"]:
            st.markdown(f"**Trend tags:** {row['Trend Tags']}")

        st.markdown("**Why this seems timely / why it may fit the journal**")
        st.write(row["Why this seems timely"])

        st.markdown("**Result / conclusion summary**")
        st.write(row["Result / conclusion summary"])

        st.markdown("**Cautions**")
        st.write(row["Cautions"])

        if not row["Abstract Available"]:
            st.warning("No abstract was recovered from feed metadata or Crossref. Manual review on the publisher page is recommended.")
