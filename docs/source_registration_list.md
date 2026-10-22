# Sources that need a registration, an API key, or a proxy

Generated 2026-10-16 from `WebsiteToScrape.docx` joined against
`job_sites_by_country_SCRAPEABILITY_backup_20261007.xlsx` and a live re-probe.
Sections B, C and D rewritten **2026-10-18** from direct measurement.

Every URL below was **requested during this triage** and its HTTP status is
recorded, because reciting an API endpoint from memory is how people end up
signing up for one that has moved. Where a URL failed to resolve today, that is
said rather than quietly dropped.

Nothing in sections A-E has been built. Nothing here needs the scraper to exist
first -- each entry is blocked purely on a credential, a network capability, or
the fact that the page is not what it claims to be.

**The three verdicts are different and are kept apart deliberately:**

- **A / B** -- blocked. Needs an account (A) or a residential IP (B).
- **C** -- buildable. Needs engineering time, not money.
- **D** -- rejected. Not a posting list at all, so no amount of the above helps.

---

## A. Blocked on a registration or an API key

### 1. France Travail (France)

The largest French public employment service. There is an **official public
API**, and it is gated behind an account.

| What | URL | Status on 2026-10-16 |
|---|---|---|
| API portal | https://api.francetravail.fr/ | HTTP 403 (exists, refuses anonymous) |
| API documentation | https://francetravail.io/partenaires/api | HTTP 200 |
| Main site | https://www.francetravail.fr | HTTP 200, redirects to `/accueil/` |

**What you would need to do:** register at the API portal, then obtain client
credentials. France Travail issues OAuth2 client credentials
(`client_id` / `client_secret`) per application.

**Why it is worth it:** France had **zero** postings in the corpus, and this is
the authoritative source for them. `/offres-recherche` returns HTTP 404, so the
public site path is not a fallback.

---

### 2. MyCareersFuture (United Kingdom)

The UK government skills and employment service.

| What | URL | Status on 2026-10-16 |
|---|---|---|
| Main site | https://www.mycareersfuture.service.gov.uk/ | ConnectionError (unreachable from this network) |
| Publisher / API | https://www.mycareersfuture.service.gov.uk/publisher/api | ConnectionError (unreachable from this network) |

**What you would need to do:** a publisher account. Vacancy data is exposed to
registered publishers via an API; the public search is behind the same login.

**Note:** the host did not resolve or connect from this network at all. That may
be geo-blocking rather than the site being down. The account requirement is the
blocker either way.

---

### 3. Eluta (Canada)

A large Canadian job board.

| What | URL | Status on 2026-10-16 |
|---|---|---|
| Main site | http://www.eluta.ca/ | SSLError (TLS handshake failed) |

**What you would need to do:** confirm the site still serves vacancies at all.
The TLS failure on both HTTP and HTTPS attempts is unusual and may be
certificate expiry, geo-blocking, or the site being retired.

**Note:** Canada is already covered by `jobbank`, so this is the least urgent
entry here.

---

### 4. Bdjobs (Bangladesh)

| What | URL | Status on 2026-10-16 |
|---|---|---|
| Main site | https://www.bdjobs.com/ | HTTP 200, redirects to `/h/` |
| `/jobs` listing | https://www.bdjobs.com/jobs | HTTP 502 |
| Employer portal | https://employer.bdjobs.com/ | ConnectionError |
| Vacancy search host | https://jobs.bdjobs.com/ | HTTP 200 (reached from the homepage) |

**What you would need to do:** confirm which of these is the current public
vacancy feed. The main site serves a listing page whose links point at
`jobs.bdjobs.com/*.asp` endpoints, so there *may* be a keyless path here -- but
`/jobs` was returning 502 during triage, so this needs a second look rather
than a credential. Bangladesh had zero postings in the corpus.

---

### 5. Adzuna (Global) -- already ruled out

| What | URL | Status on 2026-10-16 |
|---|---|---|
| Developer portal | https://developer.adzuna.com/ | HTTP 200 |

