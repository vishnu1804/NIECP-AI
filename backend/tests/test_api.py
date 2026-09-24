"""API integration tests: auth, projects, analysis, documents, applications,
assistant honesty, integrations honesty."""
from __future__ import annotations

import uuid


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


class TestAuth:
    def test_health(self, client):
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        assert r.json()["seeded"] is True

    def test_register_login_flow(self, client, user_token):
        r = client.get("/api/v1/auth/me", headers=_auth(user_token))
        assert r.status_code == 200
        assert r.json()["user"]["platform_role"] in ("APPLICANT", "ENTREPRENEUR", "MSME")

    def test_weak_password_rejected(self, client):
        r = client.post("/api/v1/auth/register", json={"email": "weak@t.in", "password": "abc", "full_name": "Weak"})
        assert r.status_code == 422

    def test_wrong_password(self, client):
        r = client.post("/api/v1/auth/login", json={"email": "admin@niecp.local", "password": "wrong"})
        assert r.status_code == 401

    def test_protected_requires_token(self, client):
        assert client.get("/api/v1/projects").status_code == 401

    def test_lockout_after_failures(self, client):
        import random

        email = f"lock{random.randint(10000,99999)}@t.in"
        client.post("/api/v1/auth/register", json={"email": email, "password": "Lockout!Pass1", "full_name": "Lockout User"})
        for _ in range(5):
            client.post("/api/v1/auth/login", json={"email": email, "password": "nope"})
        r = client.post("/api/v1/auth/login", json={"email": email, "password": "Lockout!Pass1"})
        assert r.status_code == 401
        assert "locked" in r.json()["detail"].lower()


class TestAnalysisFlow:
    def _project(self, client, token, industry="chemical", **profile):
        import random, uuid
        r = client.post("/api/v1/projects", json={"name": f"Analysis Test {random.randint(100000,999999)}"}, headers=_auth(token))
        pid = r.json()["project"]["id"]
        client.patch(
            f"/api/v1/projects/{pid}/profile",
            json={"industry_code": industry, "state_code": "MH", "total_investment": 800000000, "number_of_employees": 60, "uses_hazardous_chemicals": True, "hazardous_waste_generated": True, **profile},
            headers=_auth(token),
        )
        return pid

    def test_analysis_produces_verdicts(self, client, user_token):
        pid = self._project(client, user_token)
        r = client.post(f"/api/v1/projects/{pid}/analysis", headers=_auth(user_token))
        assert r.status_code == 200
        body = r.json()
        codes = {a["template_code"] for a in body["approvals"]}
        assert "spcb_consent_to_establish" in codes
        assert "factory_licence" in codes
        # chemical + huge investment should trigger EC conditionally
        ec = next(a for a in body["approvals"] if a["template_code"] == "environment_clearance")
        assert ec["applicability"] in ("APPLIES", "CONDITIONAL")
        assert ec["legal_basis"]  # EIA notification cited

    def test_verdicts_carry_provenance(self, client, user_token):
        pid = self._project(client, user_token, industry="food_processing", production_type="fruit juice bottling")
        r = client.post(f"/api/v1/projects/{pid}/analysis", headers=_auth(user_token))
        fssai = next(a for a in r.json()["approvals"] if a["template_code"] == "fssai_licence")
        assert fssai["source_status"] in ("REQUIRES_VERIFICATION", "VERIFIED_GOV_SOURCE")
        assert any(rq["title"] for rq in fssai["requirements"])

    def test_graph_and_critical_path(self, client, user_token):
        pid = self._project(client, user_token)
        client.post(f"/api/v1/projects/{pid}/analysis", headers=_auth(user_token))
        g = client.get(f"/api/v1/projects/{pid}/graph", headers=_auth(user_token)).json()
        assert len(g["nodes"]) > 10 and len(g["edges"]) > 10
        cp = client.get(f"/api/v1/projects/{pid}/critical-path", headers=_auth(user_token)).json()
        assert len(cp["steps"]) > 0

    def test_analysis_requires_industry(self, client, user_token):
        r = client.post("/api/v1/projects", json={"name": f"No Industry {uuid.uuid4().hex[:6]}"}, headers=_auth(user_token))
        pid = r.json()["project"]["id"]
        r2 = client.post(f"/api/v1/projects/{pid}/analysis", headers=_auth(user_token))
        assert r2.status_code == 422


