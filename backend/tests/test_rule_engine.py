"""Rule engine tests: parser safety, semantics, honesty degradation."""
from __future__ import annotations

import pytest

from app.ai.rule_engine import (
    RuleContext,
    RuleSyntaxError,
    evaluate_rule,
    parse_rule,
    required_fact_names,
)


class TestParser:
    def test_all_catalogue_rules_parse(self):
        from app.knowledge.data.approval_data import APPROVALS
        from app.knowledge.data.scheme_data import SCHEMES

        for a in APPROVALS:
            parse_rule(a["rule"])
        for s in SCHEMES:
            for c in s["eligibility_criteria"]:
                parse_rule(c["expression"])

    def test_rejects_injection(self):
        with pytest.raises(RuleSyntaxError):
            parse_rule("__import__('os').system('ls')")
        with pytest.raises(RuleSyntaxError):
            parse_rule("has('x') ; import os")
        with pytest.raises(RuleSyntaxError):
            parse_rule("[].__class__")

    def test_no_eval_in_grammar(self):
        # unknown function names are rejected
        with pytest.raises(RuleSyntaxError):
            parse_rule("eval('1+1')")


class TestSemantics:
    def test_applies_on_matching_facts(self):
        r = evaluate_rule("num('number_of_employees',0) >= 20", RuleContext.build({"number_of_employees": 45}), "t")
        assert r.produced == "APPLIES"
        assert r.facts_used == {"number_of_employees": 45}

    def test_not_applicable_on_known_false(self):
        r = evaluate_rule("num('number_of_employees',0) >= 20", RuleContext.build({"number_of_employees": 5}), "t")
        assert r.produced == "NOT_APPLICABLE"

    def test_unknown_when_facts_missing(self):
        r = evaluate_rule("num('number_of_employees',0) >= 20", RuleContext.build({}), "t")
        assert r.produced == "UNKNOWN"
        assert "number_of_employees" in r.facts_missing

    def test_information_required_is_unknown(self):
        assert evaluate_rule("information_required('x')", RuleContext.build({}), "t").produced == "UNKNOWN"
        assert evaluate_rule("information_required('x')", RuleContext.build({"x": 1}), "t").produced == "NOT_APPLICABLE"

    def test_three_valued_not(self):
        # unknown `not` stays unknown — never flips to true
        r = evaluate_rule("not truthy('has_boiler')", RuleContext.build({}), "t")
        assert r.produced == "UNKNOWN"
        r2 = evaluate_rule("not truthy('has_boiler')", RuleContext.build({"has_boiler": False}), "t")
        assert r2.produced == "APPLIES"

    def test_explicit_false_is_known(self):
        r = evaluate_rule(
            "truthy('state_code') and not truthy('is_factory_under_factories_act')",
            RuleContext.build({"state_code": "TN", "is_factory_under_factories_act": False}),
            "t",
        )
        assert r.produced == "APPLIES"

    def test_kleene_and(self):
        # False AND unknown -> False (definite)
        r = evaluate_rule("truthy('a') and truthy('b')", RuleContext.build({"a": False}), "t")
        assert r.produced == "NOT_APPLICABLE"
        # True AND unknown -> unknown
        r2 = evaluate_rule("truthy('a') and truthy('b')", RuleContext.build({"a": True}), "t")
        assert r2.produced == "UNKNOWN"

    def test_helpers(self):
        ctx = RuleContext.build({"industry_code": "MINING", "state_code": "tn", "raw_materials": ["sand"]})
        assert evaluate_rule("industry_in(['mining'])", ctx, "t").produced == "APPLIES"
        assert evaluate_rule("state_in(['TN'])", ctx, "t").produced == "APPLIES"
        assert evaluate_rule("count('raw_materials') > 0", ctx, "t").produced == "APPLIES"
        assert evaluate_rule("anyof('raw_materials', ['gravel','sand'])", ctx, "t").produced == "APPLIES"

    def test_required_fact_names(self):
        names = required_fact_names("truthy('has_boiler') or num('boiler_capacity_tph',0) > 0")
        assert "has_boiler" in names and "boiler_capacity_tph" in names


class TestProfileFacts:
    def test_manufacturing_detection(self):
        from app.models import Project, ProjectProfile
        from app.services.profile_facts import build_facts

        p = Project(id=1, name="X", slug="x", created_by=1)
        prof = ProjectProfile(project_id=1, industry_code="food_processing", production_type="milk processing")
        facts = build_facts(p, prof)
        assert facts["_is_manufacturing"] is True
        assert facts["_food_related"] is True

    def test_other_industry_derivation(self):
        from app.models import Project, ProjectProfile
        from app.services.profile_facts import build_facts

        p = Project(id=1, name="X", slug="x", created_by=1, description="marine diesel engine repair workshop")
        prof = ProjectProfile(project_id=1, industry_code="other", industry_other_description="engine repair with welding and DG sets")
        facts = build_facts(p, prof)
        assert "dgset" in facts["_derived_question_sets"]