**Status: dropped.** You ruled this out earlier -- Adzuna's commercial API terms
require payment. Not an action item.

---

## B. Cloudflare-walled -- blocked on the IP, not on a credential

These need **no account**. Every one of them serves a Cloudflare interstitial
("Just a moment...", `cf-browser-verification`) to a datacenter IP, which is
what GitHub Actions runners have.

| Site | Region | Observed |
|---|---|---|
| Naukri | India | HTTP 403 on `/` and `/njkhr/login` (368b -- a block page, not content) |
| InfoJobs (ES) | Spain | captcha challenge; `/` returned **HTTP 405** |
| Jobs.ch | Switzerland | captcha challenge |
| Akhtaboot | Middle East | captcha challenge **and** robots `Disallow` for `*` |
| CV-Library | UK | HTTP 403 (Cloudflare, `/cdn-cgi/l/email-protection`) |
| HelloWork | France | robots **disallows** `/jobs`; also ReadTimeout on a 400 KB+ page |
| ZipRecruiter | Global/US | robots **disallows** the job paths |
| Jora | Australia/global | robots **disallows** the job paths |
| Dubizzle | UAE | Incapsula challenge |
| hh.ru / HeadHunter | Russia/CIS | captcha challenge |
| BrighterMonday | Kenya/Uganda | captcha challenge |
| Jobberman | Kenya/Ghana | captcha challenge |
| Laimoon | Middle East | HTTP 503 |
| net-empregos | Portugal | captcha challenge |
| jobsnepal | Nepal | captcha challenge |
| keejob.com | Tunisia | `cloudflare` marker in the body (see section C) |
| emploipartner.com | Luxembourg | `cloudflare` marker in the body |
| careercenter.am | Armenia | `cloudflare` marker in the body |
| jobwebkenya.com | Kenya | `cloudflare` marker in the body |

**A residential proxy unblocks more coverage than anything else on this page.**
It is also the one item on this page that cannot be solved by writing code, and
it has not been purchased.

**What was measured instead of buying one.** Headless Chromium was run against
IrishJobs, Stellenanzeigen and Nationale Vacaturebank and returned the *same*
Access-Denied / 63-byte / privacy-gate responses as plain HTTP. A browser does
not clear a challenge that is keyed to the IP, so "just render it" is not a way
around this section. `jobsnepal` is the working example of what does happen: its
scraper is correct and green locally, but CI came back with a Cloudflare
"Just a moment..." page, so it sits in `config/sources.json` with
`enabled: false` until it can run from a home IP.

---

## C. JS-rendered -- headless browser, and what that actually solved

Section C used to list eleven boards as "needs a browser, no anti-bot". That was
wrong on both halves and is corrected here by measurement.

Each board was requested twice: once with plain `requests`, once through a
headless Chromium, and the two responses compared.

| Site | Region | Plain HTTP | Cloudflare? | Verdict |
|---|---|---|---|---|
| **jobsearch.az** | Azerbaijan | 200, 512 KB, **0 anchors** | no | **SHIPPED** -- `jobsearch_az`, 30 rows |
| **jobs.ge** | Georgia | 200, 332 KB, 308x `?view=jobs&id=` | no | **SHIPPED** -- `jobsge`, 60 rows |
| **hiredly.com** | Malaysia | 200, 194 KB, 0 anchors | no | **SHIPPED** -- `hiredly`, 30 rows |
| **jobsireland.ie** | Ireland | 200, 176 KB, 3,898 postings | no | **SHIPPED** -- `jobsireland`, 108 rows, **no browser** |
| **jobmail.co.za** | South Africa | 200, 142 KB, 8,000+ postings | no | **SHIPPED** -- `jobmail`, 197 rows, **no browser** |
| **forasna.com** | Egypt | 200, 281 KB, 2,852 postings | no | **SHIPPED** -- `forasna`, 60 rows, **no browser** |
| shine.com | India | 200, 36 KB, 0 anchors | no | browser viable, not yet built |
| keejob.com | Tunisia | 200, 221 KB | **yes** | moved to section B |
| emploipartner.com | Luxembourg | 200, 92 KB | **yes** | moved to section B |
| careercenter.am | Armenia | 200, 599 KB | **yes** | moved to section B |
| jobwebkenya.com | Kenya | 200, 363 KB | **yes** | moved to section B |