class TestDocuments:
    def test_upload_and_validate(self, client, user_token):
        import uuid
        r = client.post("/api/v1/projects", json={"name": f"Doc Test {uuid.uuid4().hex[:6]}"}, headers=_auth(user_token))
        pid = r.json()["project"]["id"]
        client.patch(f"/api/v1/projects/{pid}/profile", json={"organization_name": "Doc Test Industries", "state_code": "TN", "industry_code": "manufacturing_general"}, headers=_auth(user_token))
        docx = _docx("CERTIFICATE OF INCORPORATION Doc Test Industries Private Limited CIN U12345TN2020PTC123456 PAN AABCU9603R1 Tamil Nadu")
        r = client.post(
            f"/api/v1/projects/{pid}/documents",
            files={"file": ("inc.docx", docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            data={"title": "Incorporation", "category": "BUSINESS"},
            headers=_auth(user_token),
        )
        assert r.status_code == 201, r.text
        doc = r.json()["document"]
        assert doc["ai_document_type"] == "Certificate of Incorporation"
        kinds = [f["severity"] for f in doc["validation"]["findings"]]
        assert "PASS" in kinds
        # profile mismatch (PAN not in profile → info; name match → pass)
        assert doc["validation"]["disclaimer"]

    def test_blocked_extension(self, client, user_token):
        r = client.post("/api/v1/projects", json={"name": f"Sec Test {uuid.uuid4().hex[:6]}"}, headers=_auth(user_token))
        pid = r.json()["project"]["id"]
        r2 = client.post(
            f"/api/v1/projects/{pid}/documents",
            files={"file": ("evil.exe", b"MZ...", "application/x-msdownload")},
            headers=_auth(user_token),
        )
        assert r2.status_code == 422

    def test_delete_is_audited(self, client, user_token, admin_token):
        import uuid
        r = client.post("/api/v1/projects", json={"name": f"Del Test {uuid.uuid4().hex[:6]}"}, headers=_auth(user_token))
        pid = r.json()["project"]["id"]
        r2 = client.post(
            f"/api/v1/projects/{pid}/documents",
            files={"file": ("a.txt", b"hello world content", "text/plain")},
            headers=_auth(user_token),
        )
        did = r2.json()["document"]["id"]
        assert client.delete(f"/api/v1/projects/{pid}/documents/{did}", headers=_auth(user_token)).status_code == 200
        ev = client.get("/api/v1/admin/audit?action=document.delete", headers=_auth(admin_token)).json()
        assert any(e["resource_id"] == str(did) for e in ev["events"])


def _docx(text: str) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    xml = (
        '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
        + f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
        + "</w:body></w:document>"
    )
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/></Types>',
        )
        zf.writestr("word/document.xml", xml)
    return buf.getvalue()


class TestApplicationWorkflow:
    def test_prepare_confirm_status(self, client, user_token):
        r = client.post("/api/v1/projects", json={"name": f"App Flow {uuid.uuid4().hex[:6]}"}, headers=_auth(user_token))
        pid = r.json()["project"]["id"]
        client.patch(f"/api/v1/projects/{pid}/profile", json={"industry_code": "it_ites", "state_code": "KA"}, headers=_auth(user_token))
        client.post(f"/api/v1/projects/{pid}/analysis", headers=_auth(user_token))
        r = client.post(f"/api/v1/projects/{pid}/applications", json={"title": "GST registration", "approval_template_code": "gst_registration"}, headers=_auth(user_token))
        aid = r.json()["application"]["id"]
        # prepare + confirm
        assert client.post(f"/api/v1/projects/{pid}/applications/{aid}/prepare", headers=_auth(user_token)).status_code == 200
        c = client.post(f"/api/v1/projects/{pid}/applications/{aid}/confirm", headers=_auth(user_token))
        assert c.json()["application"]["user_confirmed_at"]
        # status without confirmation -> 422
        r422 = client.post(f"/api/v1/projects/{pid}/applications/{aid}/status", json={"status": "SUBMITTED", "self_reported_confirmation": False}, headers=_auth(user_token))
        assert r422.status_code == 422
        ok = client.post(f"/api/v1/projects/{pid}/applications/{aid}/status", json={"status": "SUBMITTED", "self_reported_confirmation": True}, headers=_auth(user_token))
        assert ok.json()["application"]["status"] == "SUBMITTED"
        assert ok.json()["application"]["submitted_by_user"] is True

    def test_official_reference_requires_confirmation(self, client, user_token):
        r = client.post("/api/v1/projects", json={"name": f"Ref Test {uuid.uuid4().hex[:6]}"}, headers=_auth(user_token))
        pid = r.json()["project"]["id"]
        r2 = client.post(f"/api/v1/projects/{pid}/applications", json={"title": "Ref Test Application"}, headers=_auth(user_token))
        aid = r2.json()["application"]["id"]
        r3 = client.patch(f"/api/v1/projects/{pid}/applications/{aid}", json={"official_reference": "FAKE-123"}, headers=_auth(user_token))
        assert r3.status_code == 422
        r4 = client.patch(f"/api/v1/projects/{pid}/applications/{aid}", json={"official_reference": "REAL-1", "official_reference_confirmation": True}, headers=_auth(user_token))
        assert r4.status_code == 200
        assert r4.json()["application"]["official_reference_source"] == "USER_PROVIDED"


class TestAssistantHonesty:
    def test_sensitive_action_requires_confirmation(self, client, user_token):
        r = client.post("/api/v1/projects", json={"name": f"AI Test {uuid.uuid4().hex[:6]}"}, headers=_auth(user_token))
        pid = r.json()["project"]["id"]
        r2 = client.post("/api/v1/assistant/chat", json={"message": "Please submit this application now", "project_id": pid}, headers=_auth(user_token))
        body = r2.json()
        assert body["requires_confirmation"]["action"] == "SUBMIT_APPLICATION"
        assert body["requires_confirmation"]["confirm_label"] == "CONFIRM"

    def test_unverifiable_question_says_so(self, client, user_token):
        r = client.post("/api/v1/assistant/chat", json={"message": "What is the air speed velocity of an unladen swallow in my factory"}, headers=_auth(user_token))
        body = r.json()
        assert "could not verify" in body["answer"].lower() or body["status"] in ("INFORMATION_UNAVAILABLE", "REQUIRES_VERIFICATION")

    def test_grounding_sources_present(self, client, user_token):
        r = client.post("/api/v1/assistant/chat", json={"message": "explain consent to establish"}, headers=_auth(user_token))
        body = r.json()
        assert body["intent"] in ("EXPLAIN_APPROVAL", "GENERAL")
        assert body["sources"], "regulatory answers must carry sources"


class TestIntegrationsHonesty:
    def test_integrations_report_manual_mode(self, client, user_token):
        r = client.get("/api/v1/integrations", headers=_auth(user_token)).json()
        codes = {i["code"]: i for i in r["integrations"]}
        assert codes["nsws"]["status"] in ("MANUAL_MODE", "NOT_CONNECTED")
        assert codes["nsws"]["notice"]  # transparent notice present
        assert "Official integration is currently unavailable" in codes["nsws"]["notice"]

    def test_health_check_disabled_reports_skipped(self, client, user_token):
        r = client.post("/api/v1/integrations/apisetu/health-check", headers=_auth(user_token)).json()
        assert r.get("skipped") is True or r.get("http_status") is not None
        assert "portal" in r or "reason" in r


class TestRBAC:
    def test_admin_required(self, client, user_token):
        assert client.get("/api/v1/admin/overview", headers=_auth(user_token)).status_code == 403

    def test_admin_allowed(self, client, admin_token):
        r = client.get("/api/v1/admin/overview", headers=_auth(admin_token))
        assert r.status_code == 200
        assert r.json()["counts"]["users"] >= 2

    def test_project_isolation(self, client, user_token, demo_token):
        r = client.post("/api/v1/projects", json={"name": f"Isolated {uuid.uuid4().hex[:6]}"}, headers=_auth(user_token))
        pid = r.json()["project"]["id"]
        # demo user cannot access it
        r2 = client.get(f"/api/v1/projects/{pid}", headers=_auth(demo_token))
        assert r2.status_code == 403


class TestDemoDiscipline:
    def test_demo_project_labelled(self, client, demo_token):
        projects = client.get("/api/v1/projects", headers=_auth(demo_token)).json()["projects"]
        demo = [p for p in projects if p["is_demo"]]
        assert demo and "[DEMO]" in demo[0]["name"]

    def test_demo_applications_marked(self, client, demo_token):
        projects = client.get("/api/v1/projects", headers=_auth(demo_token)).json()["projects"]
        demo = [p for p in projects if p["is_demo"]]
        if not demo:
            return
        pid = demo[0]["id"]
        apps = client.get(f"/api/v1/projects/{pid}/applications", headers=_auth(demo_token)).json()["applications"]
        demo_apps = [a for a in apps if a["is_demo"]]
        assert demo_apps
        assert demo_apps[0]["official_reference_source"] == "DEMO"
