"""
Seeds ref.normalized_job_titles -- a curated canonical-title taxonomy for
Step 29 (Occupation Classification).

Confirmed design decision before writing this: the initial taxonomy is
hand-curated, not auto-generated from real scraped titles or invented
freely by the classification job itself. It deliberately mirrors
ref.job_categories' existing scope (job_categories.py) -- tech and
business-support roles -- rather than attempting to cover the full real-
world variety RemoteOK's feed actually contains (retail, trades,
healthcare, aviation, hospitality all showed up in real sampling). That
broader scope was confirmed as a genuine future goal, not something this
seed module tries to solve on day one -- see this project's normalization
docstring/README notes on Step 29 for the fuller reasoning. Expanding
ref.job_categories itself to non-tech families is separate, larger,
future work; this taxonomy tracks whatever job_categories currently
covers, on purpose.

job_family here is a plain TEXT column (not an FK to ref.job_categories --
confirmed against the real schema before writing this), populated with
labels matching job_categories.py's existing child-category labels for
conceptual consistency, even though the database doesn't enforce that
relationship.

seniority_hint resolves against ref.experience_levels by code (entry,
junior, mid, senior, lead, principal, executive -- confirmed against the
real seed/experience_levels.py before writing this, not guessed). Not
every title needs a seniority hint -- a bare "Software Engineer" entry
deliberately has none, since it's the level-agnostic default a match can
fall back to when nothing else fits better.

This is a starting point, not a claim of completeness -- the same
"grows over time via curated seeding" pattern already established for
ref.skills. Expect to add entries as real unmatched jobs (status=
'no_match' after classification) reveal gaps.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from .base import SeedResult, upsert_many

# (normalized_title, job_family, seniority_code_or_None)
_TITLES: list[tuple[str, str, str | None]] = [
    # Backend Engineering
    ("Backend Engineer", "Backend Engineering", None),
    ("Senior Backend Engineer", "Backend Engineering", "senior"),
    ("Staff Backend Engineer", "Backend Engineering", "lead"),
    ("Junior Backend Engineer", "Backend Engineering", "junior"),
    # Frontend Engineering
    ("Frontend Engineer", "Frontend Engineering", None),
    ("Senior Frontend Engineer", "Frontend Engineering", "senior"),
    ("Junior Frontend Engineer", "Frontend Engineering", "junior"),
    # Full-stack Engineering
    ("Full-Stack Engineer", "Full-stack Engineering", None),
    ("Senior Full-Stack Engineer", "Full-stack Engineering", "senior"),
    ("Junior Full-Stack Engineer", "Full-stack Engineering", "junior"),
    ("Software Engineer", "Full-stack Engineering", None),
    ("Senior Software Engineer", "Full-stack Engineering", "senior"),
    ("Staff Software Engineer", "Full-stack Engineering", "lead"),
    ("Principal Software Engineer", "Full-stack Engineering", "principal"),
    ("Software Developer", "Full-stack Engineering", None),
    # Mobile Engineering
    ("Mobile Engineer", "Mobile Engineering", None),
    ("iOS Engineer", "Mobile Engineering", None),
    ("Android Engineer", "Mobile Engineering", None),
    ("Senior Mobile Engineer", "Mobile Engineering", "senior"),
    # DevOps / SRE / Platform
    ("DevOps Engineer", "DevOps / SRE / Platform", None),
    ("Site Reliability Engineer", "DevOps / SRE / Platform", None),
    ("Senior DevOps Engineer", "DevOps / SRE / Platform", "senior"),
    ("Platform Engineer", "DevOps / SRE / Platform", None),
    ("Cloud Infrastructure Engineer", "DevOps / SRE / Platform", None),
    # QA / Test Engineering
    ("QA Engineer", "QA / Test Engineering", None),
    ("Senior QA Engineer", "QA / Test Engineering", "senior"),
    ("Test Automation Engineer", "QA / Test Engineering", None),
    # Embedded / Hardware
    ("Embedded Software Engineer", "Embedded / Hardware", None),
    ("Hardware Engineer", "Embedded / Hardware", None),
    # Data Engineering
    ("Data Engineer", "Data Engineering", None),
    ("Senior Data Engineer", "Data Engineering", "senior"),
    ("Analytics Engineer", "Data Engineering", None),
    # Data Science
    ("Data Scientist", "Data Science", None),
    ("Senior Data Scientist", "Data Science", "senior"),
    ("Principal Data Scientist", "Data Science", "principal"),
    # Machine Learning Engineering
    ("Machine Learning Engineer", "Machine Learning Engineering", None),
    ("Senior Machine Learning Engineer", "Machine Learning Engineering", "senior"),
    ("AI Engineer", "Machine Learning Engineering", None),
    # Analytics / BI
    ("Data Analyst", "Analytics / BI", None),
    ("Senior Data Analyst", "Analytics / BI", "senior"),
    ("Business Intelligence Analyst", "Analytics / BI", None),
    # UX Design
    ("UX Designer", "UX Design", None),
    ("Senior UX Designer", "UX Design", "senior"),
    ("UX Researcher", "UX Design", None),
    # UI / Visual Design
    ("UI Designer", "UI / Visual Design", None),
    ("Visual Designer", "UI / Visual Design", None),
    ("Graphic Designer", "UI / Visual Design", None),
    # Product Design
    ("Product Designer", "Product Design", None),
    ("Senior Product Designer", "Product Design", "senior"),
    ("Lead Product Designer", "Product Design", "lead"),
    # Product Management
    ("Product Manager", "Product Management", None),
    ("Senior Product Manager", "Product Management", "senior"),
    ("Principal Product Manager", "Product Management", "principal"),
    ("Associate Product Manager", "Product Management", "entry"),
    # Technical Program Management
    ("Technical Program Manager", "Technical Program Management", None),
    ("Senior Technical Program Manager", "Technical Program Management", "senior"),
    ("Project Manager", "Technical Program Management", None),
    # Account Executive
    ("Account Executive", "Account Executive", None),
    ("Senior Account Executive", "Account Executive", "senior"),
    ("Enterprise Account Executive", "Account Executive", "senior"),
    ("Regional Sales Manager", "Account Executive", "lead"),
    # Sales Development
    ("Sales Development Representative", "Sales Development", "entry"),
    ("Business Development Representative", "Sales Development", "entry"),
    ("Field Sales Executive", "Sales Development", None),
    # Customer Success
    ("Customer Success Manager", "Customer Success", None),
    ("Senior Customer Success Manager", "Customer Success", "senior"),
    ("Client Onboarding Manager", "Customer Success", None),
    # Content Marketing
    ("Content Marketing Manager", "Content Marketing", None),
    ("Content Writer", "Content Marketing", None),
    ("Social Media Coordinator", "Content Marketing", "entry"),
    # Growth / Performance Marketing
    ("Growth Marketing Manager", "Growth / Performance Marketing", None),
    ("Performance Marketing Specialist", "Growth / Performance Marketing", None),
    ("Marketing Operations Specialist", "Growth / Performance Marketing", None),
    # Brand / Communications
    ("Brand Manager", "Brand / Communications", None),
    ("Communications Manager", "Brand / Communications", None),
    ("Marketing Specialist", "Brand / Communications", None),
    # Technical Support
    ("Technical Support Engineer", "Technical Support", None),
    ("Senior Technical Support Engineer", "Technical Support", "senior"),
    # General Customer Support
    ("Customer Support Specialist", "General Customer Support", None),
    ("Customer Support Representative", "General Customer Support", "entry"),
    ("Licensed Customer Service Representative", "General Customer Support", None),
    ("Partner Support Associate", "General Customer Support", "entry"),
    # Business Operations
    ("Business Operations Manager", "Business Operations", None),
    ("Operations Coordinator", "Business Operations", "entry"),
    ("Solutions Delivery Manager", "Business Operations", "lead"),
    ("Executive Assistant", "Business Operations", None),
    ("Administrative Assistant", "Business Operations", "entry"),
    ("Data Entry Administrator", "Business Operations", "entry"),
    # Supply Chain / Logistics
    ("Supply Chain Analyst", "Supply Chain / Logistics", None),
    ("Logistics Coordinator", "Supply Chain / Logistics", None),
    # Accounting
    ("Accountant", "Accounting", None),
    ("Senior Accountant", "Accounting", "senior"),
    ("Accounts Receivable Clerk", "Accounting", "entry"),
    ("Billing Executive", "Accounting", None),
    # FP&A
    ("Financial Analyst", "FP&A", None),
    ("Senior Financial Analyst", "FP&A", "senior"),
    ("Compensation & Benefits Manager", "FP&A", "lead"),
    # Recruiting / Talent Acquisition
    ("Recruiter", "Recruiting / Talent Acquisition", None),
    ("Senior Recruiter", "Recruiting / Talent Acquisition", "senior"),
    ("Talent Acquisition Specialist", "Recruiting / Talent Acquisition", None),
    # HR Generalist / People Ops
    ("HR Generalist", "HR Generalist / People Ops", None),
    ("Human Resources Coordinator", "HR Generalist / People Ops", "entry"),
    ("People Operations Manager", "HR Generalist / People Ops", "lead"),
    # Legal Counsel
    ("Legal Counsel", "Legal Counsel", None),
    ("Paralegal", "Legal Counsel", "entry"),
    # Compliance / Risk
    ("Compliance Analyst", "Compliance / Risk", None),
    ("Senior Governance Risk and Compliance Analyst", "Compliance / Risk", "senior"),
    # IT Helpdesk / Support
    ("IT Support Specialist", "IT Helpdesk / Support", None),
    ("Helpdesk Technician", "IT Helpdesk / Support", "entry"),
    # InfoSec / Cybersecurity
    ("Security Engineer", "InfoSec / Cybersecurity", None),
    ("Senior Security Engineer", "InfoSec / Cybersecurity", "senior"),
    # Leadership tiers -- first round, added after a real dry-run against
    # this project's actual 350 jobs showed several genuinely mismatched
    # leadership-title postings (e.g. "Head of Marketing" and "Head of
    # Design" both matching wrong, unrelated taxonomy entries) because no
    # department-head tier existed for most families -- only Engineering/
    # Data Science/Product Management had senior/lead/principal tiers.
    # "Head of X"/"Director of X" map to "principal" (most senior in
    # their function, but not full C-suite); "VP of X" maps to
    # "executive" -- distinguishing department leadership from full
    # C-suite roles like the existing "Chief Operating Officer" entry.
    # Not exhaustive -- added where real evidence showed a gap or where
    # the same real-world pattern clearly extends to a sibling family;
    # expect to keep adding as more real postings reveal further gaps,
    # same "curated, grows over time" pattern as ref.skills.
    ("Head of Marketing", "Growth / Performance Marketing", "principal"),
    ("Marketing Director", "Growth / Performance Marketing", "principal"),
    ("VP of Marketing", "Growth / Performance Marketing", "executive"),
    ("Head of Growth", "Growth / Performance Marketing", "principal"),
    ("Creative Director", "UI / Visual Design", "principal"),
    ("Head of Design", "Product Design", "principal"),
    ("VP of Design", "Product Design", "executive"),
    ("Head of Engineering", "Full-stack Engineering", "principal"),
    ("VP of Engineering", "Full-stack Engineering", "executive"),
    ("Director of Engineering", "Full-stack Engineering", "principal"),
    ("Head of Product", "Product Management", "principal"),
    ("VP of Product", "Product Management", "executive"),
    ("Head of Sales", "Account Executive", "principal"),
    ("VP of Sales", "Account Executive", "executive"),
    ("Head of Customer Success", "Customer Success", "principal"),
    ("Head of People", "HR Generalist / People Ops", "principal"),
    ("VP of People", "HR Generalist / People Ops", "executive"),
    ("Head of Operations", "Business Operations", "principal"),
    ("VP of Operations", "Business Operations", "executive"),
    ("Head of Finance", "FP&A", "principal"),
    ("Head of Data", "Data Engineering", "principal"),
    ("VP of Data", "Data Engineering", "executive"),
    # Executive / Leadership (no matching job_categories child -- broad
    # enough, and common enough in real sampled data, i.e. "Chief
    # Operating Officer", "Managing Director", to warrant its own family
    # even though ref.job_categories doesn't have a matching entry yet)
    ("Chief Operating Officer", "Executive Leadership", "executive"),
    ("Chief Financial Officer", "Executive Leadership", "executive"),
    ("Chief Technology Officer", "Executive Leadership", "executive"),
    ("Managing Director", "Executive Leadership", "executive"),
    ("Senior Executive", "Executive Leadership", "senior"),
]


def seed_normalized_job_titles(conn: Connection) -> SeedResult:
    seniority_ids = {
        code: exp_id
        for code, exp_id in conn.execute(
            text("SELECT code, experience_level_id FROM ref.experience_levels")
        )
    }

    rows = [
        {
            "normalized_title": title,
            "job_family": family,
            "seniority_hint": seniority_ids[seniority_code] if seniority_code else None,
        }
        for title, family, seniority_code in _TITLES
    ]

    return upsert_many(
        conn,
        schema="ref",
        table_name="normalized_job_titles",
        rows=rows,
        conflict_cols=("normalized_title",),
    )