**The split that matters is not JS-vs-HTML, it is Cloudflare-vs-not.** Four
boards were JS-rendered *and* unwalled, and those are genuinely buildable with a
browser; the four that were JS-rendered *and* walled are the same problem as
section B wearing a different hat.

**A better way to find the next source than this list.** `WebsiteToScrape.docx`
carries 200 (site, region) pairs, but the list above was drawn by asking "which
of these is reachable?" -- which finds the *reachable* boards, not the
*missing* ones. The sharper question is **"which countries does the corpus
cover thinly?"**, and then to look for a board in one of those. Measured on
2026-10-20 the corpus covered 60 countries, and the thin ones were
Bangladesh 0, Nigeria 0, Russia 0, Ukraine 0, Czechia 0, Chile 0, Peru 0,
Turkey 1, Egypt 1, Uruguay 1, Finland 2, Indonesia 3, Hungary 4, Belgium 4,
New Zealand 5, Argentina 5, Somalia 5, Italy 7, Iceland 7, Saudi Arabia 7.

That is how `forasna` was found: Egypt had **one** posting, and the docx
listed forasna. And `jobmail`: South Africa had 178 rows, and the docx
listed it -- plain HTTP, 200, 142 KB, 25 real posting links, no Cloudflare,
robots.txt disallowing only `/setup-alerts/*`, and a board holding at least
**8,000** postings.

The same pass triaged four others to nothing: `chakri.com` answers HTTP 523,
`Wuzzuf` and `Rozee.pk` are Cloudflare-walled, and `job.com.bd` serves only
10 postings a page with its `count` pagination parameter ignored outright --
the response body is byte-identical for `?count=0` and `?count=10`. Cross-referencing the docx against the corpus's thin
countries found `job.com.bd`, `chakri.com`, `Wuzzuf`, `Rozee.pk` and
`forasna` in one pass -- and a plain-HTTP triage of all five found forasna
unwalled, keyless and complete, while `chakri` answered 523, `Wuzzuf` and
`Rozee.pk` were Cloudflare-walled and `job.com.bd` served only 10 postings a
page with its pagination parameters ignored.

**CORRECTION -- "zero coverage" is the wrong frame.** Earlier notes here
treated a country as covered or not, and called Ireland and Egypt "zero
coverage". The corpus does not count countries at zero; it counts them at
*thin*, and the difference is worth 108 rows for Ireland and 60 for Egypt. The
thin list above is the honest one.

The APEC / IrishJobs / Jobs.ie / JobScout24 / Nationale Vacaturebank /
Totaljobs / Trade Me Jobs / StepStone / Stellenanzeigen / Profesia / PNet rows
this section used to carry are removed: headless Chromium was measured against
IrishJobs, Stellenanzeigen and Nationale Vacaturebank and got the same blocked
responses as plain HTTP, so "browser" was never going to be the answer for them.

**How the machinery works now.** `jobsearch_az` is the first source built this
way. `playwright` is a declared dependency in `pyproject.toml` -- not an ad-hoc
install -- and `config/sources.json` carries a `browser: true` flag so
`scrape_html.yml` runs `playwright install --with-deps chromium` for that one
job and skips the download for every other source in the matrix.

---

## D. Category and directory pages -- rejected, not blocked

Roughly nineteen candidates in the workbook look like boards and are not. The
listing URL resolves and returns HTTP 200, but what it renders is a set of
category links, not postings. A scraper written against one of these would
persist dozens of rows whose `job_title` is "Engineering" or "Sales".

