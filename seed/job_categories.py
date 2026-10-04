"""
Seeds ref.job_categories — a 2-level functional taxonomy. Parents are
inserted first (pass 1), then children resolve parent_category_id by code
(pass 2), so the self-referencing FK never fails mid-seed regardless of
row order in the source list.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from .base import SeedResult, upsert_many

# top-level (code, label)
_PARENTS = [
    ("engineering", "Engineering"),
    ("data_ai", "Data & AI"),
    ("design", "Design"),
    ("product", "Product"),
    ("sales", "Sales"),
    ("marketing", "Marketing"),
    ("customer_support", "Customer Support"),
    ("operations", "Operations"),
    ("finance", "Finance & Accounting"),
    ("hr_people", "HR & People"),
    ("legal", "Legal & Compliance"),
    ("it_security", "IT & Security"),
    ("healthcare", "Healthcare"),
    ("education", "Education"),
    ("retail", "Retail"),
    ("hospitality", "Hospitality & Tourism"),
    ("construction", "Construction"),
    ("manufacturing", "Manufacturing"),
    ("trades", "Trades & Services"),
    ("transport", "Transport & Logistics"),
    ("agriculture", "Agriculture"),
    ("government", "Government & Public Sector"),
    ("media", "Media & Communications"),
    ("creative", "Creative & Arts"),
    ("nonprofit", "Nonprofit & NGO"),
    ("realestate", "Real Estate & Property"),
    ("sports", "Sports & Fitness"),
    ("beauty_health", "Beauty & Wellness"),
    ("science", "Science & Research"),
    ("insurance", "Insurance & Banking"),
    ("security", "Security & Facilities"),
    ("it_services", "IT Services"),
    ("miscellaneous", "Miscellaneous"),
    ("leadership", "Leadership"),
]

# (code, label, parent_code)
_CHILDREN = [
    ("swe_backend", "Backend Engineering", "engineering"),
    ("swe_frontend", "Frontend Engineering", "engineering"),
    ("swe_fullstack", "Full-stack Engineering", "engineering"),
    ("swe_mobile", "Mobile Engineering", "engineering"),
    ("devops_sre", "DevOps / SRE / Platform", "engineering"),
    ("qa_test", "QA / Test Engineering", "engineering"),
    ("embedded_hw", "Embedded / Hardware", "engineering"),
    ("data_engineering", "Data Engineering", "data_ai"),
    ("data_science", "Data Science", "data_ai"),
    ("ml_engineering", "Machine Learning Engineering", "data_ai"),
    ("analytics", "Analytics / BI", "data_ai"),
    ("ux_design", "UX Design", "design"),
    ("ui_design", "UI / Visual Design", "design"),
    ("product_design", "Product Design", "design"),
    ("product_management", "Product Management", "product"),
    ("technical_pm", "Technical Program Management", "product"),
    ("sales_ae", "Account Executive", "sales"),
    ("sales_sdr", "Sales Development", "sales"),
    ("customer_success", "Customer Success", "sales"),
    ("marketing_content", "Content Marketing", "marketing"),
    ("marketing_growth", "Growth / Performance Marketing", "marketing"),
    ("marketing_brand", "Brand / Communications", "marketing"),
    ("support_technical", "Technical Support", "customer_support"),
    ("support_general", "General Customer Support", "customer_support"),
    ("ops_business", "Business Operations", "operations"),
    ("ops_supply_chain", "Supply Chain / Logistics", "operations"),
    ("finance_accounting", "Accounting", "finance"),
    ("finance_fp&a", "FP&A", "finance"),
    ("hr_recruiting", "Recruiting / Talent Acquisition", "hr_people"),
    ("hr_generalist", "HR Generalist / People Ops", "hr_people"),
    ("legal_counsel", "Legal Counsel", "legal"),
    ("compliance", "Compliance / Risk", "legal"),
    ("it_helpdesk", "IT Helpdesk / Support", "it_security"),
    ("security_infosec", "InfoSec / Cybersecurity", "it_security"),
    ("hc_nursing", "Nursing", "healthcare"),
    ("hc_doctors", "Physicians", "healthcare"),
    ("hc_allied", "Allied Health", "healthcare"),
    ("hc_admin", "Healthcare Administration", "healthcare"),
    ("edu_teaching", "Teaching", "education"),
    ("edu_university", "Higher Education", "education"),
    ("edu_admin", "Education Administration", "education"),
    ("retail_store", "Retail Sales", "retail"),
    ("retail_wholesale", "Wholesale / Distribution", "retail"),
    ("hosp_hotels", "Hotels & Lodging", "hospitality"),
    ("hosp_food", "Restaurants & Catering", "hospitality"),
    ("hosp_tourism", "Tourism", "hospitality"),
    ("cons_trades", "Construction Trades", "construction"),
    ("cons_management", "Construction Management", "construction"),
    ("mfg_production", "Production", "manufacturing"),
    ("trade_mechanics", "Mechanics", "trades"),
    ("trade_beauty", "Beauty & Personal Care", "trades"),
    ("trade_services", "Other Services", "trades"),
    ("transport_road", "Road Transport", "transport"),
    ("transport_aviation", "Aviation", "transport"),
    ("transport_maritime", "Maritime", "transport"),
    ("transport_rail", "Rail", "transport"),
    ("agri_farming", "Farming & Livestock", "agriculture"),
    ("agri_forestry", "Forestry", "agriculture"),
    ("gov_admin", "Public Administration", "government"),
    ("gov_security", "Public Safety", "government"),
    ("gov_public_services", "Public Services", "government"),
    ("media_journalism", "Journalism", "media"),
    ("media_production", "Media Production", "media"),
    ("creative_arts", "Arts & Entertainment", "creative"),
    ("creative_writing", "Writing", "creative"),
    ("nonprofit_work", "Nonprofit Work", "nonprofit"),
    ("realestate_brokerage", "Real Estate", "realestate"),
    ("sports_fitness", "Sports & Fitness", "sports"),
    ("beauty_wellness", "Beauty & Wellness", "beauty_health"),
    ("sci_research", "Research", "science"),
    ("ins_banking", "Banking & Insurance", "insurance"),
    ("security_facilities", "Security & Facilities", "security"),
    ("it_services", "IT Services", "it_services"),
    ("executive_leadership", "Executive Leadership", "leadership"),
    ("misc_general", "General & Other", "miscellaneous"),
]


def seed_job_categories(conn: Connection) -> SeedResult:
    parent_rows = [
        {
            "code": code,
            "label": label,
            "description": None,
            "sort_order": i,
            "parent_category_id": None,
        }
        for i, (code, label) in enumerate(_PARENTS, start=1)
    ]
    result = upsert_many(
        conn,
        schema="ref",
        table_name="job_categories",
        rows=parent_rows,
        conflict_cols=("code",),
    )

    parent_ids = {
        r.code: r.job_category_id
        for r in conn.execute(text("SELECT code, job_category_id FROM ref.job_categories"))
    }
    child_rows = [
        {
            "code": code,
            "label": label,
            "description": None,
            "sort_order": i,
            "parent_category_id": parent_ids[parent_code],
        }
        for i, (code, label, parent_code) in enumerate(_CHILDREN, start=100)
    ]
    child_result = upsert_many(
        conn,
        schema="ref",
        table_name="job_categories",
        rows=child_rows,
        conflict_cols=("code",),
    )

    result.inserted += child_result.inserted
    result.updated += child_result.updated
    result.unchanged += child_result.unchanged
    result.errors += child_result.errors
    return result
