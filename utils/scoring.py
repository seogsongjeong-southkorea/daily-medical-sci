from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Tuple

TREND_KEYWORDS = {
    "AI / digital health": ["artificial intelligence", "machine learning", "digital", "algorithm", "foundation model", "large language model", " ai "],
    "Obesity / metabolic health": ["obesity", "metabolic", "glp-1", "semaglutide", "tirzepatide", "masld", "nafld", "mash"],
    "Cancer": ["cancer", "tumor", "oncology", "carcinoma", "survival"],
    "Cardiovascular": ["heart", "cardiovascular", "atrial fibrillation", "stroke", "myocardial", "hypertension", "heart failure"],
    "Mental health": ["depression", "anxiety", "mental health", "suicide", "psychiatr"],
    "Infectious disease": ["infection", "vaccine", "virus", "bacterial", "antimicrobial", "sepsis", "covid"],
    "Aging / longevity": ["aging", "older adults", "longevity", "frailty", "geriatric"],
    "Health policy / equity": ["policy", "equity", "disparit", "access", "cost", "coverage", "public health"],
    "Women's health": ["pregnan", "maternal", "women", "gyne", "obstetric"],
}

DESIGN_SIGNALS = {
    "Randomized trial": ["randomized", "randomised", "trial", "placebo"],
    "Large observational study": ["cohort", "registry", "nationwide", "population-based", "retrospective", "prospective"],
    "Systematic review": ["systematic review", "meta-analysis"],
    "Guideline / consensus": ["guideline", "consensus", "recommendation", "statement"],
}

NOVELTY_SIGNALS = [
    ("practice-changing potential", ["randomized", "multicenter", "phase 3", "placebo-controlled"]),
    ("large-scale evidence", ["nationwide", "population-based", "registry", "multi-country", "global"]),
    ("timely policy relevance", ["equity", "cost", "policy", "access", "burden"]),
    ("high translational interest", ["biomarker", "precision", "genomic", "mechanism", "platform"]),
]

LIMITATION_SIGNALS = [
    ("observational design may limit causal interpretation", ["observational", "retrospective", "cohort", "cross-sectional"]),
    ("abstract-level summary may omit key methodological details", []),
    ("early translational findings may need external validation", ["pilot", "phase 1", "feasibility", "preclinical"]),
]


def _text_blob(title: str, abstract: str) -> str:
    return f" {title} {abstract} ".lower()


def pick_trend_tags(title: str, abstract: str) -> List[str]:
    text = _text_blob(title, abstract)
    hits: List[Tuple[str, int]] = []
    for label, keywords in TREND_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text)
        if score:
            hits.append((label, score))
    hits.sort(key=lambda x: x[1], reverse=True)
    return [label for label, _ in hits[:3]]


def detect_design(text: str) -> str:
    lower = text.lower()
    scores = Counter()
    for label, keywords in DESIGN_SIGNALS.items():
        for kw in keywords:
            if kw.lower() in lower:
                scores[label] += 1
    return scores.most_common(1)[0][0] if scores else "Unclear from abstract"


def novelty_summary(title: str, abstract: str, journal: str, family: str) -> str:
    text = _text_blob(title, abstract)
    reasons = []
    for label, keywords in NOVELTY_SIGNALS:
        if any(kw.lower() in text for kw in keywords):
            reasons.append(label)
    tags = pick_trend_tags(title, abstract)
    if tags:
        reasons.append(f"alignment with current themes such as {', '.join(tags[:2])}")
    if not reasons:
        reasons.append("topic-level relevance to current clinical and policy conversations")
    reason_text = ", ".join(reasons[:2])
    if family == "Lancet":
        fit = "broad international relevance and public-health visibility"
    elif family == "JAMA":
        fit = "strong clinical readership fit and likely practice-facing interest"
    elif family == "BMJ":
        fit = "policy, evidence-translation, or health-services relevance"
    else:
        fit = "high general-medicine salience"
    return f"Likely notable because of {reason_text}; it also fits {journal}'s editorial profile through {fit}."


def result_conclusion_summary(title: str, abstract: str) -> str:
    text = re.sub(r"\s+", " ", abstract).strip()
    if not text:
        return "No abstract was available from feed metadata or Crossref, so the result and conclusion need manual review on the publisher page."
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chosen = []
    for sent in sentences:
        if len(sent) < 35:
            continue
        chosen.append(sent.strip())
        if len(chosen) == 2:
            break
    if not chosen:
        chosen = [text[:320] + ("..." if len(text) > 320 else "")]
    return " ".join(chosen)


def limitations_summary(title: str, abstract: str) -> str:
    text = _text_blob(title, abstract)
    points = []
    for label, keywords in LIMITATION_SIGNALS:
        if not keywords or any(kw.lower() in text for kw in keywords):
            points.append(label)
    unique = []
    for p in points:
        if p not in unique:
            unique.append(p)
    return "; ".join(unique[:2])


def article_type_guess(title: str, abstract: str, article_type: str) -> str:
    if article_type:
        return article_type.replace("-", " ").title()
    text = _text_blob(title, abstract)
    design = detect_design(text)
    return design


def trend_cluster_summary(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    tag_counter = Counter()
    design_counter = Counter()
    family_counter = Counter()
    for row in rows:
        for tag in row.get("trend_tags_list", []):
            tag_counter[tag] += 1
        design_counter[row.get("Study Design Signal", "Unclear")] += 1
        family_counter[row.get("Family", "Unknown")] += 1

    summaries: List[Dict[str, str]] = []
    for tag, count in tag_counter.most_common(5):
        top_design = design_counter.most_common(1)[0][0] if design_counter else "mixed designs"
        summaries.append(
            {
                "tag": tag,
                "count": str(count),
                "summary": f"{tag} appeared repeatedly across this 7-day window, often with {top_design.lower()} signals and cross-journal visibility.",
            }
        )
    return summaries
