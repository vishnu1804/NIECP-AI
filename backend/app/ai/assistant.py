"""
AI Assistant & Agent orchestration (spec §26, §28, §50, §51, §53).

The assistant is tool-using and grounded:
  1. deterministic intent detection (regex over the transcript/message);
  2. tools pulled from the *same* services the UI uses (rule engine, readiness,
     document inventory, scheme matching, calendar) — the assistant never has a
     private, divergent view of project state;
  3. retrieval against the curated corpus for regulatory grounding;
  4. composition of the structured answer (spec §51: Answer / Why / What you
     need / Source / Status / Next step), rendered locally by default so the
     platform is fully functional with zero external AI services;
  5. an optional external LLM (llm.py) may rephrase the composed answer, but the
     verdicts, numbers and sources come from the tools.

Voice commands (spec §28) map onto the same intents; sensitive actions return
`requires_confirmation` payloads and are never executed on speech alone.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..enums import (
    AgentName,
    AIMessageRole,
    Applicability,
    ApprovalNodeState,
    ApplicationStatus,
    Confidence,
    QueryStatus,
    SourceStatus,
)
from ..services import next_action as next_action_service
from ..services import readiness as readiness_service
from ..services.approval_engine import get_critical_path
from ..services.profile_facts import build_facts
from ..services.scheme_engine import evaluate_scheme_criteria
from . import llm
from .retrieval import retrieve

# ─────────────────────────────────────────────────────────────── intents ──
INTENT_PATTERNS: list[tuple[str, list[str]]] = [
    ("PENDING_APPROVALS", [r"pending approval", r"what approvals", r"approvals do i need", r"approval list", r"அனுமதி", r"स्वीकृति"]),
    ("MISSING_DOCUMENTS", [r"missing document", r"documents? (are )?missing", r"what document", r"upload what", r"checklist", r"ஆவண"]),
    ("NEXT_STEP", [r"what (should|do) i (do|next)", r"next step", r"next action", r"what now", r"அடுத்த", r"अगला"]),
    ("READINESS", [r"readiness", r"how ready", r"score", r"prepared", r"தயார்", r"तैयार"]),
    ("APPLICATIONS", [r"my applications", r"application status", r"show applications", r"submitted", r"விண்ணப்ப"]),
    ("EXPLAIN_APPROVAL", [r"why (do|is|would)", r"explain", r"why this", r"why i need", r"ஏன்", r"क्यों"]),
    ("SCHEMES", [r"scheme", r"subsidy", r"incentive", r"benefit", r"திட்ட", r"योजना"]),
    ("CALENDAR", [r"calendar", r"deadline", r"due date", r"renewal", r"expiry", r"நாட்காட்டி", r"कैलेंडर"]),
    ("COMPLIANCE_TASKS", [r"compliance", r"task", r"today", r"todo", r"to-do"]),
    ("OPEN_PORTAL", [r"open .*portal", r"official portal", r"website for"]),
    ("PROJECT_STATUS", [r"project status", r"status of (my )?project", r"how is my project"]),
    ("QUERIES", [r"quer(y|ies)", r"show cause", r"notice from", r"deficiency"]),
    ("INSPECTION", [r"inspection", r"site visit", r"officer visit"]),
    ("CRITICAL_PATH", [r"critical path", r"roadmap", r"sequence", r"order of"]),
    ("HELP", [r"help", r"what can you do", r"how do you work"]),
    ("LANGUAGE", [r"switch to (tamil|hindi|english)", r"தமிழில்", r"हिंदी में"]),
]

SENSITIVE_PATTERNS = [
    (r"\bsubmit\b.*\bapplication\b", "SUBMIT_APPLICATION"),
    (r"\bpay\b.*\bfee\b", "PAY_FEE"),
    (r"\bsend\b.*\bdocument(s)?\b.*\b(government|authority|department)\b", "SEND_DOCUMENTS"),
]


@dataclass
class AssistantAnswer:
    intent: str
    answer: str
    why: str | None = None
    what_you_need: list[str] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    status: str = "AI_INTERPRETATION"
    confidence: str = "MEDIUM"
    next_step: dict[str, Any] | None = None
    data: dict[str, Any] = field(default_factory=dict)
    requires_confirmation: dict[str, Any] | None = None
    used_llm: bool = False
    agent: str = AgentName.STRATEGIST.value

    def to_structured(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "answer": self.answer,
            "why": self.why,
            "what_you_need": self.what_you_need,
            "sources": self.sources,
            "status": self.status,
            "confidence": self.confidence,
            "next_step": self.next_step,
            "data": self.data,
            "requires_confirmation": self.requires_confirmation,
            "used_llm": self.used_llm,
            "agent": self.agent,
        }


def detect_intent(text: str) -> str:
    low = (text or "").lower().strip()
    if not low:
        return "UNKNOWN"
    for intent, patterns in INTENT_PATTERNS:
        for p in patterns:
            if re.search(p, low):
                return intent
    return "GENERAL"


def detect_sensitive(text: str) -> str | None:
    low = (text or "").lower()
    for pattern, action in SENSITIVE_PATTERNS:
        if re.search(pattern, low):
            return action
    return None


# ─────────────────────────────────────────────── project context builder ──
def project_context(db: Session, project: models.Project) -> dict[str, Any]:
    profile = project.profile
    facts = build_facts(project, profile)
    approvals = db.scalars(select(models.ProjectApproval).where(models.ProjectApproval.project_id == project.id)).all()
    active = [a for a in approvals if a.applicability in (Applicability.APPLIES, Applicability.CONDITIONAL) and not a.user_dismissed]
    docs = db.scalars(select(models.Document).where(models.Document.project_id == project.id)).all()
    apps = db.scalars(select(models.Application).where(models.Application.project_id == project.id)).all()
    return {
        "project_name": project.name,
        "industry": facts.get("_industry_name") or facts.get("industry_other_description"),
        "state": facts.get("state_code"),
        "district": facts.get("district"),
        "project_type": facts.get("project_type"),
        "total_investment": facts.get("total_investment"),
        "employees": facts.get("number_of_employees"),
        "applicable_approvals": [
            {"code": a.template_code, "name": a.name, "state": a.node_state.value if a.node_state else None}
            for a in active[:25]
        ],
        "documents_on_file": [{"title": d.title, "category": d.category.value if d.category else None} for d in docs[:20]],
        "applications": [{"title": a.title, "status": a.status.value if a.status else None} for a in apps[:10]],
    }


# ────────────────────────────────────────────────────────── tool handlers ──
def _tool_pending_approvals(db: Session, project: models.Project) -> AssistantAnswer:
    approvals = db.scalars(
        select(models.ProjectApproval)
        .where(models.ProjectApproval.project_id == project.id)
        .order_by(models.ProjectApproval.graph_layer)
    ).all()
    active = [a for a in approvals if a.applicability in (Applicability.APPLIES, Applicability.CONDITIONAL) and not a.user_dismissed]
    pending = [a for a in active if a.node_state not in (ApprovalNodeState.COMPLETED, ApprovalNodeState.APPROVED)]
    if not active:
        return AssistantAnswer(
            intent="PENDING_APPROVALS",
            answer="I have not run the approval analysis for this project yet. Run the analysis and I will map the approvals that may apply to your project.",
            why="No approval analysis has been run for this project.",
            status=SourceStatus.AI_INTERPRETATION.value,
            next_step={"action": "Run the AI project analysis", "link": f"/projects/{project.id}/analysis"},
        )
    lines = []
    for a in pending[:10]:
        state = a.node_state.value.replace("_", " ").title() if a.node_state else ""
        lines.append(f"• {a.name} — {state} ({a.authority})")
    answer = (
        f"{len(pending)} of {len(active)} potentially applicable approvals are still open:\n" + "\n".join(lines)
        if pending
        else "All potentially applicable approvals for this project are recorded as complete. Remember this reflects your own recorded status — the authority's records are the official ones."
    )
    if len(pending) > 10:
        answer += f"\n…and {len(pending) - 10} more."
    return AssistantAnswer(
        intent="PENDING_APPROVALS",
        answer=answer,
        why="This list comes from the deterministic rule-engine analysis of your project profile — each item shows why it applies on its approval card.",
        status=SourceStatus.REQUIRES_VERIFICATION.value,
        confidence=Confidence.HIGH.value,
        next_step={"action": "Open the approvals map", "link": f"/projects/{project.id}/approvals"},
        data={"pending": [a.template_code for a in pending], "total_active": len(active)},
        agent=AgentName.APPROVAL.value,
    )


def _tool_missing_documents(db: Session, project: models.Project) -> AssistantAnswer:
    from ..services.readiness import documents_readiness

    comp = documents_readiness(db, project)
    missing = comp.get("missing", [])
    if not comp.get("required_count"):
        return AssistantAnswer(
            intent="MISSING_DOCUMENTS",
            answer="Run the approval analysis first — it generates the document checklist from the approvals that may apply to your project.",
            next_step={"action": "Run analysis", "link": f"/projects/{project.id}/analysis"},
        )
    lines = [f"• {m['title']}  (for {m['approval']})" for m in missing[:8]]
    answer = (
        f"{comp['satisfied_count']} of {comp['required_count']} required documents are on file. Still outstanding:\n" + "\n".join(lines)
        if missing
        else "Every document required by your potentially applicable approvals is on file and linked."
    )
    if len(missing) > 8:
        answer += f"\n…and {len(missing) - 8} more."
    return AssistantAnswer(
        intent="MISSING_DOCUMENTS",
        answer=answer,
        why="Checked against your actual document repository and the checklists attached to each applicable approval.",
        status=SourceStatus.AI_INTERPRETATION.value,
        confidence=Confidence.HIGH.value,
        next_step={"action": "Open the document centre", "link": f"/projects/{project.id}/documents"},
        data={"missing_count": len(missing)},
        agent=AgentName.DOCUMENT.value,
    )


def _tool_next_step(db: Session, project: models.Project) -> AssistantAnswer:
    actions = next_action_service.next_best_actions(db, project, limit=4)
    if not actions:
        return AssistantAnswer(
            intent="NEXT_STEP",
            answer="Nothing is pending right now. Keep your profile current — I will flag the next action as soon as your project state changes.",
            status=SourceStatus.AI_INTERPRETATION.value,
        )
    first = actions[0]
    lines = [f"{i+1}. {a['title']} — {a['detail']}" for i, a in enumerate(actions)]
    return AssistantAnswer(
        intent="NEXT_STEP",
        answer="Here is what I recommend, in order:\n" + "\n".join(lines),
        why="Actions are generated from your actual project state: open queries, due renewals, missing documents, blocked approvals and staged applications.",
        status=SourceStatus.AI_INTERPRETATION.value,
        confidence=Confidence.HIGH.value,
        next_step={"action": first["title"], "link": (first["link"] or "").replace("{pid}", str(project.id)), "cta": first["cta"]},
        data={"actions": [{**a, "link": (a["link"] or "").replace("{pid}", str(project.id))} for a in actions]},
        agent=AgentName.STRATEGIST.value,
    )


def _tool_readiness(db: Session, project: models.Project) -> AssistantAnswer:
    payload = readiness_service.compute_readiness(db, project)
    comps = payload["components"]
    lines = [f"• {c['label']}: {c['score']}%" for c in comps]
    answer = f"Overall preparation is {payload['overall']}%.\n" + "\n".join(lines)
    return AssistantAnswer(
        intent="READINESS",
        answer=answer,
        why=payload["disclaimer"],
        what_you_need=[c["explanation"] for c in comps],
        status=SourceStatus.AI_INTERPRETATION.value,
        confidence=Confidence.HIGH.value,
        next_step={"action": "Open the readiness dashboard", "link": f"/projects/{project.id}/analysis"},
        data={"overall": payload["overall"], "components": comps},
        agent=AgentName.STRATEGIST.value,
    )


def _tool_applications(db: Session, project: models.Project) -> AssistantAnswer:
    apps = db.scalars(
        select(models.Application).where(models.Application.project_id == project.id).order_by(models.Application.updated_at.desc())
    ).all()
    if not apps:
        return AssistantAnswer(
            intent="APPLICATIONS",
            answer="No applications have been created for this project yet. When an approval is ready, use the Get Approval workflow to prepare one and then submit on the official portal.",
            next_step={"action": "Open approvals", "link": f"/projects/{project.id}/approvals"},
        )
    lines = [f"• {a.title} — {a.status.value.replace('_',' ').title()}" + (f" (ref: {a.official_reference})" if a.official_reference else "") for a in apps[:10]]
    note = "\n\nStatuses you record are self-reported unless they came from a verified integration; the official status is the one the authority holds."
    return AssistantAnswer(
        intent="APPLICATIONS",
        answer="Your applications:\n" + "\n".join(lines) + note,
        status=SourceStatus.USER_PROVIDED.value,
        next_step={"action": "Open applications", "link": f"/projects/{project.id}/applications"},
        data={"count": len(apps)},
        agent=AgentName.TRACKING.value,
    )


def _tool_explain(db: Session, project: models.Project | None, message: str) -> AssistantAnswer:
    low = message.lower()
    approvals = (
        db.scalars(select(models.ProjectApproval).where(models.ProjectApproval.project_id == project.id)).all()
        if project
        else []
    )
    target = None
    for a in approvals:
        for token in a.name.lower().split("(")[0].split():
            if len(token) > 4 and token in low:
                target = a
                break
        if target:
            break
    if target is None:
        for a in approvals:
            code_words = a.template_code.replace("_", " ").split()
            if any(w in low for w in code_words if len(w) > 4):
                target = a
                break
    if target is None:
        chunks = retrieve(db, message, project_id=project.id if project else None, top_k=3)
        if chunks:
            c = chunks[0]
            return AssistantAnswer(
                intent="EXPLAIN_APPROVAL",
                answer=f"Here is what the knowledge base says about that:\n\n{c.text[:700]}",
                why="Retrieved from the curated knowledge corpus.",
                sources=[c.citation_dict()],
                status=c.verification_status,
                confidence=Confidence.MEDIUM.value,
            )
        return AssistantAnswer(
            intent="EXPLAIN_APPROVAL",
            answer="I could not verify this from the available official sources. Name the approval or requirement and I will explain why it applies to your project, with the legal basis and the official portal.",
            status=SourceStatus.INFORMATION_UNAVAILABLE.value,
            confidence=Confidence.LOW.value,
        )

    chunks = retrieve(db, target.name, project_id=project.id, top_k=2)
    facts_txt = ", ".join(f"{m['label']} = {m['value']}" for m in (target.matched_facts or [])[:5]) or "your project profile"
    answer = (
        f"**{target.name}** (administered by {target.authority}).\n\n"
        f"{target.why_it_applies or 'This may apply based on your project profile.'}\n\n"
        f"Matched on: {facts_txt}."
    )
    if target.legal_basis:
        answer += "\n\nLegal basis: " + "; ".join(target.legal_basis) + "."
    answer += "\n\nThis is a planning-level indication from the deterministic rule engine — confirm the current requirement on the official portal before relying on it."
    return AssistantAnswer(
        intent="EXPLAIN_APPROVAL",
        answer=answer,
        why=target.why_it_applies,
        what_you_need=[r.title for r in target.requirements[:6]],
        sources=[c.citation_dict() for c in chunks],
        status=target.source_status.value if target.source_status else SourceStatus.REQUIRES_VERIFICATION.value,
        confidence=target.confidence.value if target.confidence else Confidence.MEDIUM.value,
        next_step={
            "action": "Open the approval card",
            "link": f"/projects/{project.id}/approvals?approval={target.template_code}",
            "portal_url": target.official_portal_url,
        },
        data={"template_code": target.template_code},
        agent=AgentName.APPROVAL.value,
    )


def _tool_schemes(db: Session, project: models.Project) -> AssistantAnswer:
    results = evaluate_scheme_criteria(db, project)
    relevant = [r for r in results if r["verdict"] in ("POSSIBLY_RELEVANT", "NEEDS_MORE_INFO")]
    if not relevant:
        return AssistantAnswer(
            intent="SCHEMES",
            answer="No scheme in the catalogue matches your project data yet. Complete more of your profile (state, investment, employment, industry) and I will re-check the documented criteria.",
            status=SourceStatus.REQUIRES_VERIFICATION.value,
            next_step={"action": "Complete profile", "link": f"/projects/{project.id}/profile"},
        )
    lines = []
    for r in relevant[:6]:
        verdict = "criteria matched" if r["verdict"] == "POSSIBLY_RELEVANT" else "needs more information"
        lines.append(f"• {r['name']} — {verdict} ({r['met']}/{len(r['criteria'])})")
    answer = "Potentially relevant schemes:\n" + "\n".join(lines) + "\n\nEligibility is always decided by the administering authority; I only compare your data against the documented criteria."
    return AssistantAnswer(
        intent="SCHEMES",
        answer=answer,
        why="Criteria are evaluated from your project profile against each scheme's published eligibility conditions.",
        status=SourceStatus.REQUIRES_VERIFICATION.value,
        next_step={"action": "Open schemes", "link": f"/projects/{project.id}/schemes"},
        data={"schemes": [r["code"] for r in relevant]},
        agent=AgentName.SCHEME.value,
    )


def _tool_calendar(db: Session, project: models.Project) -> AssistantAnswer:
    items = next_action_service.todays_tasks(db, project)
    if not items:
        return AssistantAnswer(
            intent="CALENDAR",
            answer="Nothing is due in the next 7 days. Renewal reminders are configured at 90/60/30/7 days before expiry and can be changed in settings.",
            status=SourceStatus.AI_INTERPRETATION.value,
        )
    lines = [f"• {i['title']} — due {i['due_date']}" for i in items[:8]]
    return AssistantAnswer(
        intent="CALENDAR",
        answer="Due in the next 7 days:\n" + "\n".join(lines),
        status=SourceStatus.USER_PROVIDED.value,
        next_step={"action": "Open the compliance calendar", "link": f"/projects/{project.id}/calendar"},
        data={"items": items},
        agent=AgentName.COMPLIANCE.value,
    )


def _tool_critical_path(db: Session, project: models.Project) -> AssistantAnswer:
    path = get_critical_path(db, project)
    if not path:
        return AssistantAnswer(
            intent="CRITICAL_PATH",
            answer="Run the approval analysis to generate your dependency roadmap.",
            next_step={"action": "Run analysis", "link": f"/projects/{project.id}/analysis"},
        )
    lines = [f"{p['step']}. {p['name']}" for p in path[:12]]
    return AssistantAnswer(
        intent="CRITICAL_PATH",
        answer="Your current critical path:\n" + "\n".join(lines),
        why="Derived from the dependency graph of your applicable approvals and their current states.",
        status=SourceStatus.AI_INTERPRETATION.value,
        next_step={"action": "Open the approval graph", "link": f"/projects/{project.id}/approvals"},
        data={"path": path},
        agent=AgentName.STRATEGIST.value,
    )


def _tool_general(db: Session, project: models.Project | None, message: str) -> AssistantAnswer:
    chunks = retrieve(db, message, project_id=project.id if project else None, top_k=3)
    if not chunks:
        return AssistantAnswer(
            intent="GENERAL",
            answer=(
                "I could not verify this from the available official sources. I can help with: approvals that may "
                "apply to your project, missing documents, your next step, readiness, applications, schemes, the "
                "compliance calendar and queries. Ask me one of those, or ask about a specific approval."
            ),
            status=SourceStatus.INFORMATION_UNAVAILABLE.value,
            confidence=Confidence.LOW.value,
        )
    top = chunks[0]
    body = top.text[:800]
    others = [c for c in chunks[1:]]
    sources = [c.citation_dict() for c in chunks]
    answer = f"{body}\n\n(Source: {top.publisher or top.title} — {top.verification_status.replace('_',' ').title()})\n\nSelect a project and I will ground answers in your specific approvals, documents and deadlines."
    return AssistantAnswer(
        intent="GENERAL",
        answer=answer,
        why="Grounded in the retrieved knowledge corpus.",
        sources=sources,
        status=top.verification_status,
        confidence=Confidence.MEDIUM.value if len(body) > 200 else Confidence.LOW.value,
        data={"other_sources": [c.citation_dict() for c in others]},
    )


def _tool_help(db: Session, project: models.Project) -> AssistantAnswer:
    return AssistantAnswer(
        intent="HELP",
        answer=(
            "I am your approval and compliance assistant for this project. Ask me:\n"
            "• “What approvals do I need?” — the rule-engine analysis of your profile\n"
            "• “What documents are missing?” — your actual document gaps\n"
            "• “What should I do next?” — the next-best-action plan\n"
            "• “Explain Consent to Establish” — why a requirement applies, with sources\n"
            "• “Find schemes for my business” — documented eligibility matching\n"
            "• “Show my applications / calendar / tasks”\n\n"
            "I never submit anything to a government body without your explicit confirmation, and I never show a "
            "government status I have not verified."
        ),
        status=SourceStatus.AI_INTERPRETATION.value,
    )


def _tool_project_status(db: Session, project: models.Project) -> AssistantAnswer:
    ctx = project_context(db, project)
    rd = readiness_service.compute_readiness(db, project, persist=False)
    answer = (
        f"**{project.name}** — industry: {ctx.get('industry') or 'not set'}, state: {ctx.get('state') or 'not set'}. "
        f"{len(ctx['applicable_approvals'])} potentially applicable approvals, {len(ctx['documents_on_file'])} documents on file, "
        f"{len(ctx['applications'])} applications. Overall preparation: {rd['overall']}%."
    )
    return AssistantAnswer(
        intent="PROJECT_STATUS",
        answer=answer,
        status=SourceStatus.AI_INTERPRETATION.value,
        next_step={"action": "Open dashboard", "link": f"/projects/{project.id}"},
        data={"overall": rd["overall"]},
    )


def _tool_queries(db: Session, project: models.Project) -> AssistantAnswer:
    queries = db.scalars(
        select(models.GovernmentQuery).where(models.GovernmentQuery.project_id == project.id)
    ).all()
    open_q = [q for q in queries if q.status != QueryStatus.CLOSED]
    if not open_q:
        return AssistantAnswer(intent="QUERIES", answer="You have no open government queries on record.", status=SourceStatus.USER_PROVIDED.value)
    lines = [f"• {(q.reference_number or 'Query')} — {q.status.value}, authority: {q.authority or '—'}" + (f", deadline {q.deadline}" if q.deadline else "") for q in open_q[:6]]
    return AssistantAnswer(
        intent="QUERIES",
        answer="Open queries:\n" + "\n".join(lines) + "\n\nI can help you break a query into points, map each point to a document and draft a response plan — you approve the final response before anything is filed.",
        status=SourceStatus.USER_PROVIDED.value,
        next_step={"action": "Open queries", "link": f"/projects/{project.id}/queries"},
        agent=AgentName.TRACKING.value,
    )


def _tool_inspection(db: Session, project: models.Project) -> AssistantAnswer:
    inspections = db.scalars(select(models.Inspection).where(models.Inspection.project_id == project.id)).all()
    upcoming = [i for i in inspections if i.status in (models.InspectionStatus.SCHEDULED, models.InspectionStatus.FOLLOW_UP_REQUIRED)]
    if not upcoming:
        return AssistantAnswer(intent="INSPECTION", answer="No inspections are scheduled on record. When one is announced, record it and I will build the preparation checklist.", status=SourceStatus.USER_PROVIDED.value)
    i = upcoming[0]
    answer = (
        f"Next recorded inspection: {i.department or 'department not recorded'}"
        + (f" on {i.inspection_date}" if i.inspection_date else "")
        + ". Preparation basics: keep the order file at site, statutory registers current, monitoring data available, and the site consistent with your declared layout."
    )
    return AssistantAnswer(
        intent="INSPECTION",
        answer=answer,
        status=SourceStatus.AI_INTERPRETATION.value,
        next_step={"action": "Open inspections", "link": f"/projects/{project.id}/inspections"},
    )


def _tool_open_portal(db: Session, project: models.Project, message: str) -> AssistantAnswer:
    from ..services.portal_seed import search_portals

    q = message
    portals = search_portals(db, q=q, limit=4)
    if not portals:
        return AssistantAnswer(
            intent="OPEN_PORTAL",
            answer="I could not find that portal in the verified directory. Browse the full directory instead — every entry there links to the official site.",
            status=SourceStatus.INFORMATION_UNAVAILABLE.value,
            next_step={"action": "Open portal directory", "link": "/government-portals"},
        )
    lines = [f"• {p['name']} ({p['department']}) — {p['official_url']}" for p in portals]
    return AssistantAnswer(
        intent="OPEN_PORTAL",
        answer="Official portals matching your request:\n" + "\n".join(lines),
        status=portals[0].get("verification_status", SourceStatus.REQUIRES_VERIFICATION.value),
        next_step={"action": "Open portal directory", "link": "/government-portals"},
        data={"portals": portals},
    )


# ─────────────────────────────────────────────────────────── main entry ──
def answer(
    db: Session,
    project: models.Project | None,
    user: models.User,
    message: str,
    *,
    channel: str = "chat",
    language: str = "en",
    conversation: models.AIConversation | None = None,
    request_id: str | None = None,
) -> AssistantAnswer:
    intent = detect_intent(message)
    sensitive = detect_sensitive(message)

    if sensitive:
        confirmation_text = (
            "This action may send information to an external government service or record an irreversible action. "
            "Do you want to continue? Nothing is sent until you confirm on the screen."
        )
        return AssistantAnswer(
            intent="SENSITIVE_ACTION",
            answer="Submitting an application may send information to an external government service. Do you want to continue? Use CONFIRM to proceed or CANCEL to stop.",
            why="Sensitive actions are never executed from voice or chat alone — they always require an explicit, recorded confirmation.",
            requires_confirmation={
                "action": sensitive,
                "message": message,
                "confirm_label": "CONFIRM",
                "cancel_label": "CANCEL",
            },
            status=SourceStatus.AI_INTERPRETATION.value,
            agent=AgentName.APPLICATION.value,
        )

    if intent == "LANGUAGE":
        lang = "ta" if re.search(r"tamil|தமிழ்", message, re.I) else "hi" if re.search(r"hindi|हिंदी", message, re.I) else "en"
        names = {"ta": "Tamil (தமிழ்)", "hi": "Hindi (हिन्दी)", "en": "English"}
        return AssistantAnswer(
            intent="LANGUAGE",
            answer=f"Switching the interface language to {names[lang]}. Voice responses will follow the same language where supported.",
            data={"language": lang},
            next_step={"action": "Language applied", "link": "/settings"},
            status=SourceStatus.AI_INTERPRETATION.value,
            agent=AgentName.VOICE.value,
        )

    handlers = {
        "PENDING_APPROVALS": lambda: _tool_pending_approvals(db, project) if project else _need_project(),
        "MISSING_DOCUMENTS": lambda: _tool_missing_documents(db, project) if project else _need_project(),
        "NEXT_STEP": lambda: _tool_next_step(db, project) if project else _need_project(),
        "READINESS": lambda: _tool_readiness(db, project) if project else _need_project(),
        "APPLICATIONS": lambda: _tool_applications(db, project) if project else _need_project(),
        # grounded intents work even without a project selected
        "EXPLAIN_APPROVAL": lambda: _tool_explain(db, project, message),
        "SCHEMES": lambda: _tool_schemes(db, project) if project else _need_project(),
        "CALENDAR": lambda: _tool_calendar(db, project) if project else _need_project(),
        "COMPLIANCE_TASKS": lambda: _tool_calendar(db, project) if project else _need_project(),
        "OPEN_PORTAL": lambda: _tool_open_portal(db, project, message),
        "PROJECT_STATUS": lambda: _tool_project_status(db, project) if project else _need_project(),
        "QUERIES": lambda: _tool_queries(db, project) if project else _need_project(),
        "INSPECTION": lambda: _tool_inspection(db, project) if project else _need_project(),
        "CRITICAL_PATH": lambda: _tool_critical_path(db, project) if project else _need_project(),
        "HELP": lambda: _tool_help(db, project),
    }
    handler = handlers.get(intent)
    result = handler() if handler else None
    if result is None:
        result = _tool_general(db, project, message)

    # optional external LLM re-phrasing — verdicts and sources stay tool-built
    if llm.llm_configured() and result.answer and intent != "SENSITIVE_ACTION":
        try:
            chunks = [c for c in [dict(s) for s in result.sources]]
            resp = llm.generate(
                message,
                context_chunks=chunks,
                project_context=project_context(db, project) if project else None,
                rule_verdicts=None,
                response_format_hint="Rewrite the draft answer below in clear, warm, professional language without changing any fact, number, source or caveat. Keep it under 180 words.\n\nDRAFT:\n" + result.answer,
                max_tokens=500,
            )
            if resp.available and resp.text:
                result.answer = resp.text
                result.used_llm = True
        except Exception:  # noqa: BLE001 — local answer already good
            pass

    _persist_messages(db, conversation, user, project, message, result, channel, language)
    return result


def _need_project() -> AssistantAnswer:
    return AssistantAnswer(
        intent="NO_PROJECT",
        answer="Select or create a project first — my answers are grounded in your project profile, approvals and documents.",
        next_step={"action": "Create a project", "link": "/projects"},
        status=SourceStatus.AI_INTERPRETATION.value,
    )


def _persist_messages(
    db: Session,
    conversation: models.AIConversation | None,
    user: models.User,
    project: models.Project | None,
    message: str,
    result: AssistantAnswer,
    channel: str,
    language: str,
) -> None:
    if conversation is None:
        return
    db.add(
        models.AIMessage(
            conversation_id=conversation.id,
            role=AIMessageRole.USER,
            content=message,
            language=language,
        )
    )
    db.add(
        models.AIMessage(
            conversation_id=conversation.id,
            role=AIMessageRole.ASSISTANT,
            content=result.answer,
            structured=result.to_structured(),
            citations=result.sources,
            agent=result.agent or None,
            intent=result.intent,
            confidence=result.confidence or None,
            source_status=result.status or None,
            tools_used=["rule_engine", "readiness", "retrieval"],
            language=language,
        )
    )
    conversation.message_count += 2
    conversation.context_snapshot = project_context(db, project) if project else {}
    if conversation.title == "New conversation":
        conversation.title = message[:80]
    db.commit()
