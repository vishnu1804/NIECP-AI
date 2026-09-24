"""
Profile fact extraction — the bridge between the ORM and the rule engine.

Everything the rule engine sees comes from here, so this module is also where
derived facts (such as "is a manufacturing industry" or "food related") are
computed deterministically. Derived facts are prefixed with `_` and are never
treated as user-entered data.
"""
from __future__ import annotations

import re
from typing import Any

from ..knowledge.data.industries import INDUSTRY_BY_CODE, question_sets_from_description
from ..models import Project, ProjectProfile
from ..ai.rule_engine import RuleContext

MANUFACTURING_INDUSTRIES = {
    "electronics",
    "manufacturing_general",
    "food_processing",
    "textile",
    "automobile",
    "chemical",
    "pharmaceutical",
    "renewable_energy",
    "biotechnology",
    "engineering",
    "mining",
    "recycling",
    "ewaste_processing",
}

FOOD_KEYWORDS = re.compile(
    r"\b(food|edible|dairy|milk|beverage|drink|juice|bakery|bread|biscuit|snack|spice|oil|flour|rice|sugar|confection|packaged food|ready to eat|meat|poultry|fish processing)\b",
    re.I,
)

# Fields that are always copied verbatim into the rule context.
PROFILE_FIELDS: tuple[str, ...] = (
    "organization_name",
    "applicant_name",
    "contact_email",
    "contact_phone",
    "organization_type",
    "enterprise_class",
    "pan",
    "gstin",
    "cin",
    "udyam_number",
    "startup_dpiit_number",
    "is_startup_recognized",
    "is_export_oriented",
    "project_type",
    "industry_code",
    "industry_other_description",
    "sub_industry",
    "project_stage",
    "state_code",
    "district",
    "city_village",
    "industrial_area",
    "in_notified_industrial_area",
    "land_tenure",
    "land_area_sqm",
    "built_up_area_sqm",
    "survey_number",
    "zoning_classification",
    "is_coastal_regulation_zone",
    "is_eco_sensitive_zone",
    "is_forest_land",
    "total_investment",
    "land_investment",
    "building_investment",
    "machinery_investment",
    "working_capital",
    "employment_generated",
    "women_employed",
    "production_type",
    "production_capacity",
    "raw_materials",
    "chemicals_used",
    "hazardous_substances",
    "uses_hazardous_chemicals",
    "is_mah_directed",
    "water_consumption_kld",
    "wastewater_generated_kld",
    "has_etp",
    "has_stp",
    "air_emissions_present",
    "emission_sources",
    "has_boiler",
    "boiler_capacity_tph",
    "has_dg_set",
    "dg_set_kva",
    "fire_risk_level",
    "electrical_load_kw",
    "htaht_connection_required",
    "e_waste_generated",
    "plastic_waste_generated",
    "hazardous_waste_generated",
    "hazardous_waste_tpa",
    "solid_waste_generated",
    "biomedical_waste_generated",
    "construction_demolition_waste",
    "battery_waste_generated",
    "uses_batteries",
    "workers_on_site",
    "is_factory_under_factories_act",
    "operates_in_shifts",
    "uses_contract_labour",
    "domestic_sales_annual",
    "export_annual",
    "import_annual",
    "number_of_employees",
    "power_requirement_kw",
    "water_requirement_kld",
)


def _enum_value(value: Any) -> Any:
    if value is None:
        return None
    return getattr(value, "value", value)


