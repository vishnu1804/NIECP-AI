"""Government Query Translator (Master Upgrade Prompt §21).

For DEMO or USER_ENTERED government queries:

    ORIGINAL QUERY
    → PLAIN LANGUAGE EXPLANATION
    → WHAT IS MISSING?
    → WHAT INFORMATION/DOCUMENT IS NEEDED?
    → RECOMMENDED ACTION
    → RESPONSE PREPARATION
    → USER CONFIRMATION (the router gates the actual response submission)

Deterministic: the decomposition and document mapping come from the project's
real state (approval requirements, missing documents, knowledge base). The
output is explicitly labelled:

    "AI-generated explanation — verify against the official communication."

NIECP-AI never invents government queries — queries enter the system only
through user recording (source USER_PROVIDED) or the labelled demo engine
(source DEMO).
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..enums import SourceStatus
from .readiness import documents_readiness

DISCLAIMER = "AI-generated explanation — verify against the official communication."

# keyword → document hint (deterministic mapping used for "what is needed")
_DOC_HINTS: list[tuple[str, str]] = [
    ("water balance", "Water balance diagram"),
    ("effluent", "Effluent details / ETP drawings"),
    ("etp", "Effluent treatment plant (ETP) details"),
    ("stack", "Stack emission details"),
    ("emission", "Air emission control details"),
    ("consent", "Existing consent order copy"),
    ("land", "Land documents (sale deed / lease / allotment)"),
    ("fire", "Fire safety documents / NOC"),
    ("employee", "Employee / HR records"),
    ("wage", "Wage register details"),
    ("analytical", "Accredited laboratory analysis report"),
    ("laboratory", "Accredited laboratory analysis report"),
    ("lab", "Accredited laboratory analysis report"),
    ("lab report", "Accredited laboratory analysis report"),
    ("layout", "Site / layout plan"),
    ("site plan", "Site / layout plan"),
    ("compliance", "Compliance report"),
    ("authorization", "Authorisation application / certificate"),
    ("hazardous", "Hazardous waste authorisation details"),
    ("battery", "Battery waste / EPR registration details"),
    ("e-waste", "E-waste authorisation details"),
    ("boiler", "Boiler certificate / inspection documents"),
    ("udyam", "Udyam registration certificate"),
    ("pan", "PAN card"),
    ("gstin", "GST registration certificate"),
    ("incorporat", "Certificate of Incorporation"),
    ("turnover", "Financial statements / turnover proof"),
    ("investment", "Project cost / investment proof"),
]


def _decompose(text: str) -> list[str]:
    """Split the official communication into individual asks."""
    lines = [ln.strip() for ln in re.split(r"[\n;]|(?:\s\d+\.\s)|(?:\s\(\w\)\s)", text or "") if len(ln.strip()) > 8]
    items: list[str] = []
    for line in lines[:10]:
        cleaned = re.sub(r"^\[?[0-9]+[\)\.\-]?\]?\s*", "", line).strip()
        cleaned = cleaned.lstrip("-•* ").strip()
        if cleaned:
            items.append(cleaned[:240])
    if not items and text:
        items = [text.strip()[:240]]
    return items


def _needed_documents(asks: list[str], db: Session, project: models.Project) -> list[dict[str, Any]]:
    """Map each ask to concrete, project-grounded needs."""
    joined = " ".join(asks).lower()
    needed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for kw, doc in _DOC_HINTS:
        if kw in joined and doc.lower() not in seen:
            seen.add(doc.lower())
            needed.append({"document": doc, "match_reason": f"the query mentions “{kw}”"})
    # ground against the approval's own unsatisfied mandatory requirements
    for approval in project.approvals:
        for req in approval.requirements:
            if req.is_mandatory and not req.is_satisfied:
                title = req.title
                if any(word in joined.lower() for word in title.lower().split()[:4]) and title.lower() not in seen:
                    seen.add(title.lower())
                    needed.append({"document": title, "match_reason": f"listed as a pending requirement of {approval.name}"})
    # and against documents the project is actually missing
    docs = documents_readiness(db, project)
    for missing in (docs.get("missing") or [])[:8]:
        title = missing if isinstance(missing, str) else missing.get("title", "")
        if title and any(w in joined.lower() for w in title.lower().split()[:3]) and title.lower() not in seen:
            seen.add(title.lower())
            needed.append({"document": title, "match_reason": "missing from your project's document set"})
    return needed[:10]


def translate(db: Session, *, query: models.GovernmentQuery, project: models.Project) -> dict[str, Any]:
    """Produce the full §21 translation for a recorded/demo query."""
    original = query.query_text or ""
    asks = _decompose(original)
    needed = _needed_documents(asks, db, project)
    missing = [n["document"] for n in needed] or [
        "The specific item the authority names — re-read the official communication and record it if not listed here"
    ]

    plain = (
        f"The authority's communication contains {len(asks)} request(s). "
        + " ".join(f"It asks you to: {a}." for a in asks[:5])
        + (
            " No deadline is recorded — confirm the deadline with the authority instead of assuming one."
            if not query.deadline
            else f" The recorded deadline is {query.deadline.isoformat()}."
        )
    )

    steps = [
        "Separate each ask into its own response point (use the authority's numbering)",
        "Attach the exact document/information each point asks for — not extra material",
        "Check every figure against your application for consistency before sending",
        "Draft a point-by-point reply on your letterhead, signed by the authorised signatory",
        "File the response through the channel the authority specified and keep the acknowledgement",
        "Record the response and the new application status here (self-reported, with evidence)",
    ]
    draft_outline = [
        {"point": i + 1, "original_ask": ask, "response_slot": "[Your point-by-point reply]", "enclosure": needed[i]["document"] if i < len(needed) else "[Enclosure, if any]"}
        for i, ask in enumerate(asks[:8])
    ]
    recommended = (
        f"Prepare {len(needed) if needed else 'the requested'} document(s) listed under “What is needed”, "
        "then file a point-by-point response before the deadline."
        if needed
        else "Read the official communication carefully, then file a point-by-point response before the deadline."
    )

    return {
        "original_query": original,
        "plain_language_explanation": plain,
        "what_is_missing": missing,
        "what_is_needed": needed,
        "recommended_action": recommended,
        "response_preparation": {"steps": steps, "draft_outline": draft_outline},
        "asks": asks,
        "source_status": SourceStatus.AI_INTERPRETATION.value,
        "disclaimer": DISCLAIMER,
        "is_demo": bool(query.is_demo),
        "note": (
            "This query was generated by the NIECP demo engine (synthetic)."
            if query.is_demo
            else "This query was recorded by you from an official communication (USER_ENTERED)."
        ),
    }
