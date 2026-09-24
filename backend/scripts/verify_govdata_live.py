"""Live verification of the government data services upgrade (§22).
Run against the live server on :8899."""
from __future__ import annotations

import json
import sys

import httpx

BASE = "http://127.0.0.1:8899/api/v1"
PASSED = 0
FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSED
    if cond:
        PASSED += 1
        print(f"  ✔ {name}")
    else:
        FAILED.append(name)
        print(f"  ✘ {name}  {detail}")


def main() -> int:
    c = httpx.Client(base_url=BASE, timeout=30)
    print("— access & regression —")
    h = c.get("/health").json()
    check("health ok", h["status"] == "ok" and h["seeded"] is True)
    check("gov services require auth", c.get("/gov/services").status_code == 401)

    H = {"Authorization": f"Bearer {c.post('/auth/login', json={'email': 'demo@niecp.local', 'password': 'Demo!Demo!123'}).json()['access_token']}"}
    A = {"Authorization": f"Bearer {c.post('/auth/login', json={'email': 'admin@niecp.local', 'password': 'NIECP-Admin!2026'}).json()['access_token']}"}
    pid = c.get("/projects", headers=H).json()["projects"][0]["id"]

    print("— §21 service cards —")
    sv = c.get("/gov/services", headers=H).json()
    codes = {s["code"] for s in sv["services"]}
    check("7 providers listed", {"udyam_dataset", "mca", "pincode", "digilocker", "nsws", "tn_single_window", "niecp_demo_government"} <= codes, str(codes))
    check("none connected (nothing provisioned)", sv["summary"]["active"] == 0)
    by = {s["code"]: s for s in sv["services"]}
    check("digilocker awaiting authorization", "awaiting official partner authorization" in (by["digilocker"]["notice"] or "").lower())
    check("credentials as booleans only", all(isinstance(v, bool) for s in sv["services"] for v in s["credentials_configured"].values()))

    print("— §5 pincode —")
    ok = c.post("/gov/pincode-lookup", headers=H, json={"pincode": "641045"}).json()
    check("coimbatore-region pin → TN circle", ok["ok"] is True and ok["data"]["state_code"] == "TAMIL_NADU")
    check("district never guessed offline", ok["data"]["district"] is None and ok["verification_status"] == "REQUIRES_VERIFICATION")
    bad = c.post("/gov/pincode-lookup", headers=H, json={"pincode": "12"}).json()
    check("invalid pin honest error", bad["ok"] is False and "valid 6-digit" in bad["message"])
    applied = c.post("/gov/pincode-lookup", headers=H, json={"pincode": "600001", "project_id": pid, "apply_to_profile": True}).json()
    check("profile applied + twin note", applied["ok"] is True and applied.get("analysis_note"))

    print("— §3 UDYAM dataset —")
    s = c.post("/gov/udyaam/search", headers=H, json={"query": "electronics", "state_code": "TN", "project_id": pid}).json()
    check("demo search labelled", s["ok"] is True and s["mode"] == "DEMO" and "DEMO DATA — NOT A LIVE GOVERNMENT CONNECTION" in s["message"])
    rec = s["data"]["records"][0]
    sel = c.post("/gov/udyaam/select", headers=H, json={"project_id": pid, "record": rec, "confirmation": True}).json()
    check("user-selected reference stored", sel["ok"] is True and sel["reference"]["verification_status"] == "GOVERNMENT_DATASET_MATCH")
    check("verification disclaimer", "NOT a real-time verification" in sel["reference"]["verification_label"])
    refs = c.get(f"/projects/{pid}/gov-references", headers=H).json()["references"]
    check("reference listed", any(r["is_demo"] for r in refs))

    print("— §4 MCA —")
    m = c.post("/gov/mca/search", headers=H, json={"query": "Demo Electronics", "project_id": pid}).json()
    check("MCA pending authorization", m["ok"] is False and m["mode"] == "PENDING_AUTHORIZATION" and m["fallback"]["official_portal_url"] == "https://www.mca.gov.in/")
    check("no fabricated companies", not json.dumps(m.get("data", {})).count("cin"))

    print("— §6/§7 DigiLocker + consent —")
    dl = c.get("/gov/digilocker/status", headers=H).json()
    check("digilocker pending", dl["ok"] is False and dl["mode"] == "PENDING_AUTHORIZATION")
    con = c.post("/gov/consent", headers=H, json={"project_id": pid, "provider": "digilocker", "service": "DigiLocker document retrieval (requester)", "purpose": "Fetch Certificate of Incorporation", "documents_requested": ["Certificate of Incorporation"], "accepted": True}).json()
    check("consent recorded", con["ok"] is True and con["status"] == "GRANTED")
    req = c.post("/gov/digilocker/request-document", headers=H, json={"project_id": pid, "consent_id": con["consent_id"], "document_type": "Certificate of Incorporation"}).json()
    check("retrieval honest (no fake doc)", req["ok"] is False and "awaiting official partner authorization" in req["message"] and req["fallback"]["official_portal_url"].startswith("https://www.digilocker.gov.in"))
    rev = c.post(f"/gov/consent/{con['consent_id']}/revoke", headers=H).json()
    check("revoke works", rev["status"] == "REVOKED")

    print("— §20 command center —")
    cc = c.get(f"/projects/{pid}/command-center", headers=H).json()
    check("command center payload", isinstance(cc["readiness"]["overall"], int) and "/" in cc["documents_ready"] and isinstance(cc["next_best_actions"], list))
    check("integration counts honest", cc["integrations"]["active"] == 0 and cc["integrations"]["pending"] >= 4)

    print("— §16 audit —")
    ev = c.get("/admin/audit", params={"action": "GOV_DATA_PINCODE_LOOKUP", "limit": 200}, headers=A).json()["events"]
    check("provider call audited", bool(ev) and ev[0]["provider"].startswith("India Post"))
    ev2 = c.get("/admin/audit", params={"action": "GOV_DATASET_MATCH_SELECTED", "limit": 200}, headers=A).json()["events"]
    check("dataset selection audited", bool(ev2))

    print("— PHASE 3: MSME regulatory intelligence —")
    lv = c.get("/msme/law-versions", headers=H).json()
    check("law versions: current = v3-2025 + warning", lv["current_applied"] == "v3-2025" and "may not represent the latest applicable law" in lv["warning"])
    check("law versions: superseded kept", {v["version"]: v["status"] for v in lv["versions"]}["v2-2020"] == "SUPERSEDED")

    probe = c.post("/projects", headers=H, json={"name": f"verify-classification-{int(__import__('time').time())}"}).json()["project"]["id"]
    c.patch(f"/projects/{probe}/profile", headers=H, json={"industry_code": "electronics", "machinery_investment": 50_000_000})
    cl = c.get(f"/projects/{probe}/msme/classification", headers=H).json()
    check("classification: refuses without inputs", cl["potential_class"] is None and cl["status"] == "INFORMATION_REQUIRED" and any("turnover" in m for m in cl["missing_inputs"]))

    intel = c.get(f"/projects/{pid}/msme/intelligence", headers=H).json()
    secs = {p["section"]: p for p in intel["applicable_msme_provisions"]}
    check("intelligence: 10-block regulatory profile", len(intel) >= 10 and "smart_action_guide" in intel and "trust_labels" in intel)
    check("intelligence: provisions conditional + sourced", secs["22"]["applicability"] == "CONDITIONAL" and all(p["official_source"].startswith("https://") for p in secs.values()))
    check("intelligence: version warning surfaced", "may not represent the latest applicable law" in intel["law_versions"]["warning"])

    pa = c.post(f"/projects/{pid}/msme/payment-assessment", headers=H, json={
        "supplier_enterprise_class": "MICRO", "invoice_date": "2026-01-05", "amount": 500000, "payment_terms_days": 45}).json()
    check("payment: delay + §§15/18 + labelled estimate", pa.get("ok") and pa["delayed_payment_flag"] is True and "15" in pa["applicable_sections"] and "18" in pa["applicable_sections"] and pa["interest_estimate"]["amount"] > 0 and "NOT LEGAL ADVICE" in pa["assessment_type"])
    pa2 = c.post(f"/projects/{pid}/msme/payment-assessment", headers=H, json={
        "supplier_enterprise_class": "MEDIUM", "invoice_date": "2026-01-05", "amount": 100000, "as_of": "2026-09-01"}).json()
    check("payment: non-MSE supplier out of scope", pa2["msmed_relevant"] is False)

    mt = c.get(f"/projects/{pid}/msme/maitri-services", headers=H).json()
    check("maitri: TN project → gated off", mt["state_code"] == "TN" and mt["relevant"] is False and "never automates submission" in mt["notice"])
    c.patch(f"/projects/{pid}/profile", headers=H, json={"state_code": "MH"})
    mt2 = c.get(f"/projects/{pid}/msme/maitri-services", headers=H).json()
    check("maitri: MH project → catalogue + official portal", mt2["relevant"] is True and len(mt2["services"]) >= 5 and all(s["official_channel"] == "https://maitri.maharashtra.gov.in/" for s in mt2["services"]))
    c.patch(f"/projects/{pid}/profile", headers=H, json={"state_code": "TN"})

    ex = c.get("/msme/provisions/18/explain", headers=H, params={"project_id": pid}).json()
    check("explain: §18 conditional + disclaimer", ex["section"] == "18" and ex["applicable_condition"]["status"] in ("CONDITIONAL", "APPLICABLE") and "not legal advice" in ex["disclaimer"])
    check("explain: 404 unmodelled section", c.get("/msme/provisions/999/explain", headers=H).status_code == 404)

    reg = c.get("/gov/services", headers=H).json()
    rcodes = {s["code"]: s for s in reg["services"]}
    check("registry: MAITRI + CPCB adapters", rcodes["maitri"]["official_portal_url"] == "https://maitri.maharashtra.gov.in/" and rcodes["cpcb"]["authorization_status"] == "PENDING_AUTHORIZATION")


    print("— GOV DATA UPGRADE: datasets, context, routing, twin —")
    ds = c.get("/gov/data-status", headers=H).json()
    check("data-status: 6 datasets + honest outbound state", len(ds["datasets"]) == 6 and ds["outbound_calls_enabled"] is False and all(x["connection_state"] == "PENDING_AUTHORIZATION" for x in ds["datasets"]))

    svc = {s["code"]: s for s in c.get("/gov/services", headers=H).json()["services"]}
    check("cards: 11 providers, honest states, none CONNECTED", len(svc) == 11 and all(s["connection_status"] != "CONNECTED" for s in svc.values()))
    check("cards: water/ASI present + labelled", svc["cpcb_surface_water"]["data_categories"][0].startswith("pH") and "INDUSTRIAL STATISTICAL DATA" in svc["asi_industrial"]["notes"] and "HISTORICAL / SUPPORTING" in svc["cpcb_surface_water"]["service_name"] if "service_name" in svc["cpcb_surface_water"] else "HISTORICAL / SUPPORTING" in svc["cpcb_surface_water"]["service"])
    check("cards: context notes forbid approval-by-data", "never" in svc["cpcb_surface_water"]["notes"].lower() and "never" in svc["asi_industrial"]["notes"].lower())

    mh = c.get("/gov/state-integration", params={"state_code": "MH"}, headers=H).json()
    tn = c.get("/gov/state-integration", params={"state_code": "TN"}, headers=H).json()
    check("state routing: MH→MAITRI primary, TN→TN SWS", mh["primary_state_integration"]["code"] == "maitri" and tn["primary_state_integration"]["code"] == "tn_single_window")

    aq = c.post("/gov/cpcb/air-quality", headers=H, json={"project_id": pid, "city": "Mumbai"}).json()
    check("air quality: pending + ENVIRONMENTAL_CONTEXT + usage rule", aq["ok"] is False and aq["context_label"] == "ENVIRONMENTAL_CONTEXT" and "never" in aq["usage_rule"].lower())
    sw = c.post("/gov/cpcb/surface-water", headers=H, json={"project_id": pid, "location": "Wardha"}).json()
    check("surface water: HISTORICAL_SUPPORTING_DATA label", sw["context_label"] == "HISTORICAL_SUPPORTING_DATA")
    asi = c.post("/gov/asi/industry-stats", headers=H, json={"project_id": pid, "industry": "electronics"}).json()
    check("ASI: INDUSTRIAL_STATISTICAL_DATA label", asi["context_label"] == "INDUSTRIAL_STATISTICAL_DATA")

    en = c.get(f"/projects/{pid}/gov/enrichment", headers=H).json()
    check("project twin: 10 provenance blocks incl. PROJECT", set(en["blocks"]) == {"PROJECT","BUSINESS","COMPANY","MSME","LOCATION","ENVIRONMENT","INDUSTRY","APPROVALS","DOCUMENTS","COMPLIANCE"})
    check("digital twin: MSME block carries engine class", any("MSME" in (b.get("label") or "") or "class" in str(b.get("label","")).lower() for b in en["blocks"]["MSME"]))

    mca = c.post("/gov/mca/search", headers=H, json={"query": "test", "project_id": pid}).json()
    check("MCA: honest pending/portal fallback (no fake data)", mca["ok"] is False and mca["error_code"] in ("NOT_PROVISIONED", "DISABLED") and (mca.get("fallback") or {}).get("official_portal_url", "").startswith("https://www.mca.gov.in"))

    c.patch(f"/projects/{pid}/profile", headers=H, json={"state_code": "MH"})
    mt = c.get(f"/projects/{pid}/msme/maitri-services", headers=H).json()
    check("MAITRI: approval links authored + REQUIRES_VERIFICATION", isinstance(mt.get("approval_links"), list) and all(a["verification_status"] == "REQUIRES_VERIFICATION" for a in mt["approval_links"]))
    check("MAITRI: TAT honesty (no invented days)", all(s.get("tat_days") is None and s.get("tat_note") for s in mt["services"]))
    c.patch(f"/projects/{pid}/profile", headers=H, json={"state_code": "TN"})

    g = c.get(f"/projects/{pid}/graph", headers=H).json()
    if g["nodes"]:
        n0 = g["nodes"][0]
        check("graph: verification/missing-info/official-channel fields", all(k in n0 for k in ("information_required", "requires_verification", "verification_status", "official_channel", "legal_basis")))
    else:
        check("graph: verification/missing-info/official-channel fields", False)

    na = c.get(f"/projects/{pid}/next-actions", headers=H).json()
    check("smart action guide: action/reason/verification fields", na["actions"] and all({"action", "reason", "verification_status", "blocked_by", "required_documents"} <= set(a) for a in na["actions"]))


    print("— MVP ARCHITECTURE: trail, package, handoff, SLA, bottlenecks —")
    c.post(f"/projects/{pid}/analysis", headers=H)
    tr = c.get(f"/projects/{pid}/decision-trail", headers=H).json()
    check("decision trail: rows with rule/result/facts/engine version", bool(tr["trail"]) and all(k in tr["trail"][0] for k in ("rule_expression", "result", "triggering_facts", "missing_facts", "engine_version", "recorded_at")))

    pkg = c.get(f"/projects/{pid}/application-package", headers=H).json()
    check("application package: from real state + readiness note", bool(pkg["approvals"]) and "never a probability of approval" in pkg["readiness"]["note"] and isinstance(pkg["missing_items"], list))

    h0 = c.post(f"/projects/{pid}/maitri-handoff", headers=H).json()
    check("maitri handoff: non-MH honest decline", h0["status"] == "PENDING_AUTHORIZATION")
    c.patch(f"/projects/{pid}/profile", headers=H, json={"state_code": "MH"})
    h1 = c.post(f"/projects/{pid}/maitri-handoff", headers=H).json()
    check("maitri handoff: MH → MANUAL_HANDOFF, no submission claimed", h1["status"] == "MANUAL_HANDOFF" and "No application is submitted" in h1["notice"])
    c.patch(f"/projects/{pid}/profile", headers=H, json={"state_code": "TN"})

    sla = c.get(f"/projects/{pid}/sla", headers=H).json()
    check("sla engine: CONFIGURED labels + summary", "CONFIGURED" in " ".join(sla["labels"]) and "summary" in sla)

    bnx = c.get(f"/projects/{pid}/bottlenecks", headers=H).json()
    check("bottleneck engine: causal + no AI risk score", "no ai risk score" in bnx["note"].lower() and all({"bottleneck", "causes", "downstream_impact", "severity"} <= set(b) for b in bnx["bottlenecks"][:1]) if bnx["bottlenecks"] else True and "no ai risk score" in bnx["note"].lower())

    twin = c.get(f"/projects/{pid}/gov/enrichment", headers=H).json()
    check("project twin: central blocks + provenance counts", twin["twin"]["name"] == "Project Twin" and "PROJECT" in twin["blocks"] and twin["twin"]["verification_counts"])

    aps = c.get(f"/projects/{pid}/applications", headers=H).json()["applications"]
    check("lifecycle: state-driven stage per application", all("lifecycle" in a and a["lifecycle"]["stage"] and "label" in a["lifecycle"] for a in aps))

    opq = c.get("/ops/department-queue", headers=H)
    check("department queue: admin-gated (applicant blocked)", opq.status_code == 403)
    adm_login = c.post("/auth/login", json={"email": "admin@niecp.local", "password": "NIECP-Admin!2026"}).json()
    opq2 = c.get("/ops/department-queue", headers={"Authorization": f"Bearer {adm_login['access_token']}"}).json()
    check("department queue: PROTOTYPE / SIMULATED labels", opq2["view"].startswith("DEPARTMENT OPERATIONS — PROTOTYPE / SIMULATED") and opq2["labels"] == ["PROTOTYPE", "SIMULATED", "READ-ONLY"])


    print("— §17 error mapping —")
    t404 = c.post("/gov/services/nope/test", headers=H, json={})
    check("unknown provider → 404", t404.status_code == 404)

    print("— SPA —")
    spa = httpx.get("http://127.0.0.1:8899/", timeout=10)
    check("SPA served", spa.status_code == 200)

    print(f"\n{PASSED} passed, {len(FAILED)} failed")
    if FAILED:
        print("FAILED:", FAILED)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
