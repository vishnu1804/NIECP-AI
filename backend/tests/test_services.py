"""Service tests: retrieval, readiness, questionnaire, localization, PWA."""
from __future__ import annotations

from app.database import SessionLocal


def _db():
    return SessionLocal()


class TestRetrieval:
    def test_retrieval_grounding(self):
        from app.ai.retrieval import retrieve

        db = _db()
        hits = retrieve(db, "what is consent to establish under the water act")
        assert hits, "corpus must ground environmental questions"
        assert hits[0].score > 0
        assert hits[0].citation_dict()["publisher"]
        db.close()

    def test_unavailable_query_returns_empty(self):
        from app.ai.retrieval import retrieve

        db = _db()
        hits = retrieve(db, "zagzwald quatloos flibberdigibbet xylonaut")
        assert hits == []  # caller must say "could not verify"
        db.close()

    def test_corpus_stats(self):
        from app.ai.retrieval import corpus_stats

        db = _db()
        stats = corpus_stats(db)
        assert stats["documents"] >= 20
        assert stats["chunks"] > stats["documents"]
        db.close()


class TestQuestionnaire:
    def test_dynamic_questions_by_industry(self):
        from app.models import Project, ProjectProfile
        from app.services.questionnaire import build_questionnaire

        db = _db()
        project = db.query(Project).filter(Project.is_demo.is_(True)).first()
        q = build_questionnaire(db, project)
        keys = {x["key"] for x in q["questions"]}
        # answered demo questions are excluded
        assert "has_dg_set" not in keys and "number_of_employees" not in keys
        db.close()

    def test_food_industry_gets_food_questions(self):
        from app.models import Project, ProjectProfile
        from app.services.questionnaire import build_questionnaire

        db = _db()
        project = db.query(Project).filter(Project.is_demo.is_(True)).first()
        project.profile.industry_code = "food_processing"
        q = build_questionnaire(db, project)
        sets = set(q["question_sets"])
        assert "food" in sets and "water" in sets
        project.profile.industry_code = "electronics"
        db.rollback()
        db.close()


class TestLocalization:
    def test_all_languages_cover_core_keys(self):
        from app.services.localization import STRINGS

        for key in ("nav.dashboard", "action.save", "ai.unavailable", "gov.unavailable", "easy.welcome"):
            for lang in ("en", "ta", "hi"):
                assert STRINGS[lang].get(key), f"{lang} missing {key}"

    def test_state_localization(self):
        from app.services.localization import localized_enum

        assert localized_enum("APPROVED", "ta") == "அனுமதிக்கப்பட்டது"
        assert localized_enum("APPROVED", "hi") == "स्वीकृत"


class TestPWAManifest:
    def test_manifest_valid(self):
        from app.services.pwa import build_manifest

        m = build_manifest()
        assert m["short_name"] == "NIECP-AI"
        assert m["display"] == "standalone"
        assert len(m["icons"]) >= 2


class TestSchemeEngine:
    def test_scheme_matching_uses_criteria(self):
        from app.models import Project
        from app.services.scheme_engine import evaluate_scheme_criteria

        db = _db()
        project = db.query(Project).filter(Project.is_demo.is_(True)).first()
        results = evaluate_scheme_criteria(db, project)
        assert results
        top = results[0]
        assert top["verdict"] in ("POSSIBLY_RELEVANT", "NEEDS_MORE_INFO", "LIKELY_NOT_APPLICABLE")
        for c in top["criteria"]:
            assert c["state"] in ("MET", "NOT_MET", "INFO_REQUIRED")
        db.close()


class TestReadiness:
    def test_readiness_components(self):
        from app.models import Project
        from app.services.readiness import compute_readiness

        db = _db()
        project = db.query(Project).filter(Project.is_demo.is_(True)).first()
        payload = compute_readiness(db, project, persist=False)
        keys = {c["key"] for c in payload["components"]}
        assert {"profile", "documents", "eligibility", "prerequisites", "applications", "compliance"} <= keys
        assert "not a probability of approval" in payload["disclaimer"]
        assert 0 <= payload["overall"] <= 100
        db.close()


class TestNextActions:
    def test_actions_from_state(self):
        from app.models import Project
        from app.services.next_action import next_best_actions

        db = _db()
        project = db.query(Project).filter(Project.is_demo.is_(True)).first()
        actions = next_best_actions(db, project)
        types = [a["type"] for a in actions]
        assert "QUERY" in types  # demo project has an open query
        db.close()
