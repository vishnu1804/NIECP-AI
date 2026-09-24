"""Live end-to-end verification of the NIECP-AI platform — base systems plus
the Master Upgrade additions (integration manager, demo government flow,
registry, translator, audit correlation, AI alias). Run against the live
server on :8899."""
from __future__ import annotations

import json
import re
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

    print("— base —")
    h = c.get("/health").json()
    check("health ok + seeded", h["status"] == "ok" and h["seeded"] is True)
    prov = c.get("/system/provenance").json()
    check("provenance principles", len(prov.get("principles", [])) >= 5)

    r = c.post("/auth/login", json={"email": "demo@niecp.local", "password": "Demo!Demo!123"})
    H = {"Authorization": f"Bearer {r.json()['access_token']}"}
    check("demo login", r.status_code == 200)
    r = c.post("/auth/login", json={"email": "admin@niecp.local", "password": "NIECP-Admin!2026"})
    A = {"Authorization": f"Bearer {r.json()['access_token']}"}
    check("admin login", r.status_code == 200)

    pid = c.get("/projects", headers=H).json()["projects"][0]["id"]
    an = c.post(f"/projects/{pid}/analysis", headers=H).json()
    check("analysis verdicts", "approvals" in json.dumps(an)[:4000] or an.get("counts") is not None or "results" in an, str(an)[:120])
    read = c.get(f"/projects/{pid}/readiness", headers=H)
    check("readiness endpoint", read.status_code == 200)

    print("— integration registry (§12/§23) —")
    reg = c.get("/integration-registry", headers=H).json()
    codes = {e["provider_code"]: e for e in reg["registry"]}
    check("4 providers registered", {"nsws", "tn_single_window", "apisetu", "niecp_demo_government"} <= set(codes), str(list(codes)))
    check("nothing is live", all(e["live"] is False for e in reg["registry"]))
    check("NSWS pending authorization", codes["nsws"]["authorization_status"] == "PENDING")
    check("demo provider synthetic", codes["niecp_demo_government"]["environment"] == "DEMO" and codes["niecp_demo_government"]["is_demo"] is True)
    check("portal URLs are stored ones", codes["nsws"]["official_portal_url"] == "https://www.nsws.gov.in/")

    print("— demo government (§5–§8) —")
    da = c.get(f"/demo/government/approvals", params={"project_id": pid}, headers=H).json()
    check("demo approvals list", len(da["approvals"]) > 20 and da["demo"]["environment"] == "DEMO")
    code = next(a["code"] for a in da["approvals"] if a["demo_eligible"] and a["applicability"] == "APPLIES")
    aid = c.post(f"/projects/{pid}/applications", headers=H, json={"title": "LIVE verify app", "approval_template_code": code}).json()["application"]["id"]
    c.post(f"/projects/{pid}/applications/{aid}/prepare", headers=H)
    c.post(f"/projects/{pid}/applications/{aid}/confirm", headers=H)
    g = c.post("/demo/government/applications", headers=H, json={"project_id": pid, "application_id": aid})
    check("submission gate: confirmation required", g.status_code == 422)
    s = c.post("/demo/government/applications", headers=H, json={"project_id": pid, "application_id": aid, "demo_confirmation": True}).json()
    check("synthetic reference format", bool(re.fullmatch(r"NIECP-DEMO-\d{4}-\d{4}", s.get("application_reference", ""))), s.get("application_reference", "?"))
    meta = s["demo"]
    check("§5 honesty block", meta["environment"] == "DEMO" and meta["data_source"] == "SYNTHETIC" and meta["government_api"] == "NOT_CONNECTED" and meta["authorization_status"] == "NOT_AUTHORIZED" and meta["live"] is False)
    check("double submit rejected", c.post("/demo/government/applications", headers=H, json={"project_id": pid, "application_id": aid, "demo_confirmation": True}).status_code == 409)
    st = c.get(f"/demo/government/applications/{aid}/status", headers=H).json()
    check("workflow simulation + query raised", st["status"] == "QUERY_RAISED" and st["queries"] and st["queries"][0]["is_demo"])
    check("query labelled synthetic", st["queries"][0]["query_text"].startswith("[DEMO QUERY — SYNTHETIC]"))
    qid = st["queries"][0]["id"]

    print("— query translator (§21) —")
    tr = c.post(f"/projects/{pid}/queries/{qid}/translate", headers=H).json()["translation"]
    check("translation structure", all(k in tr for k in ("original_query", "plain_language_explanation", "what_is_missing", "what_is_needed", "recommended_action", "response_preparation", "disclaimer")))
    check("AI disclaimer", "verify against the official communication" in tr["disclaimer"])

    print("— demo response → decision (§7) —")
    rg = c.post(f"/demo/government/applications/{aid}/response", headers=H, json={"query_id": qid, "response_text": "Response text.", "confirm_response_submission": False})
    check("response gate", rg.status_code == 422)
    rp = c.post(f"/demo/government/applications/{aid}/response", headers=H, json={"query_id": qid, "response_text": "Point-by-point response with enclosures.", "confirm_response_submission": True}).json()
    check("USER_RESPONDED", rp["application"]["status"] == "USER_RESPONDED")
    adv = c.post(f"/demo/government/applications/{aid}/advance", headers=H).json()
    check("synthetic approval", adv["status"] == "APPROVED" and adv["valid_until"])
    check("synthetic conditions labelled", adv["demo_approval_conditions"] and all("SYNTHETIC" in x for x in adv["demo_approval_conditions"]))
    rens = c.get(f"/projects/{pid}/renewals", headers=H).json()["renewals"]
    check("renewal auto-created", any(rn.get("is_demo") and rn["title"].startswith("Renewal:") for rn in rens))
    apps = c.get(f"/projects/{pid}/applications", headers=H).json()["applications"]
    mine = next(a for a in apps if a["id"] == aid)
    check("application carries mode/ref", mine["integration_mode"] == "DEMO" and mine["correlation_id"] and mine["is_demo"])

    print("— channels (§24/§9/§10) —")
    eo = c.get(f"/projects/{pid}/applications/{aid}/execution-options", headers=H).json()
    check("authorized API unavailable", eo["channels"]["AUTHORIZED_API"]["available"] is False)
    check("manual always available", eo["channels"]["MANUAL"]["available"] is True)
    check("recommended is honest", eo["recommended"] in ("OFFICIAL_REDIRECT", "MANUAL"))
    red = c.post(f"/projects/{pid}/applications/{aid}/redirect", headers=H)
    if red.status_code == 200:
        check("redirect packet + verified URL", red.json()["redirect"]["portal_url"].startswith("https://"))
    else:
        check("redirect honest 404 when no stored URL", "does not guess" in red.json()["detail"])
    mp = c.get(f"/projects/{pid}/applications/{aid}/manual-packet", params={"format": "text"}, headers=H)
    check("manual packet download", mp.status_code == 200 and "MANUAL APPLICATION PACKET" in mp.text)
    pkt = c.get(f"/projects/{pid}/applications/{aid}/manual-packet", headers=H).json()
    check("manual packet record gates", any(f.get("gate") for f in pkt["record_fields"]))

    print("— audit correlation (§50) —")
    ev = c.get("/admin/audit", params={"action": "DEMO_SUBMITTED", "limit": 10}, headers=A).json()["events"]
    check("DEMO_SUBMITTED audited with correlation", ev and ev[0]["correlation_id"] == mine["correlation_id"] and ev[0]["integration_mode"] == "DEMO")
    ev2 = c.get("/admin/audit", params={"action": "QUERY_RESPONSE_SUBMITTED", "limit": 10}, headers=A).json()["events"]
    check("QUERY_RESPONSE_SUBMITTED audited", bool(ev2))
    ev3 = c.get("/admin/audit", params={"action": "DEMO_DECISION_RECORDED", "limit": 10}, headers=A).json()["events"]
    check("demo decision audited", bool(ev3))

    print("— AI backend (§36/§37/§47) —")
    ai = c.post("/ai/assistant", headers=H, json={"message": "What approvals do I need for my electronics manufacturing project?", "projectId": pid}).json()
    check("spec envelope", ai["status"] == "success" and ai["intent"] == "PENDING_APPROVALS" and ai["message"] and ai["sources"] is not None)
    check("action affordances", ai["actions"] and any("APPROVAL CHECKLIST" in a["label"] for a in ai["actions"]))
    sens = c.post("/ai/assistant", headers=H, json={"message": "Submit my application", "projectId": pid}).json()
    check("sensitive gate via alias", sens["requires_confirmation"] and sens["requires_confirmation"]["confirm_label"] == "CONFIRM")
    check("no guarantee language", "guarantee" not in ai["message"].lower())

    print("— SPA + honesty surfaces —")
    spa = httpx.get("http://127.0.0.1:8899/", timeout=10)
    check("SPA served", spa.status_code == 200 and "NIECP" in spa.text)
    intg = c.get("/integrations", headers=H).json()
    check("integration manager notice intact", any(i.get("notice") for i in intg["integrations"]))

    print(f"\n{PASSED} passed, {len(FAILED)} failed")
    if FAILED:
        print("FAILED:", FAILED)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
