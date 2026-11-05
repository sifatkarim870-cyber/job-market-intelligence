from job_market_intel.cleaning.qualification_mappers import (
    map_education_level,
    map_experience_level,
    map_job_category,
    map_remote_work_type,
    extract_education_field_raw,
    map_education_discipline,
    extract_experience_years,
    extract_seniority_and_management,
    extract_work_schedule,
    extract_normalized_benefits,
    extract_normalized_skills,
)


def test_map_education_level() -> None:
    assert map_education_level(None) is None
    assert map_education_level("") is None
    assert map_education_level("Requires a Master's degree in Computer Science") == "master"
    assert map_education_level("Bac + 5 école d'ingénieur") == "master"
    assert map_education_level("Bachelor of Science in Engineering or equivalent") == "bachelor"
    assert map_education_level("Licence ou équivalent") == "bachelor"
    assert map_education_level("Ph.D. in Physics required") == "phd"
    assert map_education_level("High school diploma or GED required") == "high_school"
    assert map_education_level("No degree required") == "none"
    assert map_education_level("PMP certification preferred") == "professional_certification"


def test_map_experience_level() -> None:
    assert map_experience_level(None) is None
    assert map_experience_level("", title="Senior Software Engineer") == "senior"
    assert map_experience_level("", title="Junior Web Developer") == "junior"
    assert map_experience_level("", title="Engineering Lead") == "lead"
    assert map_experience_level("", title="VP of Technology") == "executive"
    assert map_experience_level("", title="Principal Architect") == "principal"
    assert map_experience_level("", title="Intern Software Development") == "entry"
    assert map_experience_level("Minimum 5 years of experience in Python", title="Backend Developer") == "senior"
    assert map_experience_level("3-5 years of experience required", title="Developer") == "mid"
    assert map_experience_level("At least 1 year of experience", title="Analyst") == "junior"


def test_map_remote_work_type() -> None:
    assert map_remote_work_type(None) is None
    assert map_remote_work_type("Remote (Worldwide)") == "remote_global"
    assert map_remote_work_type("Remote / Work from home") == "remote_country"
    assert map_remote_work_type("Hybrid (2 days remote)") == "hybrid"
    assert map_remote_work_type("On-site in Madrid") == "on_site"


def test_map_job_category() -> None:
    assert map_job_category(None) is None
    assert map_job_category("Senior Python Developer") == "swe_backend"
    assert map_job_category("Frontend React Developer") == "swe_frontend"
    assert map_job_category("Full Stack Software Engineer") == "swe_fullstack"
    assert map_job_category("Lead Data Scientist") == "data_ai"
    assert map_job_category("UI/UX Designer") == "design"
    assert map_job_category("Senior Product Manager") == "product"
    assert map_job_category("Account Executive - Sales") == "sales"
    assert map_job_category("Marketing Specialist") == "marketing"
    assert map_job_category("Customer Support Agent") == "customer_support"
    assert map_job_category("Senior Accountant") == "finance"
    assert map_job_category("Technical Recruiter") == "hr_people"


def test_extract_education_field_raw() -> None:
    assert extract_education_field_raw(None) is None
    assert extract_education_field_raw("") is None
    assert extract_education_field_raw("Bachelor's degree in Computer Science or related field") == "Computer Science"
    assert extract_education_field_raw("Degree in Business Administration, Finance or Accounting is required") == "Business Administration, Finance or Accounting"
    assert extract_education_field_raw("Degree in Nursing required") == "Nursing"


def test_map_education_discipline() -> None:
    assert map_education_discipline(None) is None
    assert map_education_discipline("") is None
    assert "computer_science" in (map_education_discipline("Computer Science, Software Engineering") or "")
    assert "data_science_statistics" in (map_education_discipline("Data Science, Statistics") or "")
    assert "finance_accounting" in (map_education_discipline("Finance and Accounting") or "")
    assert "healthcare_nursing" in (map_education_discipline("Nursing and Medicine") or "")


def test_extract_experience_years() -> None:
    assert extract_experience_years(None) == (None, None)
    assert extract_experience_years("") == (None, None)
    assert extract_experience_years("Requires 3-5 years of experience") == (3, 5)
    assert extract_experience_years("Minimum 5 years of experience in Python") == (5, None)
    assert extract_experience_years("7+ years of relevant experience") == (7, None)
    assert extract_experience_years("No experience required") == (None, None)


def test_extract_seniority_and_management() -> None:
    assert extract_seniority_and_management(None) == (None, None)
    assert extract_seniority_and_management("") == (None, None)
    assert extract_seniority_and_management("Chief Executive Officer") == ("executive", True)
    assert extract_seniority_and_management("VP of Engineering") == ("executive", True)
    assert extract_seniority_and_management("Director of Data Science") == ("director", True)
    assert extract_seniority_and_management("Engineering Manager") == ("manager", True)
    assert extract_seniority_and_management("Senior Backend Engineer") == ("individual_contributor", False)
    assert extract_seniority_and_management("Junior Developer") == ("individual_contributor", False)
    assert extract_seniority_and_management("Intern") == ("individual_contributor", False)