minajobs.net, kumarijob.com, praca.pl, praca.by, qatarliving.com, iefp.cv,
hotnigerianjobs.com, jobfind.gr, jobwebkenya.com, bdjobs.com,
arbetsformedlingen.se, jobbnorge.no, jobnet.dk, ngcareers.com, kariera.sk,
saramin.co.kr, skill.jobs, staff.am.

This is a different verdict from sections B and C and is worth stating
separately: **no amount of proxying, credentials or browser time will make these
into postings.** They are navigation, and a board behind them may still be
worth building.

---

## E. Already investigated and resolved

| Site | Outcome |
|---|---|
| NAV Norway (arbeidsplassen.nav.no) | **No public feed exists.** Vacancies sit behind an employer login. Corrected in PR #17 after the original verdict blamed a missing key. |
| Bundesagentur für Arbeit (Germany) | `jobsuche/service-api` redirects to `/jobsuche/` (HTTP 200, 134 KB) -- the "API" path is not an API. Needs its own investigation; not yet attempted. |

---

## Recommended order

1. **shine.com** -- the last remaining unwalled JS-rendered board. The
   machinery exists; this is days of work, not a purchase. India is thinly
   covered (51job carries it, 3,696 rows).
2. **France Travail** -- an entire country, authoritative source, documented API.
   Blocked only on registration.
3. **A residential proxy** -- unblocks the whole of section B, several of them
   large national or regional leaders. Not purchased.

**CORRECTION -- jobsireland.ie.** This file previously carried it as unwalled
but with "all 188 anchors on `/en-US/browse-jobs` chrome, no posting links",
and parked it as needing a different approach than anchor scraping. That was
measuring the wrong thing. The links are plain HTML
(`/en-US/job-Details?id=2475739`) -- but a **second link per card is the
literal template** `/en-US/job-Details?id=#JobId`, with the id substituted at
runtime, so an anchor scan sees a placeholder and no id. The site is an Orchard
CMS application and is server-rendered, so it needs **no browser at all** --
the cheapest source built so far. 3,898 postings across 78 pages; built and
shipped as `jobsireland` on 2026-10-19.

**CORRECTION -- Ireland was not "zero coverage".** It was the **thinnest**-
covered country: 261 rows, and 260 of them from `greenhouse` (Stripe,
MongoDB, GitLab and Typeform postings that happened to be located in Ireland).
Fifth lowest of 59. The difference is worth 108 rows.

**CORRECTION -- jobs.ge.** This file previously carried jobs.ge as needing a
second look, on the grounds that `/ge` is "a locale prefix, not a posting
path". That was wrong. `/ge/?view=jobs&id=761321` **is** the posting: the query
string is the ad id and the page is the ad. 308 of them on page 1, with real
titles, employers, published dates and deadlines. Built and shipped as
`jobsge` on 2026-10-19; the lesson recorded in its config docstring is that a
posting path can be entirely in the query string, which a path-shape reading
misses by construction.

**CORRECTION -- hrge is Georgian, not Croatian.** `SOURCE_HOME_COUNTRY` maps
`"hrge": "GE"`, which reads like a typo for HR (Croatia). It is not: `hrge` is
`www.hr.ge`, a `.ge` domain, and its page title is `მოლარე` -- Georgian for
"Cashier". The mapping is right. Worth knowing separately: its
`announcement-search` endpoint currently returns HTTP 500 "Attempted to divide
by zero", so the source is worth re-checking before its next run.

<!-- html-sweep:start -->

## F. HTML sources measured 2026-10-21

Every site config shipped with the generic HTML framework was run once,
then the ones that produced postings were run with persistence on. The
table is generated by `scripts/render_html_sweep_docs.py` from
`reports/html_scraper_test_results.json`; it is not typed by hand.

A record only counts as a posting after
`validation/html_scraper_quality.py` accepts it. That gate was added
because the first sweep counted navigation links as successes: 499 of
536 stored rows were the site's own menu, news articles or bot-challenge
pages, and were deleted before anything was published.