def build_facts(project: Project, profile: ProjectProfile | None) -> dict[str, Any]:
    """Flatten project + profile into the flat fact map rules evaluate against."""
    facts: dict[str, Any] = {
        "project_name": project.name,
        "project_description": project.description,
        "project_stage_value": _enum_value(project.stage),
        "project_is_demo": bool(project.is_demo),
    }

    if profile is None:
        facts["_is_manufacturing"] = False
        facts["_food_related"] = False
        return facts

    for field_name in PROFILE_FIELDS:
        facts[field_name] = _enum_value(getattr(profile, field_name, None))

    # normalise numeric strings that may arrive from form input
    for key in (
        "total_investment",
        "land_investment",
        "building_investment",
        "machinery_investment",
        "working_capital",
        "domestic_sales_annual",
        "export_annual",
        "import_annual",
    ):
        if facts.get(key) is not None:
            try:
                facts[key] = float(facts[key])
            except (TypeError, ValueError):
                facts[key] = None

    extra = profile.extra or {}
    if isinstance(extra, dict):
        for key, value in extra.items():
            facts.setdefault(key, value)

    code = str(facts.get("industry_code") or "").lower()
    industry = INDUSTRY_BY_CODE.get(code)

    # derived facts -------------------------------------------------------
    facts["_is_manufacturing"] = bool(code in MANUFACTURING_INDUSTRIES)
    if code == "other":
        desc = " ".join(
            str(x)
            for x in (
                facts.get("industry_other_description"),
                facts.get("production_type"),
                facts.get("sub_industry"),
                project.description,
            )
            if x
        )
        sets = question_sets_from_description(desc)
        facts["_derived_question_sets"] = sets
        facts["_is_manufacturing"] = any(
            s in sets for s in ("boiler", "chemicals", "engineering", "food", "pharma", "textile", "automobile")
        ) or bool(FOOD_KEYWORDS.search(desc)) or bool(re.search(r"\b(manufactur|plant|factory|unit|produc)\b", desc, re.I))
    elif industry is not None:
        facts["_derived_question_sets"] = list(industry.get("question_sets") or [])

    prod = " ".join(str(x) for x in (facts.get("production_type"), facts.get("production_capacity")) if x)
    facts["_food_related"] = bool(FOOD_KEYWORDS.search(prod)) or code in ("food_processing", "agriculture")

    facts["_industry_name"] = (industry or {}).get("name") if industry else (facts.get("industry_other_description") or None)
    return facts


def build_context(project: Project, profile: ProjectProfile | None) -> RuleContext:
    return RuleContext.build(build_facts(project, profile))


def profile_field_labels() -> dict[str, str]:
    """Human labels used when a rule reports missing facts."""
    labels = {
        "state_code": "State",
        "district": "District",
        "industry_code": "Industry",
        "total_investment": "Total investment",
        "built_up_area_sqm": "Built-up area",
        "land_area_sqm": "Land area",
        "water_consumption_kld": "Water consumption",
        "wastewater_generated_kld": "Wastewater generation",
        "number_of_employees": "Number of employees",
        "employment_generated": "Employment to be generated",
        "workers_on_site": "Workers on site",
        "has_boiler": "Whether a boiler is installed",
        "has_dg_set": "Whether a diesel generator set is installed",
        "electrical_load_kw": "Electrical load",
        "hazardous_waste_generated": "Whether hazardous waste is generated",
        "e_waste_generated": "Whether e-waste is generated",
        "plastic_waste_generated": "Whether plastic waste is generated",
        "production_type": "What the unit produces",
        "is_factory_under_factories_act": "Whether the unit is a factory",
        "land_tenure": "Land ownership / tenure",
        "organization_type": "Type of organization",
        "enterprise_class": "Enterprise classification",
        "export_annual": "Annual export value",
        "import_annual": "Annual import value",
        "udyam_number": "Udyam registration number",
        "gstin": "GSTIN",
        "cin": "CIN",
        "uses_contract_labour": "Whether contract labour is used",
        "fire_risk_level": "Fire risk level",
        "is_coastal_regulation_zone": "Whether the site is in a coastal regulation zone",
        "is_eco_sensitive_zone": "Whether the site is in an eco-sensitive zone",
        "is_forest_land": "Whether the site includes forest land",
    }
    for f in PROFILE_FIELDS:
        labels.setdefault(f, f.replace("_", " ").capitalize())
    return labels


FIELD_LABELS = profile_field_labels()


def label_for(field_name: str) -> str:
    return FIELD_LABELS.get(field_name, field_name.replace("_", " ").capitalize())
