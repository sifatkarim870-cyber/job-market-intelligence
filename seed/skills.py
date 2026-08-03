"""
Seeds ref.skills — a curated initial vocabulary (~180 skills) spanning
common technical and soft skills, enough for the first scraper (RemoteOK)
to have real match targets. `normalized_skill_name` is computed via
utils.normalize_name; `aliases` captures common abbreviations so early
rule-based extraction (Step 24) has something to match against immediately.
"""
from __future__ import annotations

from sqlalchemy import Connection, text

from .base import SeedResult, upsert_many
from .utils import normalize_name

# (skill_name, category_name, aliases, is_technology)
_SKILLS: list[tuple[str, str, list[str], bool]] = [
    # Programming Languages
    ("Python", "Programming Language", ["py"], True),
    ("JavaScript", "Programming Language", ["js", "ecmascript"], True),
    ("TypeScript", "Programming Language", ["ts"], True),
    ("Java", "Programming Language", [], True),
    ("Go", "Programming Language", ["golang"], True),
    ("Rust", "Programming Language", [], True),
    ("C", "Programming Language", [], True),
    ("C++", "Programming Language", ["cpp"], True),
    ("C#", "Programming Language", ["csharp", "dotnet c#"], True),
    ("Ruby", "Programming Language", [], True),
    ("PHP", "Programming Language", [], True),
    ("Swift", "Programming Language", [], True),
    ("Kotlin", "Programming Language", [], True),
    ("Scala", "Programming Language", [], True),
    ("R", "Programming Language", [], True),
    ("SQL", "Programming Language", [], True),
    ("Bash", "Programming Language", ["shell scripting"], True),
    ("Elixir", "Programming Language", [], True),
    ("Perl", "Programming Language", [], True),
    ("Dart", "Programming Language", [], True),
    # Frameworks
    ("React", "Framework", ["react.js", "reactjs"], True),
    ("Angular", "Framework", [], True),
    ("Vue.js", "Framework", ["vue"], True),
    ("Svelte", "Framework", [], True),
    ("Next.js", "Framework", ["nextjs"], True),
    ("Django", "Framework", [], True),
    ("Flask", "Framework", [], True),
    ("FastAPI", "Framework", [], True),
    ("Ruby on Rails", "Framework", ["rails"], True),
    ("Spring Boot", "Framework", ["spring"], True),
    ("Express.js", "Framework", ["express"], True),
    ("Laravel", "Framework", [], True),
    ("ASP.NET", "Framework", ["dotnet"], True),
    ("Node.js", "Framework", ["nodejs", "node"], True),
    ("Flutter", "Framework", [], True),
    ("React Native", "Framework", [], True),
    # Libraries
    ("Pandas", "Library", [], True),
    ("NumPy", "Library", [], True),
    ("PyTorch", "Library", [], True),
    ("TensorFlow", "Library", [], True),
    ("scikit-learn", "Library", ["sklearn"], True),
    ("Redux", "Library", [], True),
    ("jQuery", "Library", [], True),
    # Databases
    ("PostgreSQL", "Database", ["postgres"], True),
    ("MySQL", "Database", [], True),
    ("MongoDB", "Database", [], True),
    ("Redis", "Database", [], True),
    ("SQLite", "Database", [], True),
    ("Elasticsearch", "Database", [], True),
    ("Cassandra", "Database", [], True),
    ("DynamoDB", "Database", [], True),
    ("Oracle Database", "Database", ["oracle db"], True),
    ("Microsoft SQL Server", "Database", ["mssql", "sql server"], True),
    ("Snowflake", "Database", [], True),
    ("BigQuery", "Database", [], True),
    # Cloud Platforms
    ("AWS", "Cloud Platform", ["amazon web services"], True),
    ("Microsoft Azure", "Cloud Platform", ["azure"], True),
    ("Google Cloud Platform", "Cloud Platform", ["gcp"], True),
    ("Heroku", "Cloud Platform", [], True),
    ("DigitalOcean", "Cloud Platform", [], True),
    # DevOps / Infra
    ("Docker", "DevOps / Infrastructure Tool", [], True),
    ("Kubernetes", "DevOps / Infrastructure Tool", ["k8s"], True),
    ("Terraform", "DevOps / Infrastructure Tool", [], True),
    ("Ansible", "DevOps / Infrastructure Tool", [], True),
    ("Jenkins", "DevOps / Infrastructure Tool", [], True),
    ("GitHub Actions", "DevOps / Infrastructure Tool", [], True),
    ("GitLab CI/CD", "DevOps / Infrastructure Tool", [], True),
    ("CircleCI", "DevOps / Infrastructure Tool", [], True),
    ("Git", "DevOps / Infrastructure Tool", [], True),
    ("Prometheus", "DevOps / Infrastructure Tool", [], True),
    ("Grafana", "DevOps / Infrastructure Tool", [], True),
    ("Nginx", "DevOps / Infrastructure Tool", [], True),
    ("Apache Kafka", "DevOps / Infrastructure Tool", ["kafka"], True),
    ("RabbitMQ", "DevOps / Infrastructure Tool", [], True),
    # Operating Systems
    ("Linux", "Operating System", [], True),
    ("Windows Server", "Operating System", [], True),
    ("macOS", "Operating System", [], True),
    # AI / ML
    ("Machine Learning", "AI / ML", ["ml"], True),
    ("Deep Learning", "AI / ML", [], True),
    ("Natural Language Processing", "AI / ML", ["nlp"], True),
    ("Computer Vision", "AI / ML", [], True),
    ("Large Language Models", "AI / ML", ["llms"], True),
    ("MLOps", "AI / ML", [], True),
    ("Reinforcement Learning", "AI / ML", [], True),
    ("Explainable AI", "AI / ML", ["xai"], True),
    # Data & Analytics
    ("Data Analysis", "Data & Analytics", [], True),
    ("Data Visualization", "Data & Analytics", [], True),
    ("ETL", "Data & Analytics", [], True),
    ("Statistics", "Data & Analytics", [], True),
    ("A/B Testing", "Data & Analytics", [], True),
    ("Tableau", "Data & Analytics", [], True),
    ("Power BI", "Data & Analytics", [], True),
    ("Looker", "Data & Analytics", [], True),
    ("dbt", "Data & Analytics", [], True),
    ("Apache Spark", "Data & Analytics", ["spark"], True),
    ("Apache Airflow", "Data & Analytics", ["airflow"], True),
    # Design Tools
    ("Figma", "Design Tool", [], True),
    ("Adobe Photoshop", "Design Tool", ["photoshop"], True),
    ("Adobe Illustrator", "Design Tool", ["illustrator"], True),
    ("Sketch", "Design Tool", [], True),
    ("Adobe XD", "Design Tool", [], True),
    # PM Tools
    ("Jira", "Project Management Tool", [], True),
    ("Asana", "Project Management Tool", [], True),
    ("Trello", "Project Management Tool", [], True),
    ("Notion", "Project Management Tool", [], True),
    ("Confluence", "Project Management Tool", [], True),
    # Certifications
    ("AWS Certified Solutions Architect", "Certification", [], True),
    ("PMP", "Certification", ["project management professional"], True),
    ("CPA", "Certification", ["certified public accountant"], True),
    ("CISSP", "Certification", [], True),
    ("Scrum Master (CSM)", "Certification", ["csm"], True),
    ("Google Analytics Certification", "Certification", [], True),
    # Soft Skills
    ("Communication", "Soft Skill", [], False),
    ("Teamwork", "Soft Skill", ["collaboration"], False),
    ("Leadership", "Soft Skill", [], False),
    ("Problem Solving", "Soft Skill", [], False),
    ("Critical Thinking", "Soft Skill", [], False),
    ("Time Management", "Soft Skill", [], False),
    ("Adaptability", "Soft Skill", [], False),
    ("Creativity", "Soft Skill", [], False),
    ("Conflict Resolution", "Soft Skill", [], False),
    ("Emotional Intelligence", "Soft Skill", [], False),
    ("Mentoring", "Soft Skill", ["coaching"], False),
    ("Public Speaking", "Soft Skill", [], False),
    ("Negotiation", "Soft Skill", [], False),
    ("Attention to Detail", "Soft Skill", [], False),
    ("Cross-functional Collaboration", "Soft Skill", [], False),
    # Business Skills
    ("Project Management", "Business Skill", [], False),
    ("Agile", "Business Skill", ["scrum"], False),
    ("Product Strategy", "Business Skill", [], False),
    ("Stakeholder Management", "Business Skill", [], False),
    ("Budgeting", "Business Skill", [], False),
    ("Financial Modeling", "Business Skill", [], False),
    ("Sales Forecasting", "Business Skill", [], False),
    ("CRM Management", "Business Skill", [], False),
    ("SEO", "Business Skill", ["search engine optimization"], False),
    ("Content Strategy", "Business Skill", [], False),
    ("Copywriting", "Business Skill", [], False),
    ("Customer Relationship Management", "Business Skill", ["crm"], False),
    # Other Tools
    ("Salesforce", "Other Tool", [], True),
    ("HubSpot", "Other Tool", [], True),
    ("Zendesk", "Other Tool", [], True),
    ("Shopify", "Other Tool", [], True),
    ("WordPress", "Other Tool", [], True),
    ("Webflow", "Other Tool", [], True),
]


def seed_skills(conn: Connection) -> SeedResult:
    category_ids = {
        r.category_name: r.skill_category_id
        for r in conn.execute(text("SELECT category_name, skill_category_id FROM ref.skill_categories"))
    }
    rows = []
    for name, category, aliases, is_tech in _SKILLS:
        rows.append(
            {
                "skill_name": name,
                "normalized_skill_name": normalize_name(name),
                "skill_category_id": category_ids[category],
                "aliases": aliases or None,
                "is_technology": is_tech,
                "embedding_ref": None,
            }
        )
    return upsert_many(
        conn, schema="ref", table_name="skills",
        rows=rows, conflict_cols=("normalized_skill_name",),
    )