def test_extract_work_schedule() -> None:
    assert extract_work_schedule(None) is None
    assert extract_work_schedule("Flexible working hours with remote options") == "flexible"
    assert extract_work_schedule("Must be available for night shift") == "night_shift"
    assert extract_work_schedule("Standard Monday to Friday 9 to 5") == "standard_day"
    assert extract_work_schedule("Weekend shift work required") == "weekend"


def test_extract_normalized_benefits() -> None:
    assert extract_normalized_benefits(None) is None
    text = "We offer comprehensive health insurance, dental coverage, 401(k) matching, and generous paid time off."
    b = extract_normalized_benefits(text) or ""
    assert "health_insurance" in b
    assert "dental_vision" in b
    assert "retirement_401k" in b
    assert "paid_time_off" in b


def test_extract_normalized_skills() -> None:
    assert extract_normalized_skills(None) is None
    text = "Requirements: Strong experience with Python, PostgreSQL, Docker, AWS, and React."
    s = extract_normalized_skills(text) or ""
    assert "python" in s
    assert "postgresql" in s
    assert "docker" in s
    assert "aws" in s
    assert "react" in s


def test_map_education_level_multilingual() -> None:
    # Persian
    assert map_education_level("مدرک کارشناسی ارشد مهندسی") == "master"
    assert map_education_level("مدرک کارشناسی نرم افزار") == "bachelor"
    assert map_education_level("مدرک دکتری فیزیک") == "phd"
    assert map_education_level("دیپلم دبیرستان") == "high_school"
    # German
    assert map_education_level("Abitur oder Fachhochschulreife") in ("high_school", "associate")
    assert map_education_level("Abgeschlossenes Master-Studium") == "master"
    assert map_education_level("Doktortitel erwünscht") == "phd"
    # Spanish
    assert map_education_level("Licenciatura en Informática") == "bachelor"
    assert map_education_level("Maestría en Administración de Empresas") == "master"
    # Indonesian
    assert map_education_level("Pendidikan minimal S1 Teknik Informatika") == "bachelor"
    assert map_education_level("Pendidikan S2 Bisnis") == "master"


def test_extract_experience_years_multilingual() -> None:
    # Persian
    assert extract_experience_years("۳ تا ۵ سال سابقه کار") == (3, 5)
    assert extract_experience_years("حداقل 3 سال سابقه مرتبط") == (3, None)
    # Spanish
    assert extract_experience_years("3 a 5 años de experiencia requerida") == (3, 5)
    assert extract_experience_years("Mínimo 5 años de experiencia") == (5, None)
    # German
    assert extract_experience_years("3 bis 5 Jahre Berufserfahrung") == (3, 5)
    assert extract_experience_years("Mindestens 4 Jahre Berufserfahrung") == (4, None)
    # French
    assert extract_experience_years("3 à 5 ans d'expérience") == (3, 5)


def test_extract_seniority_and_management_multilingual() -> None:
    # Persian
    assert extract_seniority_and_management("مدیر عامل شرکت") == ("executive", True)
    assert extract_seniority_and_management("مدیر ارشد فنی") == ("executive", True)
    assert extract_seniority_and_management("سرپرست تیم توسعه") == ("team_lead", None)
    assert extract_seniority_and_management("کارشناس نرم افزار") == ("individual_contributor", False)
    # Spanish
    assert extract_seniority_and_management("Director General") == ("executive", True)
    assert extract_seniority_and_management("Gerente de Operaciones") == ("manager", True)
    assert extract_seniority_and_management("Desarrollador Backend") == ("individual_contributor", False)
    # German
    assert extract_seniority_and_management("Geschäftsführer") == ("executive", True)
    assert extract_seniority_and_management("Teamleiter Softwareentwicklung") == ("team_lead", None)
    assert extract_seniority_and_management("Softwareentwickler") == ("individual_contributor", False)


def test_extract_normalized_benefits_multilingual() -> None:
    # Persian
    p_b = extract_normalized_benefits("مزایا: بیمه تامین اجتماعی، بیمه تکمیلی، ناهار و مرخصی سالانه") or ""
    assert "health_insurance" in p_b
    assert "paid_time_off" in p_b
    assert "wellness_perks" in p_b
    # Spanish
    es_b = extract_normalized_benefits("Ofrecemos seguro médico privado y 25 días de vacaciones pagadas") or ""
    assert "health_insurance" in es_b
    assert "paid_time_off" in es_b
    # German
    de_b = extract_normalized_benefits("Betriebliche Altersvorsorge und 30 Urlaubstage") or ""
    assert "retirement_401k" in de_b
    assert "paid_time_off" in de_b


def test_map_education_discipline_multilingual() -> None:
    # Persian
    d_fa = map_education_discipline("مهندسی کامپیوتر و فناوری اطلاعات") or ""
    assert "computer_science" in d_fa
    assert "information_technology" in d_fa
    # German
    d_de = map_education_discipline("Informatik oder Maschinenbau") or ""
    assert "computer_science" in d_de
    assert "engineering_mechanical" in d_de