**108 configs tested** -- NO_LINKS: 33 | OK: 33 | BLOCKED: 17 | PARSE_FAIL: 19 | EMPTY: 6

### Verified: postings stored (33)

| Source | Parsed in test | Row(s) stored |
| --- | --- | --- |
| `ams_at` | 2 | 0 |
| `arbeitsagentur_de` | 1 | 0 |
| `camhr_com` | 1 | 0 |
| `careercenter_am` | 1 | 0 |
| `careerviet_vn` | 1 | 0 |
| `cliclavoro_gov_it` | 2 | 0 |
| `cv_lt` | 1 | 0 |
| `educarriere` | 1 | 0 |
| `emploidakar_com` | 3 | 0 |
| `enbek_kz` | 3 | 0 |
| `hellojob` | 2 | 0 |
| `hellowork_com` | 3 | 0 |
| `iefp_cv` | 2 | 0 |
| `iefponline_iefp_pt` | 2 | 0 |
| `jobfind_gr` | 1 | 0 |
| `jobtiger_bg` | 2 | 0 |
| `jobwebkenya_com` | 3 | 6 |
| `kalibrr_com` | 3 | 0 |
| `kariera_sk` | 1 | 0 |
| `keejob_com` | 2 | 0 |
| `kosovajob_com` | 1 | 0 |
| `kumarijob_com` | 1 | 0 |
| `leforem_be` | 3 | 0 |
| `lucru_md` | 3 | 0 |
| `mifotra_gov_rw` | 1 | 0 |
| `minajobs` | 3 | 0 |
| `mojposao_ba` | 2 | 6 |
| `optius_com` | 3 | 0 |
| `posao_hr` | 3 | 0 |
| `praca_by` | 3 | 0 |
| `pracecz` | 3 | 0 |
| `skilljobs` | 3 | 0 |
| `upsvr_gov_sk` | 2 | 0 |

### Fetched pages but no posting survived the quality gate (19)

