"""Build the uniform master Excel workbook combining all job site lists, probe data,
GitHub scraper registry status, and local database counts.
"""

import csv
import json
import os
import pathlib
import re
import xml.etree.ElementTree as ET
import zipfile

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
import psycopg

# Paths
ROOT_DIR = pathlib.Path(__file__).resolve().parents[3]
JMI_DIR = ROOT_DIR / "DataBase" / "job-market-intel"
OUTPUT_FILE = ROOT_DIR / "job_sites_uniform_master.xlsx"

print(f"Root: {ROOT_DIR}")
print(f"JMI Dir: {JMI_DIR}")
print(f"Output File: {OUTPUT_FILE}")

# 1. Fetch DB metrics
db_counts = {}
try:
    conn = psycopg.connect("postgresql://app_user:changeme@localhost:5432/job_market_intelligence")
    cur = conn.cursor()
    cur.execute("""
        SELECT s.source_code, s.source_name, count(j.job_id) 
        FROM ref.sources s 
        LEFT JOIN core.jobs j ON s.source_id = j.source_id 
        GROUP BY s.source_code, s.source_name;
    """)
    for row in cur.fetchall():
        db_counts[row[0]] = {"name": row[1], "rows": row[2]}
    conn.close()
    print(f"Fetched DB counts for {len(db_counts)} sources.")
except Exception as e:
    print(f"Warning: could not connect to local DB: {e}")

# 2. Fetch GitHub Sources Registry
with open(JMI_DIR / "config" / "sources.json", "r", encoding="utf-8") as f:
    sources_data = json.load(f)

registry_sources = {}
for s in sources_data.get("sources", []):
    code = s["code"]
    registry_sources[code] = s

print(f"Loaded {len(registry_sources)} sources from config/sources.json")

