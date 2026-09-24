"""Master Upgrade Prompt — tests for the Government Integration Manager,
DemoGovernmentAdapter, OfficialRedirectAdapter, ManualApplicationAdapter,
Government registry, Query Translator, audit correlation and the /ai/assistant
alias. Honesty invariants (DEMO never LIVE, synthetic everything, confirmation
gates) are asserted explicitly."""
from __future__ import annotations

import re

import pytest

def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _project(client, token, industry="electronics", **profile):
    import random

    r = client.post(
        "/api/v1/projects",
        json={"name": f"Upgrade Test {random.randint(1000000, 9999999)}"},
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    pid = r.json()["project"]["id"]
    client.patch(
        f"/api/v1/projects/{pid}/profile",
        json={
            "industry_code": industry,
            "state_code": "TN",
            "total_investment": 350000000,
            "number_of_employees": 45,
            "uses_hazardous_chemicals": False,
            **profile,
        },
        headers=_auth(token),
    )
    client.post(f"/api/v1/projects/{pid}/analysis", headers=_auth(token))
    return pid


DEMO_META_KEYS = ("environment", "data_source", "government_api", "authorization_status", "live", "notice")


class TestGovernmentRegistry:
    def test_registry_providers(self, client, user_token):
        r = client.get("/api/v1/integration-registry", headers=_auth(user_token))
        assert r.status_code == 200
        body = r.json()
        providers = {e["provider_code"]: e for e in body["registry"]}
        assert {"nsws", "tn_single_window", "apisetu", "niecp_demo_government"} <= set(providers)
        # nothing is live — never faked
        assert all(e["live"] is False for e in body["registry"])
        assert providers["nsws"]["authorization_status"] == "PENDING"
        assert providers["apisetu"]["authorization_status"] == "NOT_AUTHORIZED"
        demo = providers["niecp_demo_government"]
        assert demo["environment"] == "DEMO" and demo["is_demo"] is True
        assert demo["supported_operations"]
        # spec-required fields present
        for field in ("provider_name", "service_name", "jurisdiction", "authority", "official_portal_url",
                      "environment", "authorization_status", "supported_operations", "authentication_method",
                      "fallback_mode", "data_categories", "consent_required", "live", "source_type", "last_verified_at"):
            assert field in demo
        assert "will be activated only after formal authorization" in body["declaration"]

    def test_registry_requires_auth(self, client):
        assert client.get("/api/v1/integration-registry").status_code == 401


class TestDemoGovernmentFlow:
    def _prepared_application(self, client, token):
        pid = _project(client, token)
        da = client.get(f"/api/v1/demo/government/approvals?project_id={pid}", headers=_auth(token)).json()
        assert da["demo"]["environment"] == "DEMO" and da["demo"]["live"] is False
        assert "Not connected to a live government system" in da["notice"]
        code = next(a["code"] for a in da["approvals"] if a["demo_eligible"] and a["applicability"] == "APPLIES")
        r = client.post(
            f"/api/v1/projects/{pid}/applications",
            json={"title": "Upgrade demo flow", "approval_template_code": code},
            headers=_auth(token),
        )
        aid = r.json()["application"]["id"]
        assert client.post(f"/api/v1/projects/{pid}/applications/{aid}/prepare", headers=_auth(token)).status_code == 200
        c = client.post(f"/api/v1/projects/{pid}/applications/{aid}/confirm", headers=_auth(token))
        assert c.json()["application"]["status"] == "USER_CONFIRMED"
        return pid, aid

    def test_gates(self, client, user_token):
        pid, aid = self._prepared_application(client, user_token)
        # demo confirmation is mandatory
        r = client.post("/api/v1/demo/government/applications", json={"project_id": pid, "application_id": aid}, headers=_auth(user_token))
        assert r.status_code == 422
        # unprepared applications cannot be submitted
        r2 = client.post(
            f"/api/v1/projects/{pid}/applications",
            json={"title": "Gate test", "approval_template_code": next(
                a["code"] for a in client.get(f"/api/v1/demo/government/approvals?project_id={pid}", headers=_auth(user_token)).json()["approvals"]
                if a["demo_eligible"])},
            headers=_auth(user_token),
        )
        aid2 = r2.json()["application"]["id"]
        r = client.post("/api/v1/demo/government/applications", json={"project_id": pid, "application_id": aid2, "demo_confirmation": True}, headers=_auth(user_token))
        assert r.status_code == 422
        assert "Prepare" in r.json()["detail"]

    def test_full_lifecycle_with_honesty_fields(self, client, user_token, admin_token):
        pid, aid = self._prepared_application(client, user_token)
        r = client.post("/api/v1/demo/government/applications", json={"project_id": pid, "application_id": aid, "demo_confirmation": True}, headers=_auth(user_token))
        assert r.status_code == 201, r.text
        sub = r.json()
        # synthetic reference format
        assert re.fullmatch(r"NIECP-DEMO-\d{4}-\d{4}", sub["application_reference"])
        # the §5 honesty block on every transaction
        for key in DEMO_META_KEYS:
            assert key in sub["demo"]
        assert sub["demo"]["environment"] == "DEMO"
        assert sub["demo"]["data_source"] == "SYNTHETIC"
        assert sub["demo"]["government_api"] == "NOT_CONNECTED"
        assert sub["demo"]["authorization_status"] == "NOT_AUTHORIZED"
        assert sub["demo"]["live"] is False
        assert sub["correlation_id"]

        # double submit is rejected
        r2 = client.post("/api/v1/demo/government/applications", json={"project_id": pid, "application_id": aid, "demo_confirmation": True}, headers=_auth(user_token))
        assert r2.status_code == 409

        # status: query raised with a labelled synthetic query
        st = client.get(f"/api/v1/demo/government/applications/{aid}/status", headers=_auth(user_token)).json()
        assert st["status"] == "QUERY_RAISED"
        assert st["workflow"] == "DEMO WORKFLOW SIMULATION"
        q = st["queries"][0]
        assert q["is_demo"] is True and q["query_text"].startswith("[DEMO QUERY — SYNTHETIC]")

        # query translator on the demo query
        tr = client.post(f"/api/v1/projects/{pid}/queries/{q['id']}/translate", headers=_auth(user_token)).json()
        t = tr["translation"]
        assert t["source_status"] == "AI_INTERPRETATION"
        assert "verify against the official communication" in t["disclaimer"]
        assert t["what_is_missing"] and t["response_preparation"]["steps"]
        assert t["response_preparation"]["draft_outline"]

        # response gate + response
        r422 = client.post(f"/api/v1/demo/government/applications/{aid}/response", json={"query_id": q["id"], "response_text": "Point by point response here.", "confirm_response_submission": False}, headers=_auth(user_token))
        assert r422.status_code == 422
        r = client.post(f"/api/v1/demo/government/applications/{aid}/response", json={"query_id": q["id"], "response_text": "Point-by-point response with the requested documents attached.", "confirm_response_submission": True}, headers=_auth(user_token))
        assert r.status_code == 200
        assert r.json()["application"]["status"] == "USER_RESPONDED"

        # demo control advances to the synthetic approval
        adv = client.post(f"/api/v1/demo/government/applications/{aid}/advance", headers=_auth(user_token)).json()
        assert adv["status"] == "APPROVED"
        assert adv["valid_until"]
        assert adv["demo_approval_conditions"] and all("SYNTHETIC DEMO CONDITION" in c for c in adv["demo_approval_conditions"])

        # approval node propagated + renewal created (reused platform machinery)
        apps = client.get(f"/api/v1/projects/{pid}/applications", headers=_auth(user_token)).json()["applications"]
        mine = next(a for a in apps if a["id"] == aid)
        assert mine["status"] == "APPROVED" and mine["integration_mode"] == "DEMO"
        assert mine["is_demo"] is True and mine["official_reference"] == sub["application_reference"]
        rens = client.get(f"/api/v1/projects/{pid}/renewals", headers=_auth(user_token)).json()
        assert any(rn["title"].startswith("Renewal:") and rn.get("is_demo") for rn in rens["renewals"])

        # audit trail carries the new action + correlation + integration mode
        ev = client.get("/api/v1/admin/audit", params={"action": "DEMO_SUBMITTED", "limit": 50}, headers=_auth(admin_token)).json()["events"]
        assert ev and ev[0]["correlation_id"] == sub["correlation_id"]
        assert ev[0]["integration_mode"] == "DEMO" and ev[0]["provider"] == "niecp_demo_government"
        dec = client.get("/api/v1/admin/audit", params={"action": "DEMO_DECISION_RECORDED", "limit": 10}, headers=_auth(admin_token)).json()["events"]
        assert dec

    def test_demo_requires_auth(self, client):
        assert client.get("/api/v1/demo/government/applications/1").status_code == 401

    def test_demo_document_receipt(self, client, user_token):
        pid = _project(client, token=user_token)
        files = {"file": ("incorporation.txt", b"Certificate of Incorporation for the demo company. CIN U72900TN2026PTC000001.", "text/plain")}
        up = client.post(f"/api/v1/projects/{pid}/documents", files=files, headers=_auth(user_token))
        assert up.status_code in (200, 201), up.text
        doc_id = (up.json().get("document") or up.json())["id"]
        r = client.get(f"/api/v1/demo/government/documents/{doc_id}", headers=_auth(user_token)).json()
        assert r["demo"]["data_source"] == "SYNTHETIC"
        assert r["receipt_reference"].startswith("DEMO-RCPT-")
        assert "No government system received this document" in r["synthetic_acknowledgement"]


class TestExecutionChannels:
    def test_execution_options_never_live(self, client, user_token):
        pid = _project(client, token=user_token, uses_hazardous_chemicals=True)
        da = client.get(f"/api/v1/demo/government/approvals?project_id={pid}", headers=_auth(token=user_token)).json()
        code = next(a["code"] for a in da["approvals"] if a["demo_eligible"])
        r = client.post(f"/api/v1/projects/{pid}/applications", json={"title": "Channel test", "approval_template_code": code}, headers=_auth(user_token))
        aid = r.json()["application"]["id"]
        eo = client.get(f"/api/v1/projects/{pid}/applications/{aid}/execution-options", headers=_auth(user_token)).json()
        assert eo["recommended"] in ("OFFICIAL_REDIRECT", "MANUAL", "DEMO")  # never LIVE without authorization
        assert eo["channels"]["AUTHORIZED_API"]["available"] is False
        assert eo["channels"]["MANUAL"]["available"] is True
        assert eo["channels"]["DEMO"]["available"] is True
        assert eo["channels"]["DEMO"]["requires_confirmation"] is True
        assert "NIECP-AI never submits" in eo["declaration"]

    def test_official_redirect_uses_stored_url(self, client, user_token, admin_token):
        pid = _project(client, token=user_token)
        da = client.get(f"/api/v1/demo/government/approvals?project_id={pid}", headers=_auth(user_token)).json()
        with_portal = next((a["code"] for a in da["approvals"] if a["demo_eligible"]), None)
        r = client.post(f"/api/v1/projects/{pid}/applications", json={"title": "Redirect test", "approval_template_code": with_portal}, headers=_auth(user_token))
        aid = r.json()["application"]["id"]
        red = client.post(f"/api/v1/projects/{pid}/applications/{aid}/redirect", headers=_auth(user_token))
        if red.status_code == 200:  # approval stores a portal URL
            packet = red.json()["redirect"]
            assert packet["portal_url"].startswith("https://")
            assert "does not file applications" in packet["disclaimer"]
            ev = client.get("/api/v1/admin/audit", params={"action": "OFFICIAL_REDIRECT_OPENED", "limit": 5}, headers=_auth(admin_token)).json()["events"]
            assert ev and ev[0]["integration_mode"] == "OFFICIAL_REDIRECT"
        else:
            assert red.status_code == 404
            assert "does not guess" in red.json()["detail"]

    def test_manual_packet(self, client, user_token):
        pid = _project(client, token=user_token)
        da = client.get(f"/api/v1/demo/government/approvals?project_id={pid}", headers=_auth(user_token)).json()
        code = next(a["code"] for a in da["approvals"] if a["demo_eligible"])
        aid = client.post(f"/api/v1/projects/{pid}/applications", json={"title": "Manual test", "approval_template_code": code}, headers=_auth(user_token)).json()["application"]["id"]
        pkt = client.get(f"/api/v1/projects/{pid}/applications/{aid}/manual-packet", headers=_auth(user_token)).json()
        assert pkt["mode"] == "MANUAL"
        assert pkt["record_fields"] and pkt["checklist"]
        status_field = next(f for f in pkt["record_fields"] if f["field"] == "status")
        assert "APPROVED" in status_field["allowed"] and "QUERY_RAISED" in status_field["allowed"]
        assert "never generates references" in pkt["notice"]
        txt = client.get(f"/api/v1/projects/{pid}/applications/{aid}/manual-packet", params={"format": "text"}, headers=_auth(user_token))
        assert "MANUAL APPLICATION PACKET" in txt.text


class TestQueryTranslator:
    def test_translation_shape(self, client, user_token):
        pid = _project(client, token=user_token)
        r = client.post(
            f"/api/v1/projects/{pid}/queries",
            json={"query_text": "1. Submit the water balance diagram for the premises.\n2. Provide the accredited laboratory analysis report of effluent samples.", "authority": "TNPCB"},
            headers=_auth(user_token),
        )
        assert r.status_code == 201, r.text
        t = r.json()["translation"]
        assert len(t["asks"]) == 2
        assert "2 request(s)" in t["plain_language_explanation"]
        assert any("Water balance" in n["document"] for n in t["what_is_needed"])
        assert any("laboratory" in n["document"].lower() for n in t["what_is_needed"])
        assert "AI-generated explanation" in t["disclaimer"]
        # stored on the query row too
        q = r.json()["query"]
        assert q["translator"]["disclaimer"] == t["disclaimer"]

    def test_translate_endpoint(self, client, user_token):
        pid = _project(client, token=user_token)
        qid = client.post(f"/api/v1/projects/{pid}/queries", json={"query_text": "Clarify the site layout and access details."}, headers=_auth(user_token)).json()["query"]["id"]
        r = client.post(f"/api/v1/projects/{pid}/queries/{qid}/translate", headers=_auth(user_token))
        assert r.status_code == 200
        assert r.json()["translation"]["recommended_action"]


class TestAIAlias:
    def test_alias_shape_and_context(self, client, user_token):
        pid = _project(client, token=user_token)
        r = client.post("/api/v1/ai/assistant", json={"message": "What approvals do I need for my project?", "projectId": pid}, headers=_auth(user_token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "success"
        assert body["intent"] == "PENDING_APPROVALS"
        assert body["message"]
        assert body["actions"] and all("label" in a and "route" in a for a in body["actions"])
        assert any(str(pid) in a["route"] for a in body["actions"])

    def test_alias_sensitive_gates(self, client, user_token):
        r = client.post("/api/v1/ai/assistant", json={"message": "Submit my application to the government"}, headers=_auth(user_token))
        body = r.json()
        assert body["requires_confirmation"]["confirm_label"] == "CONFIRM"
        assert body["requires_confirmation"]["cancel_label"] == "CANCEL"