| Source | Measured reason |
| --- | --- |
| `arbeidsplassen_nav_no` | [32m2026-10-22 00:00:40.860[0m / [1mINFO    [0m / [36mjob_market_intel.scrapers.html_scraper.pipeline[0m:[36mrun[0m:[36m107[0m -  |
| `bne_cl` | [32m2026-10-22 00:00:50.397[0m / [1mINFO    [0m / [36mjob_market_intel.scrapers.html_scraper.pipeline[0m:[36mrun[0m:[36m107[0m -  |
| `burkina24_com` | [32m2026-10-22 00:00:46.917[0m / [1mINFO    [0m / [36mjob_market_intel.scrapers.html_scraper.pipeline[0m:[36mrun[0m:[36m107[0m -  |
| `empleos_net` | [32m2026-10-22 00:00:54.878[0m / [1mINFO    [0m / [36mjob_market_intel.scrapers.html_scraper.pipeline[0m:[36mrun[0m:[36m107[0m -  |
| `emploipartner_com` | [32m2026-10-22 00:00:57.465[0m / [1mINFO    [0m / [36mjob_market_intel.scrapers.html_scraper.pipeline[0m:[36mrun[0m:[36m107[0m -  |
| `emprego_sapo_pt` | [32m2026-10-22 00:00:58.570[0m / [1mINFO    [0m / [36mjob_market_intel.scrapers.html_scraper.pipeline[0m:[36mrun[0m:[36m107[0m -  |
| `hotnigerianjobs` | [32m2026-10-22 00:01:07.461[0m / [1mINFO    [0m / [36mjob_market_intel.scrapers.html_scraper.pipeline[0m:[36mrun[0m:[36m107[0m -  |
| `ikman_lk` | [32m2026-10-22 00:01:04.547[0m / [1mINFO    [0m / [36mjob_market_intel.scrapers.html_scraper.pipeline[0m:[36mrun[0m:[36m107[0m -  |
| `jobbnorge_no` | [32m2026-10-22 00:01:21.768[0m / [1mINFO    [0m / [36mjob_market_intel.scrapers.html_scraper.pipeline[0m:[36mrun[0m:[36m107[0m -  |
| `jobnet_dk` | [32m2026-10-22 00:01:20.249[0m / [1mINFO    [0m / [36mjob_market_intel.scrapers.html_scraper.pipeline[0m:[36mrun[0m:[36m107[0m -  |
| `jobzella` | [32m2026-10-22 00:01:26.983[0m / [1mINFO    [0m / [36mjob_market_intel.scrapers.html_scraper.pipeline[0m:[36mrun[0m:[36m107[0m -  |
| `magneto365_com` | [32m2026-10-22 00:02:14.597[0m / [1mINFO    [0m / [36mjob_market_intel.scrapers.html_scraper.pipeline[0m:[36mrun[0m:[36m107[0m -  |
| `mol_gov_om` | [32m2026-10-22 00:01:47.276[0m / [1mINFO    [0m / [36mjob_market_intel.scrapers.html_scraper.pipeline[0m:[36mrun[0m:[36m107[0m -  |
| `mwnation_com` | [32m2026-10-22 00:01:56.429[0m / [1mINFO    [0m / [36mjob_market_intel.scrapers.html_scraper.pipeline[0m:[36mrun[0m:[36m107[0m -  |
| `ngcareers_com` | [32m2026-10-22 00:01:54.499[0m / [1mINFO    [0m / [36mjob_market_intel.scrapers.html_scraper.pipeline[0m:[36mrun[0m:[36m107[0m -  |
| `praca_pl` | [32m2026-10-22 00:02:11.895[0m / [1mINFO    [0m / [36mjob_market_intel.scrapers.html_scraper.pipeline[0m:[36mrun[0m:[36m107[0m -  |
| `qatarliving_com` | [32m2026-10-22 00:02:20.441[0m / [1mINFO    [0m / [36mjob_market_intel.scrapers.html_scraper.pipeline[0m:[36mrun[0m:[36m107[0m -  |
| `wanted_co_kr` | [32m2026-10-22 00:02:48.857[0m / [1mINFO    [0m / [36mjob_market_intel.scrapers.html_scraper.pipeline[0m:[36mrun[0m:[36m107[0m -  |
| `zaplata_bg` | [32m2026-10-22 00:02:31.471[0m / [1mINFO    [0m / [36mjob_market_intel.scrapers.html_scraper.pipeline[0m:[36mrun[0m:[36m107[0m -  |

### Listing has no job links over plain HTTP (33)

| Source | Measured reason |
| --- | --- |
| `agenceemploijeunes` | no postings found |
| `alwatwan` | no postings found |
| `alwihdainfo` | no postings found |
| `aptitus_com` | no postings found |
| `brightermonday_co_tz` | no postings found |
| `bumeran_com_ar` | no postings found |
| `bumeran_com_pe` | no postings found |
| `dubizzle_com` | no postings found |
| `empleo_gob_mx` | no postings found |
| `ethiojobs` | no postings found |
| `gupy_io` | no postings found |
| `hiredly_com` | no postings found |
| `iskur_gov_tr` | no postings found |
| `jamaica_gleaner_com` | no postings found |
| `jamaicaobserver_com` | no postings found |
| `job_mynavi_jp` | no postings found |
| `jobline_hu` | no postings found |
| `jobsearch_az` | no postings found |
| `jobthai_com` | no postings found |
| `karir_com` | no postings found |
| `kuenselonline_com` | no postings found |
| `laimoon_com` | no postings found |
| `samoaobserver_ws` | no postings found |
| `superjob_ru` | no postings found |
| `tootukassa_ee` | no postings found |
| `tyopaikat_oikotie_fi` | no postings found |
| `vagas_com_br` | no postings found |
| `vaterland_li` | no postings found |
| `willhaben_at` | no postings found |
| `workandincome_govt_nz` | no postings found |
| `workforceaustralia_gov_au` | no postings found |
| `zhipin_com` | no postings found |
| `zonajobs_com_ar` | no postings found |

### Refused the request (403 / WAF) (17)

| Source | Measured reason |
| --- | --- |
| `ar_computrabajo_com` | 403 Client Error |
| `bestjobs_eu` | 403 Client Error |
| `co_computrabajo_com` | 403 Client Error |
| `do_computrabajo_com` | 403 Client Error |
| `ec_computrabajo_com` | 403 Client Error |
| `gt_computrabajo_com` | 403 Client Error |
| `hn_computrabajo_com` | 403 Client Error |
| `lmra_gov_bh` | 403 Client Error |
| `mx_computrabajo_com` | 403 Client Error |
| `naukri_com` | 403 Client Error |
| `ni_computrabajo_com` | 403 Client Error |
| `pa_computrabajo_com` | 403 Client Error |
| `punaime_al` | 403 Client Error |
| `py_computrabajo_com` | 403 Client Error |
| `sv_computrabajo_com` | 403 Client Error |
| `uy_computrabajo_com` | 403 Client Error |
| `ve_computrabajo_com` | 403 Client Error |

### Listing request failed (server error, TLS, timeout) (6)

| Source | Measured reason |
| --- | --- |
| `fne_cm` | [32m2026-10-22 00:00:55.748[0m / [33m[1mWARNING [0m / [36mjob_market_intel.scrapers.html_scraper.client[0m:[36mdiscover_detail_paths |
| `helloworld_rs` | [32m2026-10-22 00:00:59.409[0m / [33m[1mWARNING [0m / [36mjob_market_intel.scrapers.html_scraper.client[0m:[36mdiscover_detail_paths |
| `jobs_id` | [32m2026-10-22 00:01:19.449[0m / [33m[1mWARNING [0m / [36mjob_market_intel.scrapers.html_scraper.client[0m:[36mdiscover_detail_paths |
| `nsz_gov_rs` | [32m2026-10-22 00:01:57.547[0m / [33m[1mWARNING [0m / [36mjob_market_intel.scrapers.html_scraper.client[0m:[36mdiscover_detail_paths |
| `nva_gov_lv` | [32m2026-10-22 00:02:12.455[0m / [33m[1mWARNING [0m / [36mjob_market_intel.scrapers.html_scraper.client[0m:[36mdiscover_detail_paths |
| `trinidadexpress_com` | [32m2026-10-22 00:02:37.018[0m / [33m[1mWARNING [0m / [36mjob_market_intel.scrapers.html_scraper.client[0m:[36mdiscover_detail_paths |

<!-- html-sweep:end -->

<!-- browser-sweep:start -->

## G. Browser (Selenium) sources measured 2026-10-22

The boards in section F that failed over plain HTTP because their
listings are rendered by JavaScript were rebuilt on the browser
framework (`src/job_market_intel/scrapers/browser_scraper/`): a real
Chrome in undetected mode, the rendered page read after the page has
finished running its scripts, and the same parser, quality gate and
persistence path as the HTML framework.

The table is generated from `reports/browser_scraper_test_results.json`.

**8 configs tested** -- OK: 8

### Verified in a real browser: postings stored (8)

| Source | Rendered | Parsed | Seconds |
| --- | --- | --- | --- |
| `arbeidsplassen_nav_no` | 4 | 4 | 58.6  |
| `bumeran_com_ar` | 4 | 4 | 50.8  |
| `bumeran_com_pe` | 4 | 4 | 50.0  |
| `careercenter_am` | 4 | 2 | 57.4  |
| `ethiojobs` | 4 | 4 | 34.1  |
| `keejob_com` | 4 | 2 | 101.4  |
| `minajobs` | 4 | 4 | 76.0  |
| `ngcareers_com` | 4 | 4 | 47.0  |

### Rendered in a browser and still not usable

Every remaining candidate from the list was opened in the same browser
before it was written off. The reason is measured, not assumed:

| Source | URL | Verdict | Why |
| --- | --- | --- | --- |
| `zhipin_com` | https://www.zhipin.com/ | CHALLENGE | served the security-check page (安全验证) even to a real browser |
| `superjob_ru` | https://superjob.ru/ | CHALLENGE | served a captcha page with zero links |
| `jobnet_dk` | https://job.jobnet.dk/CV/FindWork/Search | NEEDS_LOGIN | the job search is behind a MitID login |
| `gupy_io` | https://gupy.io/en/jobs | NOT_A_BOARD | an HR platform, not a public job board; 404 on /en/jobs and no posting links |
| `jobline_hu` | https://www.jobline.hu/ | DEAD | redirects to hvg.hu, three anchors, no jobs |
| `kuenselonline_com` | https://www.kuenselonline.com/jobs | TLS_ERROR | the site's certificate fails privacy checks in the browser |
| `jobs_id` | https://www.jobs.id/ | TLS_ERROR | the site's certificate fails privacy checks in the browser |
| `tyopaikat_oikotie_fi` | https://www.tyopaikat.oikotie.fi/ | DNS_FAIL | the host did not resolve |
| `ikman_lk` | https://www.ikman.lk/jobs | NO_POSTINGS | classifieds, not a job board; the ad list renders 29 anchors and no posting links |
| `jobbnorge_no` | https://www.jobbnorge.no/search | NO_POSTINGS | the search result list is built after load and never appeared |
| `tootukassa_ee` | https://www.tootukassa.ee/et/jalus | NO_POSTINGS | the vacancy list is a widget that did not render; only service links |
| `iskur_gov_tr` | https://www.iskur.gov.tr/ | NO_POSTINGS | 428 links on the homepage, none of them postings; the job-list path errors |
| `mol_gov_om` | https://www.mol.gov.om/manpoweralleservices/ | NOT_POSTINGS | a government service portal; the links are services, not vacancies |
| `brightermonday_co_tz` | https://www.brightermonday.co.tz/ | NOT_POSTINGS | a company blog; every link is a /discover/ article |
| `laimoon_com` | https://www.laimoon.com/jobs | NOT_POSTINGS | a training-course marketplace, not a job board |
| `dubizzle_com` | https://www.dubizzle.com/ | NOT_POSTINGS | classifieds; the job links are per-city category pages, not postings |
| `jobzella` | https://www.jobzella.com/ | NO_POSTINGS | the listing is /search/jobs and the homepage carries no posting links |
| `job_mynavi_jp` | https://job.mynavi.jp/pc/jobs | NO_POSTINGS | 404; the student portal's routes did not resolve |
| `jobfind_gr` | https://www.jobfind.gr/JobAdsSearch/GR/Theseis_Ergasias | NO_POSTINGS | 170 links under /JobAds/ are city filters, not postings; the ads themselves are not links in the rendered page |
| `lucru_md` | https://lucru.md/ro/posturi-vacante | NO_POSTINGS | the rendered page carries only categories and navigation; individual vacancies are not anchors |
| `bne_cl` | https://bne.cl/ofertas?mostrar=empleo | NO_POSTINGS | the offer list is fetched after load and never appeared; the only job-shaped links are off-site sence.gob.cl pages |
| `aptitus_com` | https://www.aptitus.com/ | DUPLICATE | serves the Bumeran Peru board (page title 'Trabajos - Empleos | Bumeran Peru'); retired in favour of bumeran_com_pe |
| `alwihdainfo` | https://www.alwihdainfo.com/ | NOT_POSTINGS | a news site; every link is a tag or an article |
| `alwatwan` | https://www.alwatwan.net/ | NOT_POSTINGS | a Comorian newspaper; sections are politics, economy, sport, culture |
| `agenceemploijeunes` | https://agenceemploijeunes.civ/ | DNS_FAIL | the host did not resolve |
<!-- browser-sweep:end -->