# 3. Read Probe Summary CSV
probes = {}
probe_csv_path = ROOT_DIR / "job_sites_probe_summary.csv"
if probe_csv_path.exists():
    with open(probe_csv_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = row.get("domain", "").strip().lower()
            if d:
                probes[d] = row
    print(f"Loaded {len(probes)} probe entries from CSV.")

# 4. Read Country Scrapeability Excel
country_rows = []
scrape_excel_path = ROOT_DIR / "job_sites_by_country_SCRAPEABILITY.xlsx"
if scrape_excel_path.exists():
    wb_scrape = openpyxl.load_workbook(scrape_excel_path, data_only=True)
    ws_country = wb_scrape["Job Sites by Country"]
    for r in range(2, ws_country.max_row + 1):
        vals = [ws_country.cell(r, c).value for c in range(1, ws_country.max_column + 1)]
        if any(vals):
            country_rows.append(vals)
    print(f"Loaded {len(country_rows)} country rows from SCRAPEABILITY Excel.")

# 5. Read WebsiteToScrape.docx
docx_categories = []
docx_path = ROOT_DIR / "WebsiteToScrape.docx"
if docx_path.exists():
    with zipfile.ZipFile(docx_path) as z:
        xml_content = z.read("word/document.xml")
    tree = ET.fromstring(xml_content)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    body = tree.find(".//w:body", ns)
    current_cat = "Global / General"
    for child in body:
        tag = child.tag.split("}")[-1]
        if tag == "p":
            text = "".join(child.itertext()).strip()
            if text and not text.startswith("#") and len(text) < 60:
                current_cat = text
        elif tag == "tbl":
            rows = child.findall(".//w:tr", ns)
            for row in rows:
                cells = row.findall(".//w:tc", ns)
                c_text = ["".join(c.itertext()).strip() for c in cells]
                if c_text and c_text[0] != "#":
                    docx_categories.append({
                        "category": current_cat,
                        "num": c_text[0] if len(c_text) > 0 else "",
                        "name": c_text[1] if len(c_text) > 1 else "",
                        "focus": c_text[2] if len(c_text) > 2 else ""
                    })
    print(f"Loaded {len(docx_categories)} categorized sites from WebsiteToScrape.docx.")

def extract_domain(text: str) -> str:
    if not text:
        return ""
    m = re.search(r"\(([\w\.\-]+(?:\.[a-z]{2,}))\)", text)
    if m:
        return m.group(1).lower()
    m2 = re.search(r"([\w\.\-]+\.[a-z]{2,})", text)
    if m2:
        return m2.group(1).lower()
    return ""

def clean_site_name(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\s*\(.*?\)", "", text).strip()
    return text

domain_to_code = {
    "remoteok.com": "remoteok",
    "weworkremotely.com": "weworkremotely",
    "remotive.com": "remotive",
    "reed.co.uk": "reed",
    "51job.com": "51job",
    "myjob.mu": "myjob",
    "job.am": "jobam",
    "irantalent.com": "irantalent",
    "jobvision.ir": "jobvision",
    "glints.com": "glints",
    "jobmaster.co.il": "jobmaster",
    "hr.ge": "hrge",
    "emploitic.com": "emploitic",
    "greenhouse.io": "greenhouse",
    "boards.greenhouse.io": "greenhouse",
    "arbeitnow.com": "arbeitnow",
    "himalayas.app": "himalayas",
    "jobicy.com": "jobicy",
    "themuse.com": "themuse",
    "jobbank.gc.ca": "jobbank",
    "usajobs.gov": "usajobs",
    "wellfound.com": "wellfound",
    "builtin.com": "builtin",
    "careers24.com": "careers24",
    "apna.co": "apna",
    "mustakbil.com": "mustakbil",
    "alfred.is": "alfred",
    "careerjunction.co.za": "careerjunction",
    "angolaemprego.com": "angola_emprego",
    "jobinrwanda.com": "jobinrwanda",
    "jobwebghana.com": "jobwebghana",
    "acbar.org": "acbar_jobs",
    "jobs.af": "jobs_af",
    "fijisun.com.fj": "fijisun_jobs",
    "corporatestaffing.co.ke": "corporatestaffing_ke",
    "philjobnet.gov.ph": "philjobnet",
    "karriere.at": "karriere_at",
    "hiiraan.com": "hiiraan_jobs",
    "hiredly.com": "hiredly",
    "my.hiredly.com": "hiredly",
    "jobs.ge": "jobsge",
    "forasna.com": "forasna",
    "jobsireland.ie": "jobsireland",
    "jobmail.co.za": "jobmail",
    "shine.com": "shine",
    "jobinja.ir": "jobinja",
    "indeed.com": "indeed",
    "net-empregos.com": "net_empregos",
    "vagas.com.br": "vagas_com_br",
    "jobsnepal.com": "jobsnepal",
    "jobsearch.az": "jobsearch_az",
    "skill.jobs": "skilljobs",
    "alwatwan.net": "alwatwan",
    "alwihdainfo.com": "alwihdainfo",
    "educarriere.ci": "educarriere",
    "burkina24.com": "burkina24_com",
    "fne.cm": "fne_cm",
    "mwnation.com": "mwnation_com",
    "mifotra.gov.rw": "mifotra_gov_rw",
    "brightermonday.co.tz": "brightermonday_co_tz",
    "prace.cz": "pracecz",
    "agenceemploijeunes.ci": "agenceemploijeunes",
    "ethiojobs.net": "ethiojobs",
    "hellojob.az": "hellojob",
    "hotnigerianjobs.com": "hotnigerianjobs",
    "jobzella.com": "jobzella",
    "minajobs.net": "minajobs",
    "emploipartner.com": "emploipartner_com",
    "iefp.cv": "iefp_cv",
    "jobwebkenya.com": "jobwebkenya_com",
    "ngcareers.com": "ngcareers_com",
    "emploidakar.com": "emploidakar_com",
    "keejob.com": "keejob_com",
    "careercenter.am": "careercenter_am",
    "enbek.kz": "enbek_kz",
    "kumarijob.com": "kumarijob_com",
    "qatarliving.com": "qatarliving_com",
    "wanted.co.kr": "wanted_co_kr",
    "ikman.lk": "ikman_lk",
    "praca.by": "praca_by",
    "mojposao.ba": "mojposao_ba",
    "zaplata.bg": "zaplata_bg",
    "jobtiger.bg": "jobtiger_bg",
    "posao.hr": "posao_hr",
    "jobnet.dk": "jobnet_dk",
    "kosovajob.com": "kosovajob_com",
    "arbeidsplassen.nav.no": "arbeidsplassen_nav_no",
    "jobbnorge.no": "jobbnorge_no",
    "praca.pl": "praca_pl",
    "emprego.sapo.pt": "emprego_sapo_pt",
    "bumeran.com.ar": "bumeran_com_ar",
    "gupy.io": "gupy_io",
    "bne.cl": "bne_cl",
    "magneto365.com": "magneto365_com",
    "empleos.net": "empleos_net",
    "bumeran.com.pe": "bumeran_com_pe",
    "pe.computrabajo.com": "pe_computrabajo_com",
    "cr.computrabajo.com": "cr_computrabajo_com",
    "bo.computrabajo.com": "bo_computrabajo_com",
    "greatzambiajobs.com": "greatzambiajobs_com",
    "rekrute.com": "rekrute_com",
}

for code, s_info in registry_sources.items():
    note = s_info.get("notes", "")
    found_domains = re.findall(r"([\w\.\-]+\.[a-z]{2,})", note)
    for fd in found_domains:
        if fd not in domain_to_code:
            domain_to_code[fd.lower()] = code


SPA_BLOCKERS = {
    "alwatwan": "PERMANENTLY_DEAD (Newspaper portal, /annonces/ 404, no job board)",
    "kuenselonline_com": "PERMANENTLY_DEAD (Classifieds section gone, only CEO coverage PDF remains)",
    "zhipin_com": "CAPTCHA_BLOCKED (Slider/image captcha wall on all endpoints; requires anti-captcha proxy)",
    "naukri_com": "SPA_AKAMAI_BLOCKED (Akamai bot-manager blocks DC/CI IPs; 0 server-side links)",
    "hiredly_com": "DUPLICATE (Domain alias of enabled 'hiredly' source; keep disabled to prevent dups)",
    "iskur_gov_tr": "AUTH_REQUIRED (Angular SPA, job grid is empty anonymously; user login required)",
    "laimoon_com": "PERMANENTLY_DEAD (DNS failure; job board permanently shut down)",
    "tyopaikat_oikotie_fi": "PERMANENTLY_DEAD (Oikotie Työpaikat portal officially closed and redirects to notice)",
    "jobline_hu": "PERMANENTLY_DEAD (Site shut down on 2026-01-31 per official closure notice)",
    "cliclavoro_gov_it": "NO_JOB_CONTENT (Pivoted to institutional news portal; job paths 404)",
    "superjob_ru": "CAPTCHA_BLOCKED (Slider captcha wall on all endpoints)",
    "jamaicaobserver_com": "NO_JOB_CONTENT (Anygraaf API returns empty items; classifieds have 0 jobs)",
    "empleo_gob_mx": "AUTH_REQUIRED (Angular SPA; JS bundle returns 403, /api/* returns 401 without session)",
    "trinidadexpress_com": "ROBOTS_BLOCKED+429 (robots.txt disallows /classifieds/job/*; returns HTTP 429)",
    "workforceaustralia_gov_au": "ROBOTS_BLOCKED (robots.txt: User-agent: * Disallow: / blanket ban)",
    "samoaobserver_ws": "NO_JOB_CONTENT (Newspaper only; no jobs or classifieds board exists)",
}

SPA_ACTION_PLANS = {
    "alwatwan": "Permanently decommission scraper (newspaper site without job board)",
    "kuenselonline_com": "Permanently decommission scraper (classifieds section removed)",
    "zhipin_com": "Requires residential IP proxy + paid captcha solving service (out of CI scope)",
    "naukri_com": "Requires residential IP proxy to bypass Akamai bot manager (out of CI scope)",
    "hiredly_com": "Keep disabled — 'hiredly' (my.hiredly.com) is the active operational scraper",
    "iskur_gov_tr": "Requires government auth credentials / session tokens not available for public scraping",
    "laimoon_com": "Permanently decommission scraper (DNS domain defunct)",
    "tyopaikat_oikotie_fi": "Permanently decommission scraper (service officially discontinued)",
    "jobline_hu": "Permanently decommission scraper (service permanently terminated 2026-01-31)",
    "cliclavoro_gov_it": "Permanently decommission scraper (government moved job postings to SIISL)",
    "superjob_ru": "Requires residential proxy and Russian captcha solver (out of CI scope)",
    "jamaicaobserver_com": "Permanently decommission scraper (classifieds no longer lists employment)",
    "empleo_gob_mx": "Requires Mexican government portal citizen authentication",
    "trinidadexpress_com": "Comply with site robots.txt policy and avoid IP blacklisting",
    "workforceaustralia_gov_au": "Comply with government robots.txt Disallow: / directive",
    "samoaobserver_ws": "Permanently decommission scraper (news portal without employment section)",
}

disabled_reasons = {}
analysis_md_path = ROOT_DIR / "DataBase" / "comprehensive_disabled_analysis.md"
if analysis_md_path.exists():
    text = analysis_md_path.read_text(encoding="utf-8")
    curr_cat = ""
    for line in text.splitlines():
        if line.startswith("### Category"):
            curr_cat = line.split("—")[0].strip().replace("### ", "")
        elif line.startswith("**Scrapers**:") and curr_cat:
            scrapers_list = [sc.strip() for sc in line.replace("**Scrapers**:", "").split(",")]
            for sc in scrapers_list:
                disabled_reasons[sc] = curr_cat

all_master_entries = {}

def get_or_create_master_entry(domain, fallback_name="", region="", country="", category=""):
    key = domain.lower() if domain else fallback_name.lower()
    if not key:
        return None
    if key not in all_master_entries:
        all_master_entries[key] = {
            "key": key,
            "domain": domain,
            "name": fallback_name,
            "region": region,
            "country": country,
            "category": category,
            "http_status": "",
            "probe_title": "",
            "scrape_method": "",
            "probe_detail": "",
            "github_code": "",
            "github_status": "NOT BUILT (Backlog)",
            "github_group": "",
            "db_rows": 0,
            "blocker_reason": "",
            "action_plan": "",
        }
    entry = all_master_entries[key]
    if not entry["name"] and fallback_name:
        entry["name"] = fallback_name
    if not entry["region"] and region:
        entry["region"] = region
    if not entry["country"] and country:
        entry["country"] = country
    if not entry["category"] and category:
        entry["category"] = category
    return entry

# A) Ingest Country list
for r in country_rows:
    reg = r[1]
    cntry = r[2]
    for idx, col_idx in enumerate([3, 4, 5], start=1):
        site_raw = r[col_idx]
        if not site_raw or site_raw.strip() in ("—", "-", ""):
            continue
        domain = extract_domain(site_raw)
        name = clean_site_name(site_raw)
        entry = get_or_create_master_entry(domain, fallback_name=name, region=reg, country=cntry, category="Country Portal")
        scr_idx = 7 + idx
        if scr_idx < len(r) and r[scr_idx]:
            scr_val = str(r[scr_idx])
            entry["probe_detail"] = scr_val[:250]

# B) Ingest 200 docx sites
for s in docx_categories:
    name = s["name"]
    cat = s["category"]
    focus = s["focus"]
    domain = extract_domain(name)
    clean_n = clean_site_name(name)
    reg = ""
    cntry = focus
    if "United States" in cat or focus == "US":
        reg = "Americas"
        cntry = "United States"
    elif "Canada" in cat:
        reg = "Americas"
        cntry = "Canada"
    elif "United Kingdom" in cat or focus == "UK":
        reg = "Europe"
        cntry = "United Kingdom"
    elif "Continental Europe" in cat or "Nordic" in cat or "Eastern" in cat:
        reg = "Europe"
    elif "India" in cat:
        reg = "Asia"
        cntry = "India"
    elif "Middle East" in cat or "Africa" in cat:
        reg = "Middle East / Africa"
    elif "Asia-Pacific" in cat:
        reg = "Asia-Pacific"
    
    get_or_create_master_entry(domain, fallback_name=clean_n, region=reg, country=cntry, category=cat)

# C) Ingest Probes
for d, p in probes.items():
    entry = get_or_create_master_entry(d, fallback_name=d)
    entry["http_status"] = p.get("http", "")
    entry["probe_title"] = p.get("title", "")
    entry["scrape_method"] = p.get("method", "")
    if not entry["probe_detail"] and p.get("detail"):
        entry["probe_detail"] = p.get("detail", "")

# D) Cross-reference GitHub sources.json & DB
for key, entry in all_master_entries.items():
    d = entry["domain"]
    code = domain_to_code.get(d)
    
    if not code:
        for c, s in registry_sources.items():
            if c.lower() == entry["name"].lower() or c.lower().replace("_", "") == entry["name"].lower().replace(" ", ""):
                code = c
                break

    if code and code in registry_sources:
        s_info = registry_sources[code]
        entry["github_code"] = code
        entry["github_group"] = s_info.get("group", "")
        is_enabled = s_info.get("enabled", False)
        
        db_stat = db_counts.get(code, {"rows": 0})
        entry["db_rows"] = db_stat["rows"]
        
        if is_enabled:
            entry["github_status"] = "DONE (Active in CI)"
        else:
            entry["github_status"] = "BUILT (Disabled in CI)"
            if code in SPA_BLOCKERS:
                entry["blocker_reason"] = SPA_BLOCKERS[code]
                entry["action_plan"] = SPA_ACTION_PLANS[code]
            else:
                cat_reason = disabled_reasons.get(code, "")
                notes = s_info.get("notes", "")
                entry["blocker_reason"] = cat_reason if cat_reason else (notes[:120] if notes else "Disabled in registry")
                
                if "CSS" in cat_reason or "0 Postings" in cat_reason:
                    entry["action_plan"] = "Update CSS selectors in HTML site config and test with --no-db"
                elif "Client-Rendered" in cat_reason:
                    entry["action_plan"] = "Check API XHR endpoint or switch to Playwright browser: true"
                elif "403" in cat_reason:
                    entry["action_plan"] = "Inspect WAF / user-agent / proxy requirements"
                elif "Cloudflare" in cat_reason:
                    entry["action_plan"] = "Residential IP proxy or undetected Chrome"
                elif "Browser" in cat_reason or code == "indeed":
                    entry["action_plan"] = "Dedicated runner or seleniumbase UC mode"
                else:
                    entry["action_plan"] = "Investigate error logs and verify site response"
    elif code and code in db_counts:
        entry["github_code"] = code
        entry["db_rows"] = db_counts[code]["rows"]
        entry["github_status"] = "LEGACY / IN DATABASE"
    else:
        if not entry["scrape_method"]:
            if "API" in entry["probe_detail"]:
                entry["scrape_method"] = "FREE API"
            elif "SELENIUM" in entry["probe_detail"] or "PLAYWRIGHT" in entry["probe_detail"]:
                entry["scrape_method"] = "SELENIUM / PLAYWRIGHT"
            elif "HTML" in entry["probe_detail"]:
                entry["scrape_method"] = "HTML scraper"

# Also ensure all 154 sources from sources.json are represented
for code, s_info in registry_sources.items():
    already_in = False
    for k, e in all_master_entries.items():
        if e.get("github_code") == code:
            already_in = True
            break
    if not already_in:
        entry = get_or_create_master_entry(f"{code}.builtin", fallback_name=code, category="System Built-in")
        entry["github_code"] = code
        entry["github_group"] = s_info.get("group", "")
        entry["github_status"] = "DONE (Active in CI)" if s_info.get("enabled") else "BUILT (Disabled in CI)"
        entry["db_rows"] = db_counts.get(code, {"rows": 0})["rows"]
        if code in SPA_BLOCKERS:
            entry["blocker_reason"] = SPA_BLOCKERS[code]
            entry["action_plan"] = SPA_ACTION_PLANS.get(code, "")
        else:
            entry["blocker_reason"] = disabled_reasons.get(code, s_info.get("notes", "")[:120])

print(f"Total unified master entries: {len(all_master_entries)}")

# Build Excel workbook
wb = openpyxl.Workbook()
wb.remove(wb.active)

# Styles
font_title = Font(name="Calibri", size=15, bold=True, color="1F4E79")
font_subtitle = Font(name="Calibri", size=11, italic=True, color="595959")
font_header = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
font_data = Font(name="Calibri", size=10)
font_bold = Font(name="Calibri", size=10, bold=True)

fill_header = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
fill_sub_header = PatternFill(start_color="2F5597", end_color="2F5597", fill_type="solid")
fill_zebra = PatternFill(start_color="F2F5F9", end_color="F2F5F9", fill_type="solid")

fill_active = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
font_active = Font(name="Calibri", size=10, bold=True, color="375623")

fill_disabled = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
font_disabled = Font(name="Calibri", size=10, bold=True, color="7F6000")

fill_backlog = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
font_backlog = Font(name="Calibri", size=10, color="595959")

thin_border = Border(
    left=Side(style="thin", color="D9D9D9"),
    right=Side(style="thin", color="D9D9D9"),
    top=Side(style="thin", color="D9D9D9"),
    bottom=Side(style="thin", color="D9D9D9")
)

# Sheet 1: Master Directory
ws1 = wb.create_sheet(title="Master Directory")
ws1.views.sheetView[0].showGridLines = True

ws1.cell(row=1, column=1, value="Job Market Intelligence Platform — Unified Scraper Master Directory").font = font_title
ws1.cell(row=2, column=1, value="Comprehensive registry of all global, remote, tech, and country-level job boards with GitHub scraper & database status").font = font_subtitle

headers_ws1 = [
    "ID", "Site / Portal Name", "Domain", "Primary Region", "Country / Scope",
    "Segment / Category", "GitHub Status", "GitHub Code", "Workflow Group",
    "DB Rows Collected", "Scrape Method", "HTTP Probe", "Blocker / Reason (If Disabled)", "Action Plan / Fix Strategy"
]

row_idx = 4
for c_idx, h in enumerate(headers_ws1, 1):
    cell = ws1.cell(row=row_idx, column=c_idx, value=h)
    cell.font = font_header
    cell.fill = fill_header
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

status_order = {
    "DONE (Active in CI)": 1,
    "BUILT (Disabled in CI)": 2,
    "LEGACY / IN DATABASE": 3,
    "NOT BUILT (Backlog)": 4,
}

sorted_entries = sorted(
    all_master_entries.values(),
    key=lambda x: (status_order.get(x["github_status"], 5), -x["db_rows"], str(x["name"]).lower())
)

for entry_idx, e in enumerate(sorted_entries, 1):
    row_idx += 1
    st = e["github_status"]
    
    ws1.cell(row=row_idx, column=1, value=entry_idx).alignment = Alignment(horizontal="center")
    ws1.cell(row=row_idx, column=2, value=e["name"])
    ws1.cell(row=row_idx, column=3, value=e["domain"])
    ws1.cell(row=row_idx, column=4, value=e["region"])
    ws1.cell(row=row_idx, column=5, value=e["country"])
    ws1.cell(row=row_idx, column=6, value=e["category"])
    
    st_cell = ws1.cell(row=row_idx, column=7, value=st)
    if "Active" in st:
        st_cell.fill = fill_active
        st_cell.font = font_active
    elif "Disabled" in st:
        st_cell.fill = fill_disabled
        st_cell.font = font_disabled
    else:
        st_cell.fill = fill_backlog
        st_cell.font = font_backlog
    st_cell.alignment = Alignment(horizontal="center")

    ws1.cell(row=row_idx, column=8, value=e["github_code"]).alignment = Alignment(horizontal="center")
    ws1.cell(row=row_idx, column=9, value=e["github_group"]).alignment = Alignment(horizontal="center")
    
    db_cell = ws1.cell(row=row_idx, column=10, value=e["db_rows"])
    db_cell.number_format = "#,##0"
    db_cell.alignment = Alignment(horizontal="right")
    
    ws1.cell(row=row_idx, column=11, value=e["scrape_method"])
    ws1.cell(row=row_idx, column=12, value=e["http_status"]).alignment = Alignment(horizontal="center")
    ws1.cell(row=row_idx, column=13, value=e["blocker_reason"])
    ws1.cell(row=row_idx, column=14, value=e["action_plan"])

    is_even = (entry_idx % 2 == 0)
    for c in range(1, len(headers_ws1) + 1):
        c_node = ws1.cell(row=row_idx, column=c)
        c_node.border = thin_border
        if c != 7:
            c_node.font = font_data
            if is_even:
                c_node.fill = fill_zebra

ws1.freeze_panes = "A5"
col_widths_ws1 = [6, 26, 24, 16, 20, 22, 22, 16, 15, 16, 24, 12, 36, 38]
for c_idx, w in enumerate(col_widths_ws1, 1):
    ws1.column_dimensions[get_column_letter(c_idx)].width = w

# Sheet 2: Country Coverage (197 Countries)
ws2 = wb.create_sheet(title="Country Coverage (197)")
ws2.views.sheetView[0].showGridLines = True

ws2.cell(row=1, column=1, value="Global Coverage: 197 Countries × 3 Local Portals").font = font_title
ws2.cell(row=2, column=1, value="Full audit of national job portals, verification confidence, scrapeability method, and implementation status").font = font_subtitle

headers_ws2 = [
    "#", "Region", "Country / Territory", "Confidence", "Notes",
    "Site #1 Name / Domain", "Site #1 Status", "Site #1 Method & Probe Evidence",
    "Site #2 Name / Domain", "Site #2 Status", "Site #2 Method & Probe Evidence",
    "Site #3 Name / Domain", "Site #3 Status", "Site #3 Method & Probe Evidence"
]

row_idx = 4
for c_idx, h in enumerate(headers_ws2, 1):
    cell = ws2.cell(row=row_idx, column=c_idx, value=h)
    cell.font = font_header
    cell.fill = fill_sub_header
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

for r in country_rows:
    row_idx += 1
    cntry_num = r[0]
    reg = r[1]
    cntry = r[2]
    conf = r[6]
    notes = r[7] if len(r) > 7 else ""
    
    ws2.cell(row=row_idx, column=1, value=cntry_num).alignment = Alignment(horizontal="center")
    ws2.cell(row=row_idx, column=2, value=reg)
    ws2.cell(row=row_idx, column=3, value=cntry).font = font_bold
    ws2.cell(row=row_idx, column=4, value=conf)
    ws2.cell(row=row_idx, column=5, value=notes)

    col_out = 6
    for idx, s_idx in enumerate([3, 4, 5], 1):
        site_str = r[s_idx] if len(r) > s_idx else ""
        scr_str = r[7 + idx] if len(r) > 7 + idx else ""
        domain = extract_domain(site_str)
        
        stat = "No URL"
        if domain:
            code = domain_to_code.get(domain)
            if code and code in registry_sources:
                stat = "ACTIVE" if registry_sources[code].get("enabled") else "BUILT (Disabled)"
            else:
                stat = "BACKLOG"
        elif site_str and site_str != "—":
            stat = "UNVERIFIED"

        ws2.cell(row=row_idx, column=col_out, value=site_str)
        st_cell = ws2.cell(row=row_idx, column=col_out + 1, value=stat)
        if stat == "ACTIVE":
            st_cell.fill = fill_active
            st_cell.font = font_active
        elif "Disabled" in stat:
            st_cell.fill = fill_disabled
            st_cell.font = font_disabled
        st_cell.alignment = Alignment(horizontal="center")

        ws2.cell(row=row_idx, column=col_out + 2, value=scr_str)
        col_out += 3

    for c in range(1, len(headers_ws2) + 1):
        ws2.cell(row=row_idx, column=c).border = thin_border
        ws2.cell(row=row_idx, column=c).font = font_data
        if str(cntry_num).isdigit() and int(cntry_num) % 2 == 0:
            if c not in (7, 10, 13):
                ws2.cell(row=row_idx, column=c).fill = fill_zebra

ws2.freeze_panes = "D5"
col_widths_ws2 = [6, 14, 22, 14, 20, 26, 16, 40, 26, 16, 40, 26, 16, 40]
for c_idx, w in enumerate(col_widths_ws2, 1):
    ws2.column_dimensions[get_column_letter(c_idx)].width = w

# Sheet 3: Specialized & Global Boards (200)
ws3 = wb.create_sheet(title="Thematic Boards (200)")
ws3.views.sheetView[0].showGridLines = True

ws3.cell(row=1, column=1, value="200 Thematic, Regional & Specialized Job Portals").font = font_title
ws3.cell(row=2, column=1, value="Categorized listing of major general, remote, startup, technology, and regional niche boards").font = font_subtitle

headers_ws3 = [
    "#", "Category / Sector", "Job Site Name", "Focus / Niche", "Matched Domain",
    "GitHub Status", "GitHub Code", "DB Rows", "Scrape Technique"
]

row_idx = 4
for c_idx, h in enumerate(headers_ws3, 1):
    cell = ws3.cell(row=row_idx, column=c_idx, value=h)
    cell.font = font_header
    cell.fill = fill_sub_header
    cell.alignment = Alignment(horizontal="center", vertical="center")

for idx, item in enumerate(docx_categories, 1):
    row_idx += 1
    num = item["num"]
    cat = item["category"]
    name = item["name"]
    focus = item["focus"]
    domain = extract_domain(name)
    if not domain:
        cn = clean_site_name(name).lower()
        for d in domain_to_code:
            if cn in d:
                domain = d
                break
    
    stat = "BACKLOG"
    code = ""
    rows = 0
    method = ""
    if domain:
        code = domain_to_code.get(domain, "")
        if code and code in registry_sources:
            stat = "ACTIVE" if registry_sources[code].get("enabled") else "BUILT (Disabled)"
            rows = db_counts.get(code, {"rows": 0})["rows"]
        if domain in probes:
            method = probes[domain].get("method", "")

    ws3.cell(row=row_idx, column=1, value=int(num) if num.isdigit() else idx).alignment = Alignment(horizontal="center")
    ws3.cell(row=row_idx, column=2, value=cat)
    ws3.cell(row=row_idx, column=3, value=name).font = font_bold
    ws3.cell(row=row_idx, column=4, value=focus)
    ws3.cell(row=row_idx, column=5, value=domain)
    
    st_cell = ws3.cell(row=row_idx, column=6, value=stat)
    if stat == "ACTIVE":
        st_cell.fill = fill_active
        st_cell.font = font_active
    elif "Disabled" in stat:
        st_cell.fill = fill_disabled
        st_cell.font = font_disabled
    st_cell.alignment = Alignment(horizontal="center")

    ws3.cell(row=row_idx, column=7, value=code).alignment = Alignment(horizontal="center")
    ws3.cell(row=row_idx, column=8, value=rows).number_format = "#,##0"
    ws3.cell(row=row_idx, column=9, value=method)

    for c in range(1, len(headers_ws3) + 1):
        ws3.cell(row=row_idx, column=c).border = thin_border
        if c != 6:
            ws3.cell(row=row_idx, column=c).font = font_data
            if idx % 2 == 0:
                ws3.cell(row=row_idx, column=c).fill = fill_zebra

ws3.freeze_panes = "C5"
col_widths_ws3 = [6, 26, 28, 24, 24, 18, 16, 14, 30]
for c_idx, w in enumerate(col_widths_ws3, 1):
    ws3.column_dimensions[get_column_letter(c_idx)].width = w

# Sheet 4: Executive Summary Dashboard
ws4 = wb.create_sheet(title="Executive Summary")
ws4.views.sheetView[0].showGridLines = True

ws4.cell(row=1, column=1, value="Job Market Intelligence Platform — Pipeline Overview").font = font_title
ws4.cell(row=2, column=1, value="Executive status summary, scraper deployment statistics, and database volume metrics").font = font_subtitle

total_master = len(all_master_entries)
active_scrapers = sum(1 for e in all_master_entries.values() if "Active" in e["github_status"])
disabled_scrapers = sum(1 for e in all_master_entries.values() if "Disabled" in e["github_status"])
backlog_sites = sum(1 for e in all_master_entries.values() if "Backlog" in e["github_status"])
total_jobs = sum(e["db_rows"] for e in all_master_entries.values())

api_count = sum(1 for e in all_master_entries.values() if e["github_group"] == "api")
html_count = sum(1 for e in all_master_entries.values() if e["github_group"] == "html")
browser_count = sum(1 for e in all_master_entries.values() if e["github_group"] == "browser")

kpis = [
    ("Total Verified Sites Tracked", total_master, "Distinct job portals across all countries and niches"),
    ("Active Scrapers in CI", active_scrapers, "Regularly executing on scheduled GitHub Actions crons"),
    ("Built Scrapers Awaiting Fix", disabled_scrapers, "Implemented code present; requires CSS, browser, or proxy update"),
    ("Sites in Engineering Backlog", backlog_sites, "Candidate portals ready for implementation"),
    ("Total Job Postings in DB", f"{total_jobs:,}", "Normalized, deduplicated postings in local PostgreSQL warehouse")
]

row_idx = 4
for idx, (title, val, sub) in enumerate(kpis, 1):
    ws4.cell(row=row_idx, column=2, value=title).font = font_bold
    val_cell = ws4.cell(row=row_idx, column=3, value=val)
    val_cell.font = Font(name="Calibri", size=13, bold=True, color="1F4E79")
    val_cell.alignment = Alignment(horizontal="right")
    ws4.cell(row=row_idx, column=4, value=sub).font = font_subtitle
    ws4.cell(row=row_idx, column=2).fill = fill_zebra
    ws4.cell(row=row_idx, column=3).fill = fill_zebra
    row_idx += 1

row_idx += 2
ws4.cell(row=row_idx, column=2, value="GitHub Actions Workflow Groups").font = font_bold
row_idx += 1
for grp_name, cnt in [("API Scrapers (JSON / RSS endpoints)", api_count), ("HTML Scrapers (Server-rendered HTML / JSON-LD)", html_count), ("Browser Scrapers (Headless Chrome / Playwright)", browser_count)]:
    ws4.cell(row=row_idx, column=2, value=grp_name).font = font_data
    c_val = ws4.cell(row=row_idx, column=3, value=cnt)
    c_val.font = font_bold
    c_val.alignment = Alignment(horizontal="right")
    row_idx += 1

row_idx += 2
ws4.cell(row=row_idx, column=2, value="Top 15 Data Sources by Collected Rows").font = font_bold
row_idx += 1
ws4.cell(row=row_idx, column=2, value="Source Code").font = font_header
ws4.cell(row=row_idx, column=2).fill = fill_header
ws4.cell(row=row_idx, column=3, value="Postings in DB").font = font_header
ws4.cell(row=row_idx, column=3).fill = fill_header
ws4.cell(row=row_idx, column=4, value="Status").font = font_header
ws4.cell(row=row_idx, column=4).fill = fill_header

top_sources = sorted([e for e in all_master_entries.values() if e["db_rows"] > 0], key=lambda x: -x["db_rows"])[:15]
for s in top_sources:
    row_idx += 1
    ws4.cell(row=row_idx, column=2, value=s["name"] or s["github_code"]).font = font_data
    cnt_cell = ws4.cell(row=row_idx, column=3, value=s["db_rows"])
    cnt_cell.number_format = "#,##0"
    cnt_cell.font = font_bold
    cnt_cell.alignment = Alignment(horizontal="right")
    st_cell = ws4.cell(row=row_idx, column=4, value=s["github_status"])
    if "Active" in s["github_status"]:
        st_cell.fill = fill_active
        st_cell.font = font_active
    else:
        st_cell.fill = fill_disabled
        st_cell.font = font_disabled

ws4.column_dimensions["B"].width = 38
ws4.column_dimensions["C"].width = 20
ws4.column_dimensions["D"].width = 50

# Save Workbook
wb.save(OUTPUT_FILE)
print(f"Successfully generated uniform master Excel at: {OUTPUT_FILE}")
