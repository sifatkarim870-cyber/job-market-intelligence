# Sources that need a registration, an API key, or a proxy

Generated 2026-10-16 from `WebsiteToScrape.docx` joined against
`job_sites_by_country_SCRAPEABILITY_backup_20261007.xlsx` and a live re-probe.
Sections B, C and D rewritten **2026-10-18** from direct measurement.

Every URL below was **requested during this triage** and its HTTP status is
recorded, because reciting an API endpoint from memory is how people end up
signing up for one that has moved. Where a URL failed to resolve today, that is
said rather than quietly dropped.

Nothing here needs the scraper to exist first -- each entry is blocked purely on
a credential, a network capability, or the fact that the page is not what it
claims to be. Several entries have since been built anyway; the reconciliation
below records which, before the historical tables.

**The three verdicts are different and are kept apart deliberately:**

- **A / B** -- blocked. Needs an account (A) or a residential IP (B).
- **C** -- buildable. Needs engineering time, not money.
- **D** -- rejected. Not a posting list at all, so no amount of the above helps.

## STATUS RECONCILIATION -- 2026-11-13

The tables below are the **2026-10-16/18 measurement record** and are kept as
written. Eight entries that this page recorded as blocked or unbuilt have since
been built and are **enabled in `config/sources.json`** (verified 2026-11-13
against the registry and `core.jobs`):

| Earlier verdict here | Registry code | Rows | How it was cleared |
|---|---|---|---|
| Section B -- hh.ru captcha-walled | `hh_ru` | 57 | `impersonate: "chrome"`; HeadHunter HTML listing, JSON-LD details |
| Section B -- Jobs.ch captcha | `jobs_ch` | 60 | JSON-LD details; server-rendered listing |
| Section B -- BrighterMonday captcha | `brightermonday_co_ug` | 60 | Uganda; `detail_json_ld_fill` |
| Section B -- net-empregos captcha | `net_empregos` | 1,509 | server-rendered listing; largest of the eight |
| Section B -- jobsnepal captcha | `jobsnepal` | 172 | now **enabled** (no longer the `enabled: false` example in the B paragraph) |
| Section B / C -- keejob.com `cloudflare` marker | `keejob_tn` | 60 | Tunisia; unwalled from a home IP |
| Section B / C -- careercenter.am `cloudflare` marker | `careercenter_am` | 49 | browser group; unwalled from a home IP |
| Section C -- shine.com "browser viable, not yet built" | `shine` | 72 | built server-side, no browser needed |

Two section-D "rejected directory" entries have likewise been built since:
`minajobs` (154 rows) and `staff_am` (37 rows). The entries below that are *not*
marked BUILT remain unbuilt and are still blocked exactly as described.

A ninth board, **Jobberman (Nigeria)** -- mislabelled "Kenya/Ghana" in the B
table -- was measured afresh and is now built as `jobberman` (60 rows). It is not
captcha-walled from a home IP; the earlier "captcha challenge" note was taken
against a datacenter IP.

A tenth board, **Rozee.pk (Pakistan)** -- recorded in section B/C as
Cloudflare-walled (plain HTTP returns a shell / 403) -- is now built as
`rozee_pk` (54 rows) on the **browser (Selenium)** framework: the listing at
`https://www.rozee.pk/` renders ~320 posting links and every detail page
publishes a full schema.org `JobPosting` JSON-LD block that `detail_json_ld`
maps (title, employer, description, PKR salary, posted date). Verified
2026-11-13; CI run 43298965524 SUCCESS, 54 inserted.

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
| Jobs.ch | Switzerland | captcha challenge -- **BUILT** as `jobs_ch` |
| Akhtaboot | Middle East | captcha challenge **and** robots `Disallow` for `*` |
| CV-Library | UK | HTTP 403 (Cloudflare, `/cdn-cgi/l/email-protection`). Re-measured 2026-11-20: a hard deny ("You triggered a security action"), not a challenge to solve. Only the cached `/` returns 200 (Next.js shell, no job links, no job API); robots.txt, sitemap, listings and job pages are 403 from both this host and a US datacenter, and a real Chrome (SeleniumBase UC) gets the same page. NOT BUILDABLE without a proxy: robots.txt itself is unreadable, so compliance cannot be established |
| HelloWork | France | robots **disallows** `/jobs`; also ReadTimeout on a 400 KB+ page |
| ZipRecruiter | Global/US | robots **disallows** the job paths |
| Jora | Australia/global | robots **disallows** the job paths |
| Dubizzle | UAE | Incapsula challenge |
| hh.ru / HeadHunter | Russia/CIS | captcha challenge -- **BUILT** as `hh_ru` (`impersonate: "chrome"`) |
| BrighterMonday | Kenya/Uganda | captcha challenge -- **BUILT** as `brightermonday_co_ug` (Uganda) |
| Jobberman | Nigeria | captcha challenge from a datacenter IP -- **BUILT** as `jobberman` (unwalled from a home IP) |
| Laimoon | Middle East | HTTP 503 |
| net-empregos | Portugal | captcha challenge -- **BUILT** as `net_empregos` |
| jobsnepal | Nepal | captcha challenge -- **BUILT** as `jobsnepal` (now enabled) |
| keejob.com | Tunisia | `cloudflare` marker in the body (see section C) -- **BUILT** as `keejob_tn` |
| emploipartner.com | Luxembourg | `cloudflare` marker in the body |
| careercenter.am | Armenia | `cloudflare` marker in the body -- **BUILT** as `careercenter_am` (browser group) |
| jobwebkenya.com | Kenya | `cloudflare` marker in the body |
| APEC | France | DataDome wall (`window.ddjskey`, `geo.captcha-delivery.com`): 403 on `/`, `/robots.txt`, `/sitemap.xml`, the search/detail pages and `/rss/offres.xml`; re-measured 2026-11-20 from this host and a US datacenter, with curl_cffi impersonation and a real Chrome. The JSON API is protected too (`ajaxListenerPath: ['/cms/webservices', '/.apec-login.do']`), so only a proxy would reach it |
| Catho | Brazil | AWS ALB fixed-response **HTTP 403** (server: awselb/2.0, 520-byte static body, no challenge) on every path including `/robots.txt`; re-measured 2026-11-20 from this host, a US datacenter and a real Chrome, and with Googlebot/bingbot UAs. Brazil-IP-only, so it needs a proxy; robots.txt is unreadable, so compliance cannot be established |

**A residential proxy unblocks more coverage than anything else on this page.**
It is also the one item on this page that cannot be solved by writing code, and
it has not been purchased.

**What was measured instead of buying one.** Headless Chromium was run against
IrishJobs, Stellenanzeigen and Nationale Vacaturebank and returned the *same*
Access-Denied / 63-byte / privacy-gate responses as plain HTTP. A browser does
not clear a challenge that is keyed to the IP, so "just render it" is not a way
around this section. `jobsnepal` was the working example of what happens (correct
and green locally, a Cloudflare "Just a moment..." page in CI), and it sat in
`config/sources.json` with `enabled: false` until it could run from a home IP --
it is **enabled now** (172 rows, 2026-11-13). The point it illustrated still
stands for every entry below not marked BUILT.

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
| shine.com | India | 200, 36 KB, 0 anchors | no | **SHIPPED** -- `shine`, 72 rows, no browser |
| keejob.com | Tunisia | 200, 221 KB | **yes** | moved to section B -- now **BUILT** as `keejob_tn` |
| emploipartner.com | Luxembourg | 200, 92 KB | **yes** | moved to section B |
| careercenter.am | Armenia | 200, 599 KB | **yes** | moved to section B -- now **BUILT** as `careercenter_am` |
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

**Update 2026-11-13:** two of these were later built anyway, because their
*detail* pages are postings even though the page listed here is a navigation
hub: `minajobs` (154 rows) and `staff.am` (37 rows). The rest of the list still
stands exactly as measured.

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

1. ~~**shine.com**~~ -- **DONE.** Built and shipped as `shine` (72 rows,
   server-side, no browser). It was the last remaining unwalled JS-rendered
   board; India is thinly covered (51job carries it, 3,696 rows).
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

### Built after the 2026-10-22 sweep

- **`rozee_pk`** (Pakistan, rozee.pk) -- 2026-11-13. The listing at
  `https://www.rozee.pk/` renders ~320 posting links of the form
  `/<slug>-jobs-<id>`; the detail DOM is React/MUI with unstable generated
  classes, but each ad publishes a schema.org `JobPosting` **JSON-LD** block, so
  `detail_json_ld` maps title, employer (`hiringOrganization.name`), description
  (1,605-9,733 chars), posted date and the structured PKR-monthly `baseSalary`.
  `detail_url_pattern` is `-jobs-\d+$`. Verified locally and in CI (run
  43298965524): 54 fetched, 54 parsed, batch validation PASSED, 54 inserted; all
  54 rows country Pakistan. Pakistan was already seeded (country_id 38, PKR), so
  only `SOURCE_HOME_COUNTRY["rozee_pk"] = "PK"` was added. This board's plain
  HTTP response is a JS shell (recorded as a 403/Cloudflare wall in 2026-10-22),
  so it is the browser framework that makes it buildable.

- **`landing_jobs`** (Portugal, landing.jobs) -- 2026-11-13. A Lisbon-based
  pan-European tech board; the listing at `https://landing.jobs/jobs` renders 50
  ad cards (plain HTTP returns a ~5 KB shell, so it needs the browser). The SPA
  paginates only client-side (`?page=N` renders 4 more on a click but a direct
  GET always serves page 1), so `max_pages` is 1. Each detail page publishes a
  schema.org `JobPosting` **JSON-LD** block, so `detail_json_ld` maps title,
  employer (`hiringOrganization.name`), locality+country, description
  (1,495-12,845 chars), posted date, employment type and the structured EUR
  yearly `baseSalary` (15/50 ads). `detail_url_pattern` is `/at/[^/]+/[^/]+$`.
  Portugal is already seeded (country_id 9), so no seed or `SOURCE_HOME_COUNTRY`
  change was needed -- all 50 rows resolved from the location text (49 Portugal,
  1 Poland). Verified locally: 50 fetched / 50 parsed / 50 inserted, batch
  validation PASSED, 0 failed. **Disabled in CI**: runs 43311284418 and
  43311901554 both had the runner's datacenter IP served a Cloudflare
  `challenge-platform` page instead of the listing, so it is kept BUILT
  (Disabled in CI) -- the same datacenter-IP wall as `tanitjobs`.

- **`mojedelo`** (Slovenia, mojedelo.com) -- 2026-11-13. Slovenia's largest
  job board; the listing at `https://www.mojedelo.com/iskanje-zaposlitve`
  renders 20 ad cards per page and `?jobSearchPage={page}` was measured
  serving 20 distinct ads per page with 0 overlap, so it needs the browser
  (plain HTTP returns a shell). Each detail page publishes a schema.org
  `JobPosting` **JSON-LD** block, so `detail_json_ld` maps title, employer,
  locality+region, description+qualifications (145-1,245 chars), posted date
  and employment type; `detail_url_pattern` is `/oglas/[^/]+/[0-9a-f-]{36}$`.
  MojeDelo embeds a **passive reCAPTCHA** widget on every ad, so its markup
  always contains `g-recaptcha` and the built-in challenge markers rejected
  every page -- this is what the new config-gated
  `ignore_challenge_markers` field exists for. Verified locally and in CI
  (run 43324675623): 60 fetched, 60 parsed, 60 inserted, batch validation
  PASSED, 0 failed. Slovenia was seeded (`ref.countries` SI) and
  `SOURCE_HOME_COUNTRY["mojedelo"] = "SI"` added; note Slovenia already had
  `optius_com` built, but its 120 rows were all country-NULL because the
  country was unseeded, so `mojedelo` is the first Slovenian source to
  resolve a country. Slovenian cities/regions are not yet in
  `ref.cities`/`ref.regions`, so the resolver places every ad at one
  country-level location (the platform's documented fallback); seeding a
  curated Slovenian city set is the follow-up for city-level rows.

- **`104_tw`** (Taiwan, 104.com.tw) -- 2026-11-14. Taiwan's largest job bank.
  The search listing at `https://www.104.com.tw/jobs/search/` renders 20 ad
  cards per page, and pagination `?page={page}` serves 20 distinct ads per page.
  Plain HTTP encounters a Cloudflare `403 Forbidden` TLS fingerprint check;
  SeleniumBase undetected Chrome bypasses it cleanly with no challenge. Each
  detail page publishes a schema.org `JobPosting` **JSON-LD** block inside a
  list container, which `detail_json_ld` maps: title, employer
  (`hiringOrganization.name`), locality+region, description (HTML decoded),
  posted date, employment type, and salary (`baseSalary.value.value`).
  `detail_url_pattern` is `^/job/[a-zA-Z0-9]+` and `id_url_regex` is
  `/job/([a-zA-Z0-9]+)`. Verified locally: 5 fetched / 5 parsed / 5 cleaned /
  5 inserted, batch validation PASSED, 0 failed. CI SUCCESS 2026-11-14: browser-group
  run 43519426253 rendered the search listing and detail pages in headless Chrome
  via seleniumbase UC mode on Ubuntu with no Cloudflare challenge, parsed and
  persisted postings, extracted sections, and exported a Hugging Face shard.
  Taiwan is already seeded (`ref.countries` TW, country_id 5216), and
  `SOURCE_HOME_COUNTRY["104_tw"] = "TW"` was added.

- **`1111_tw`** (Taiwan, 1111.com.tw) -- 2026-11-14. Taiwan's second largest
  job portal. The search listing at `https://www.1111.com.tw/search/job`
  runs in SeleniumBase UC mode and extracts schema.org `JobPosting` **JSON-LD**:
  title, employer (`hiringOrganization.name`), locality+region, description,
  posted date, employment type, and salary (`baseSalary.value.minValue`).
  `detail_url_pattern` is `^/job/\\d+/?` and `id_url_regex` is `/job/(\\d+)`.
  Verified locally: 5 fetched / 5 parsed / 5 cleaned / 5 inserted, batch
  validation PASSED, 0 failed. `SOURCE_HOME_COUNTRY["1111_tw"] = "TW"` added.
  **Disabled in CI**: runs 43522012440 and 43618507110 showed the runner's
  datacenter IP is served a persistent `captcha_ch` loader challenge that does
  not yield ad cards (never showed `a[href*='/job/']`), so it is kept BUILT
  (Disabled in CI) until residential proxy support is added.

- **`adem_lu`** (Luxembourg, adem.public.lu) -- 2026-11-15. Public employment agency
  of Luxembourg (Agence pour le développement de l'emploi). Previously misclassified
  in backlog sweep as having no job list route; reverse-engineering the site's AEM
  JobBoard component revealed the direct CTIE REST endpoint at
  `https://adem.public.lu/ctie/jobboard?id=...`, which streams all active Luxembourg
  job vacancies (over 2,600 live postings) in NDJSON chunks without bot challenges,
  captchas, or authentication. Offers are enriched with full descriptions via the
  accompanying REST endpoint `/ctie/jobboard/offer?id=...&ref={ref}`. Built as a
  dedicated `api` group scraper (`scripts/run_adem_lu_scraper.py`), mapping reference,
  title, employer, locality/canton, contract type, duration, schedule, and languages.
  Luxembourg is seeded in `ref.countries` (ISO `LU`/`LUX`, continent Europe, default
  currency EUR) and registered in `SOURCE_HOME_COUNTRY["adem_lu"] = "LU"`. Verified
  locally: 2,639 raw discovered, parsed, normalized, persisted to Postgres, batch
  validation PASSED, 0 failed. CI SUCCESS 2026-11-15: Scrape (API) run 43629165500
  streamed the NDJSON feed, enriched 60 offers with full descriptions in 1m19s on
  Ubuntu runner, 60 inserted / 0 failed, description sections extracted, and Parquet
  shard exported to Hugging Face. LIVE in scheduled CI matrix.

- **`ajira_tz`** (Tanzania, portal.ajira.go.tz) -- 2026-11-15. Public Service Recruitment
  Secretariat (PSRS) vacancy portal for the United Republic of Tanzania. Previously
  misclassified in backlog sweep as unreachable due to SSLError on apex `ajira.go.tz`.
  Analysis of the portal application revealed an active, public GraphQL API at
  `https://portal.ajira.go.tz/candidates/graphql` requiring no authentication or API keys.
  The queries `GetVacancies` and `GetVacancy(vacancyId)` provide vacancy titles, scheme
  definitions, duties & responsibilities, qualifications, salary scale grades, employer
  names, opening and closing dates, and post counts. Built as a dedicated `api` group
  scraper (`scripts/run_ajira_tz_scraper.py`). Tanzania is seeded in `ref.countries`
  (ISO `TZ`/`TZA`, continent Africa, default currency TZS) and registered in
  `SOURCE_HOME_COUNTRY["ajira_tz"] = "TZ"`. Verified locally: 16 raw discovered,
  parsed, normalized, persisted to Postgres, batch validation PASSED, 0 failed. CI SUCCESS
  2026-11-15: Scrape (API) run 43635137308 queried the GraphQL API, retrieved details
  for all 16 postings, 16 inserted / 0 failed in 1m29s, description sections extracted,
  and Parquet shard exported to Hugging Face. LIVE in scheduled CI matrix.

- **`finn_no`** (Norway, finn.no) -- 2026-11-15. Norway's primary job portal.
  Previously misclassified in backlog sweep as having an unsupported JSON-LD single-key
  wrapper (`script:ld+json`). Analysis of the search portal revealed server-rendered
  pagination at `https://www.finn.no/job/search` with 50+ job links per page, and detail
  pages embedding full schema.org `JobPosting` JSON-LD under `script:ld+json` with
  job title, hiring organization, locality, posting dates, expiration dates, employment
  type, and complete HTML descriptions. Built as a dedicated `api` group scraper
  (`scripts/run_finn_no_scraper.py`). Norway is registered in `ref.countries` (ISO
  `NO`/`NOR`, continent Europe, default currency NOK) and registered in
  `SOURCE_HOME_COUNTRY["finn_no"] = "NO"`. Verified locally: 5 raw discovered,
  parsed, normalized, persisted to Postgres, batch validation PASSED, 0 failed. CI SUCCESS
  2026-11-15: Scrape (API) run 43636028568 retrieved search listings and details,
  persisted 58 jobs (0 failed) in 1m37s on Ubuntu runner, extracted description sections,
  and exported Parquet shard to Hugging Face. LIVE in scheduled CI matrix.

- **`mojposao_hr`** (Croatia, moj-posao.net) -- 2026-11-15. Leading job board in Croatia.
  Previously misclassified in backlog sweep as unsupported due to Nuxt 3 state
  (`__NUXT_DATA__`). Analysis revealed that the search portal server-renders 100 job
  links per page at `https://www.moj-posao.net/Pretraga-Poslova/`, and detail pages
  embed a deserializable Nuxt 3 object graph containing full job titles, hiring
  organizations, locations, complete duties/requirements/benefits, and validity dates.
  Built as a dedicated `api` group scraper (`scripts/run_mojposao_hr_scraper.py`).
  Croatia is seeded in `ref.countries` (ISO `HR`/`HRV`, continent Europe, default
  currency EUR) and registered in `SOURCE_HOME_COUNTRY["mojposao_hr"] = "HR"`.
  Verified locally: 5 raw discovered, parsed, normalized, persisted to Postgres,
  batch validation PASSED, 0 failed. CI SUCCESS 2026-11-15: Scrape (API) run 43636942644
  fetched listings, deserialized Nuxt 3 data for 60 postings in 1m22s, 60 inserted /
  0 failed on Ubuntu runner, description sections extracted, and Parquet shard exported
  to Hugging Face. LIVE in scheduled CI matrix.

- **`vrabotuvanje_mk`** (North Macedonia, vrabotuvanje.com.mk) -- 2026-11-15. Leading job
  portal in North Macedonia (Alma Career South). Previously misclassified in backlog
  sweep as unsupported due to Nuxt 3 state (`__NUXT_DATA__`). Gathers active
  `/rabota/{uuid}/{slug}` postings across the homepage and `/rabotni-mesta` directory,
  then deserializes each posting's embedded Nuxt 3 object graph containing title,
  employer, locality, full job descriptions, qualifications, and validity dates.
  Built as a dedicated `api` group scraper (`scripts/run_vrabotuvanje_mk_scraper.py`).
  North Macedonia is registered in `ref.countries` (ISO `MK`/`MKD`, continent Europe,
  default currency MKD) and registered in `SOURCE_HOME_COUNTRY["vrabotuvanje_mk"] = "MK"`.
  Verified locally: 5 raw discovered, parsed, normalized, persisted to Postgres, batch
  validation PASSED, 0 failed. CI verification run 43639056689 succeeded: 60 inserted,
  0 failed on Ubuntu runner, description sections extracted, and Parquet shard exported
  to Hugging Face. LIVE in scheduled CI matrix.

- **`merojob_np`** (Nepal, merojob.com) -- 2026-11-15. Nepal's premier job portal.
  Previously misclassified in backlog sweep as unsupported due to Next.js App Router
  (`self.__next_f`). Built as a dedicated `api` group scraper (`scripts/run_merojob_np_scraper.py`)
  querying Merojob's public REST API at `https://api.merojob.com/api/v1/jobs/` for active vacancy
  discovery and `https://api.merojob.com/api/v1/jobs/{job_id}/` for full structured details
  (duties, specifications, skills, employer, locations, and salary in NPR).
  Nepal is registered in `ref.countries` (ISO `NP`/`NPL`, continent Asia, default currency NPR)
  and registered in `SOURCE_HOME_COUNTRY["merojob_np"] = "NP"`.
  Verified locally: 5 raw discovered, parsed, normalized, persisted to Postgres, batch
  validation PASSED, 0 failed. CI verification run 43642434020 succeeded: 60 inserted,
  0 failed on Ubuntu runner, description sections extracted, and Parquet shard exported
  to Hugging Face. LIVE in scheduled CI matrix.

- **`jobbkk_th`** (Thailand, jobbkk.com) -- 2026-11-15. Thailand's leading employment portal.
  Previously misclassified in backlog sweep as unsupported due to Next.js App Router
  (`self.__next_f`). Built as a dedicated `api` group scraper (`scripts/run_jobbkk_th_scraper.py`)
  paginating server-rendered search directories at `https://www.jobbkk.com/jobs/lists/{page}` to
  discover `/jobs/(?:detail|detailurgent)/{emp_id}/{job_id}` vacancies, then parsing complete
  Schema.org `JobPosting` JSON-LD containing title, employer, locality, full job description,
  validity dates, and THB salary.
  Thailand is registered in `ref.countries` (ISO `TH`/`THA`, continent Asia, default currency THB)
  and registered in `SOURCE_HOME_COUNTRY["jobbkk_th"] = "TH"`.
  Verified locally: 5 raw discovered, parsed, normalized, persisted to Postgres, batch
  validation PASSED, 0 failed. CI verification run 43643325864 succeeded: 60 inserted,
  0 failed on Ubuntu runner, description sections extracted, and Parquet shard exported
  to Hugging Face. LIVE in scheduled CI matrix.

- **`goodwork_ca`** (Canada, goodwork.ca) -- 2026-11-15. Canada's leading green and environmental
  employment network. Previously misclassified in backlog sweep as an unsupported JS shell
  due to apex domain redirection. Built as a dedicated `api` group scraper
  (`scripts/run_goodwork_ca_scraper.py`) querying server-rendered directory at
  `https://www.goodwork.ca/jobs` to discover active `/jobs/{slug}-{job_id}` postings, then
  parsing structured section content containing title, organization, locality, duties,
  qualifications, and remuneration in CAD.
  Canada is registered in `ref.countries` (ISO `CA`/`CAN`, continent North America, default currency CAD)
  and registered in `SOURCE_HOME_COUNTRY["goodwork_ca"] = "CA"`.
  Verified locally: 5 raw discovered, parsed, normalized, persisted to Postgres, batch
  validation PASSED, 0 failed. CI verification run 43754251004 succeeded: 46 inserted,
  0 failed on Ubuntu runner, description sections extracted, and Parquet shard exported
  to Hugging Face. LIVE in scheduled CI matrix.

- **`job_com_bd`** (Bangladesh, job.com.bd) -- 2026-11-16. Major recruitment directory in Bangladesh.
  Paginates server-rendered search directories at `https://job.com.bd/jobs?page={page}` discovering
  `/jobs/{slug}-{id}` postings, extracting structured semantic cards (`jd-title-block`, `jd-fact`,
  `jd-card`) for duties, qualifications, and monthly BDT salaries.
  Bangladesh is registered in `ref.countries` (ISO `BD`/`BGD`, continent Asia, default currency BDT)
  and registered in `SOURCE_HOME_COUNTRY["job_com_bd"] = "BD"`.
  Verified locally: 60 discovered across 5 pages, 5 parsed, normalized, persisted to Postgres (Session 118,
  5 inserted, 0 failed, batch validation PASSED). In GitHub Actions CI (runs 43769324285 and 43769969723),
  the origin server drops/times out all TCP/TLS connections from Azure US datacenter runners. Kept BUILT
  (`enabled: false` in `config/sources.json`), status: `BUILT (Disabled in CI)`. Not included in scheduled matrix.

- **`jobkorea_kr`** (South Korea, jobkorea.co.kr) -- 2026-11-16. South Korea's premier employment and talent
  acquisition network. Previously misclassified in backlog sweep as an unsupported Next.js App Router shell.
  Reverse engineering revealed server-rendered search directory pagination at
  `https://www.jobkorea.co.kr/recruit/joblist?Page={page}&menucode=local&localorder=1` discovering 115+
  unique job IDs per page (`/Recruit/GI_Read/{job_id}`). Detail pages embed comprehensive Schema.org
  `JobPosting` JSON-LD blocks including title, enterprise, locality, KRW remuneration, and closing dates,
  with HTML fallback parsing.
  South Korea is registered in `ref.countries` (country_id 30, ISO `KR`/`KOR`, continent Asia, default currency KRW)
  and registered in `SOURCE_HOME_COUNTRY["jobkorea_kr"] = "KR"`. Added KRW conversion rate (`0.00072`) to
  `_USD_CONVERSION_RATES` in `salary_standardization.py`.
  Verified locally: 115 discovered, 5 parsed, normalized, persisted to Postgres (Session 119, 5 inserted, 0 failed,
  batch validation PASSED). In GitHub Actions CI (run 43773212988), 100% SUCCESS: 50 inserted, 0 failed,
  description sections extracted, and Parquet shard exported to Hugging Face. LIVE and enabled in scheduled CI matrix.

- **`gallito_uy`** (Uruguay, trabajo.gallito.com.uy) -- 2026-11-16. Uruguay's leading employment portal (Gallito).
  Previously misclassified in backlog sweep � the main domain `gallito.com.uy` returns Cloudflare, but the
  dedicated jobs subdomain `trabajo.gallito.com.uy` serves plain HTTP (no bot protection). Search directory
  paginates at `https://trabajo.gallito.com.uy/buscar/page/{page}` (20 jobs/page, up to 42 pages). Detail pages
  at `/anuncio/{slug}-{id}` carry Schema.org `JobPosting` JSON-LD with title, hiringOrganization,
  jobLocation (UY/Montevideo), datePosted, validThrough, and employmentType. Salary fields are rare but parsed
  when present. Description sections in `div.cuadro-aviso` containers (Responsabilidades, Funciones, Requisitos).
  UYU inserted into `ref.currencies` (currency_id=5286), Uruguay's `default_currency_id` updated to 5286.
  Added `UYU: 0.023` to `_USD_CONVERSION_RATES` in `salary_standardization.py`.
  Registered `SOURCE_HOME_COUNTRY[""gallito_uy""] = ""UY""`.
  Verified locally: 20 discovered, 5 parsed, normalized, persisted to Postgres (Session 121, 5 inserted, 0 failed,
  batch validation PASSED). GitHub Actions CI run 43924056179: 100% SUCCESS � 50 inserted, 0 failed, 50 rows
  exported to Hugging Face. LIVE and enabled in scheduled CI matrix.












- **`jobnet_mm`** (Myanmar, www.jobnet.com.mm) � 2026-11-20. Myanmar's premier employment portal.
  Paginates server-rendered listing at `https://www.jobnet.com.mm/jobs?page={page}` (30 jobs/page).
  Detail pages at `/job/{slug}/{numeric_id}` carry Schema.org `JobPosting` JSON-LD with capitalized keys
  (`Title`, `Description`), `hiringOrganization`, `jobLocation` (Yangon/Myanmar), `datePosted`
  (`MM/DD/YYYY HH:MM:SS AM/PM` format), `validThrough`, `employmentType`.
  Non-ASCII characters in URL paths are percent-encoded via `urllib.parse.quote`.
  `json.loads(strict=False)` required for tab characters embedded in `Description` JSON strings.
  Added `SOURCE_HOME_COUNTRY["jobnet_mm"] = "MM"`. Myanmar already in `ref.countries` (country_id=3686),
  MMK already in `ref.currencies` (currency_id=3409). Added `"MMK": 0.00048` to
  `_USD_CONVERSION_RATES` in `salary_standardization.py`.
  Verified locally: 30 discovered, 5 parsed, Session 122, 5 inserted, 0 failed, batch validation PASSED.
  GitHub Actions CI run 44611231120: 30 inserted, 0 failed, 30 rows exported to Hugging Face, PASSED.
  LIVE and enabled in scheduled CI matrix.


- **`emploi_ci`** (C�te d'Ivoire, www.emploi.ci) � 2026-11-20. Ivory Coast's leading employment portal powered by AfricaWork.
  Paginates server-rendered search directories at `https://www.emploi.ci/recherche-jobs-cote-ivoire?page={page}` (25 jobs/page).
  Detail pages at `/offre-emploi-cote-ivoire/{slug}-{numeric_id}` carry Schema.org `JobPosting` JSON-LD with title,
  hiringOrganization, jobLocation (locality, region, C�te d'Ivoire), datePosted (ISO format `YYYY-MM-DDTHH:MM:SS+00:00`),
  validThrough, and employmentType (CDI, CDD, Stage, etc.). Includes regex unescape/repair for description HTML quotes in JSON-LD
  with fallback to HTML `div.job-description`.
  Added `SOURCE_HOME_COUNTRY["emploi_ci"] = "CI"`. C�te d'Ivoire in `ref.countries` (country_id=3060, alpha-2 CI),
  XOF (West African CFA franc) in `ref.currencies` (currency_id=506). Added `"XOF": 0.0016` to
  `_USD_CONVERSION_RATES` in `salary_standardization.py`.
  Verified locally: 25 discovered, 5 parsed, Session 123, 5 inserted, 0 failed, batch validation PASSED.
  GitHub Actions CI run 44613872590: 50 inserted, 0 failed, 50 rows exported to Hugging Face, PASSED.
  LIVE and enabled in scheduled CI matrix.

- **`topjobs_lk`** (Sri Lanka, topjobs.lk) - 2026-11-20. Sri Lanka's long-running classifieds board, and the
  first source for the country that actually resolves to a country: the pre-existing 750 `ikman_lk` rows all
  carried a NULL country because `ref.countries` had no `LK` row at all.
  The 2026-10-04 probe recorded an SSLError and reached nothing; re-probed 2026-11-20, the site answers HTTP 200
  to plain requests and robots.txt permits the listing and `/employer/` paths. No key, no registration, no proxy.
  Listing is server-rendered JSP at `/applicant/vacancybyfunctionalarea.jsp?jst=OPEN&pageNo={page}`: 6 open pages
  holding 4,583 unique job codes, with consecutive pages overlapping by exactly one row (de-duplicated on `jc`).
  TRAPS: (1) rows are not anchors - each `<tr>` opens a popup through `onclick="createAlert('rid','ac','jc','ec','id')"`
  and the ad URL must be rebuilt from those four codes; (2) the listing carries opening date, closing date and town
  that the ad page lacks, while the ad page carries the `ad-status` labels the listing lacks; (3) two date formats
  (`Fri Nov 20 2026` on the listing, `03/12/2026` day-first on the ad page); (4) a trailing parenthetical on the title
  is headcount, not part of the title; (5) 239 of 250 ads in the CI run were image-only, stored with
  `description_clean = NULL` and `raw_payload['description_is_image'] = true` rather than dropped; (6) no salary
  field anywhere (1 of 75 sampled bodies mentioned pay), so LKR/monthly state the home market, not an amount.
  A capped run always takes the newest 120 rows and fills the rest of its budget from a tail window that advances
  one window-width per day, so the older 4.5k ads are covered over successive runs instead of re-reading page 1.
  Seeded `LK`/`LKA` (country_id 5634) with `LKR` (currency_id 5375) and 25 Sri Lankan cities; registered
  `SOURCE_HOME_COUNTRY["topjobs_lk"] = "LK"` and `SOURCE_HOME_COUNTRY["ikman_lk"] = "LK"`.
  Added `"LKR": 0.00300818` to `_USD_CONVERSION_RATES` in `salary_standardization.py` (19 Nov 2026, 1 USD = 332.43 LKR).
  Verified locally: 60 inserted, 0 failed, 60/60 resolved to LK, batch validation PASSED.
  GitHub Actions CI run 44623966782: 250 fetched, 250 inserted, 0 failed, 8 with body text / 239 image-only,
  rows exported to Hugging Face, PASSED. LIVE and enabled in scheduled CI matrix.

- **`emploi_cd`** (DR Congo, emploi.cd) - 2026-11-20. The AfricaWork portal for the Democratic Republic of
  the Congo, the same platform as `emploi_ci`, and the country had no coverage at all: `ref.countries` had
  no `CD` row and `ref.currencies` no `CDF` row, so any DRC posting would have carried a NULL country.
  The 2026-10-04 probe recorded HTTP 403 behind a Cloudflare challenge and reached nothing; re-probed
  2026-11-20, the site answers HTTP 200 to plain requests and robots.txt permits the search and ad paths
  (`Crawl-delay: 10`, honoured between every request). No key, no registration, no proxy.
  Discovery is the server-rendered search directory `/recherche-jobs-congo-rdc?page={page}` (page 1 takes no
  query string): 90 offers over 4 pages (24/25/25/15 ad links), 89 unique ad URLs, no page overlap, and the
  page after the last one returns HTTP 200 with zero links, which is the stop signal.
  TRAPS: (1) ad URLs are `/offre-emploi-rdc-republique-democratique-congo/{slug}` and some slugs carry no
  trailing numeric id, so the URL is only the discovery key - the canonical id is JSON-LD `identifier.value`;
  (2) some `description` values embed unescaped double quotes from inline HTML (`<p align="left">`), the same
  defect `emploi_ci` repairs - the block is re-parsed with the description field dropped and the text is read
  from `div.job-description`; (3) `employmentType` is frequently the multi-value
  `CDI - CDD - Interim - Freelance`, which maps to no code rather than one guess (56 of 89 stored rows carry
  no employment type for this reason); (4) `jobLocation.address.addressCountry` is the boilerplate
  `RDC - Republique Democratique du Congo` on every ad, normalized to the seeded country name rather than
  used as a per-ad country signal; (5) `baseSalary` was absent on every sampled ad, so `salary_disclosed` is
  false and CDF/monthly state the home market, not an amount.
  A capped run always takes the newest `fresh_rows` rows and fills the rest of its budget from a tail window
  that advances one window-width per day, so the whole board is covered over successive runs.
  Seeded `CD`/`COD` (country_id 5737) with `CDF` (currency_id 5465) and 31 DRC cities; registered
  `SOURCE_HOME_COUNTRY["emploi_cd"] = "CD"`.
  Added `"CDF": 0.00043257` to `_USD_CONVERSION_RATES` in `salary_standardization.py`
  (19 Nov 2026, 1 USD = 2,311.79 CDF).
  Verified locally: 89 fetched, 89 parsed, 79 inserted + 10 unchanged on an immediate re-run, 0 failed,
  89/89 resolved to CD.
  GitHub Actions CI run 44632202307: 89 fetched, 89 inserted, 0 failed, rows exported to Hugging Face, PASSED.
  LIVE and enabled in scheduled CI matrix.

- **`emploibenin_com`** (Benin, emploibenin.com) - 2026-11-20. The AfricaWork portal for Benin, the same platform as `emploi_ci` and `emploi_cd`, and the country had no coverage at all: `ref.countries` had no `BJ` row and no Benin cities, so any posting would have carried a NULL country.
  The 2026-10-04 probe recorded HTTP 403 behind a Cloudflare challenge and reached nothing; re-probed 2026-11-20, the site answers HTTP 200 to plain requests and robots.txt permits the search and ad paths (`Crawl-delay: 10`, honoured between every request). No key, no registration, no proxy.
  Discovery is the server-rendered search directory `/recherche-jobs-benin?page={page}` (page 1 takes no query string): 209 offers over 9 pages (25 x 8 plus a final page of 9), no page overlap, and the page after the last one returns HTTP 200 with zero links, which is the stop signal.
  TRAPS: (1) ad URLs are `/offre-emploi-benin/{slug}` and some slugs carry no trailing numeric id, so the URL is only the discovery key - the canonical id is JSON-LD `identifier.value`; (2) some `description` values embed unescaped double quotes from inline HTML (`<p align="left">`), the same defect `emploi_ci` and `emploi_cd` repair - the block is re-parsed with the description field dropped and the text is read from `div.job-description`; (3) `employmentType` is frequently multi-value (`Freelance - Temps partiel`, `CDI - Freelance`), which maps to no code rather than one guess (raw value kept in `raw_payload`); (4) `jobLocation.address.addressCountry` is the clean label `Benin` on every ad, including ads whose locality is Paris or Poitiers, so the country is normalized and city matching is what puts a French ad in `FR`; (5) `jobLocation.address.addressRegion` is NOT a region but the list of cities the ad is open to (`Abomey - Abomey-Calavi - Cotonou`), so it is used for remote detection only and never stored as a place; (6) `En Ligne` (online) is the locality for work-from-anywhere ads and is mapped to remote; (7) `baseSalary` was absent on every sampled ad, so `salary_disclosed` is false and XOF/monthly state the home market, not an amount.
  A capped run always takes the newest `fresh_rows` rows and fills the rest of its budget from a tail window that advances one window-width per day, so the whole board is covered over successive runs.
  Seeded `BJ`/`BEN` (country_id 5841) with `XOF` (currency_id 506, already present) and 25 Benin cities; also added Poitiers (FR) because the board advertises on-site roles in France. Registered `SOURCE_HOME_COUNTRY["emploibenin_com"] = "BJ"`.
  Verified locally: 20 fetched, 20 parsed, 20 inserted, 0 failed, 1 updated on an immediate re-run (an `En Ligne` ad reclassified as remote); 18/20 rows resolved to BJ, the two Paris ads resolved to FR, no salary invented, all 20 descriptions present.
  GitHub Actions CI run 44662056423: 120 fetched, 120 inserted, 0 failed, rows exported to Hugging Face, PASSED. The shard resolved 118 rows to BJ and 2 to FR; one Poitiers ad landed on BJ because that run restored the HF state snapshot published before the Poitiers seed. The snapshot is now republished with all 25 Benin cities plus Poitiers, so later runs resolve it to FR.
  LIVE and enabled in scheduled CI matrix.

- **`emploi_cm`** (Cameroon, emploi.cm) - 2026-11-20. The AfricaWork portal for Cameroon, the same platform as `emploi_ci`, `emploi_cd` and `emploibenin_com`. Cameroon had no `ref.countries` row at all before this, so the two already-registered Cameroonian boards (`minajobs`, `fne_cm`, 328 rows) carry a NULL country; seeding CM unblocks them for future runs.
  The 2026-10-04 probe recorded HTTP 403 behind a Cloudflare challenge and reached nothing; re-probed 2026-11-20, the site answers HTTP 200 to plain requests and robots.txt permits the search and ad paths (`Crawl-delay: 10`, honoured between every request). No key, no registration, no proxy.
  Discovery is the server-rendered search directory `/recherche-jobs-cameroun?page={page}` (page 1 takes no query string): 418 unique offers over 17 pages (25 x 16 plus a final page of 19; 419 links, one URL repeating), and the page after the last one returns HTTP 200 with zero links, which is the stop signal.
  TRAPS: (1) ad URLs are `/offre-emploi-cameroun/{slug}`; every sampled slug ends in the numeric ad id, but the URL is still only the discovery key - the canonical id is JSON-LD `identifier.value`; (2) some `description` values embed unescaped double quotes from inline HTML (`<p align="left">`), the same defect `emploi_ci`/`emploi_cd` repair - the block is re-parsed with the description field dropped and the text is read from `div.job-description`; (3) `employmentType` is frequently multi-value (`CDI - CDD - Interim - Freelance`), which maps to no code rather than one guess (raw value kept in `raw_payload`); (4) `jobLocation.address.addressCountry` is the French label `Cameroun`, which is not a `ref.countries` name, so it is normalized; city matching runs first, which is what keeps the Djibouti expatriation ad on `DJ`; (5) `jobLocation.address.addressRegion` is NOT a region but the list of cities the ad is open to (`Douala - Yaounde`), so it is used for remote detection only and never stored as a place; (6) some `addressLocality` values are the same city list (`Douala Yaounde Bafoussam Garoua Maroua`) or just `Cameroun`, and both are dropped rather than guessed into one city; (7) `baseSalary` was absent on every sampled ad, so `salary_disclosed` is false and XAF/monthly state the home market, not an amount.
  A capped run always takes the newest `fresh_rows` rows and fills the rest of its budget from a tail window that advances one window-width per day, so the whole board is covered over successive runs.
  Seeded `CM`/`CMR` (default currency XAF, already present) and 25 Cameroon cities; also `DJ`/`DJI` with the new DJF currency and Djibouti city for the measured expatriation ad. Registered `SOURCE_HOME_COUNTRY["emploi_cm"] = "CM"`.
  Verified locally: 20 fetched, 20 parsed, 20 inserted, 0 failed; 19 rows resolved to CM and the Djibouti ad to DJ, no salary invented, all 20 descriptions present. An immediate re-run updated 3 and left 17 unchanged. The location fixes were measured on the live board: country-label and multi-city localities are dropped, so a five-city ad stores `Cameroon` rather than an invented city.
  GitHub Actions CI run 44670844960: 120 fetched, 120 inserted, 0 failed, rows exported to Hugging Face, PASSED.
  LIVE and enabled in scheduled CI matrix.
- **`emploi_ma`** (Morocco, emploi.ma) - 2026-11-20. Morocco's AfricaWork portal, the same platform as `emploi_ci`, `emploi_cd`, `emploibenin_com` and `emploi_cm`. Morocco already had one source (`rekrute_com`, 90 rows) but no cities in `ref.cities`, so every Moroccan ad folded onto a single country-level row.
  The whole domain sits behind a Cloudflare managed challenge: plain `requests` and `curl_cffi` (chrome/chrome124/safari17_0) get HTTP 403 on home, search, sitemap, rss and api; a real browser clears it from a residential IP in about 8 seconds. This is therefore a BROWSER source (`scripts/run_browser_scraper.py`, SeleniumBase UC mode, headless), not a bespoke HTTP client. robots.txt (HTTP 200 to plain requests) allows `/` for `*` with no Crawl-delay; the challenge is a bot guard, not a robots restriction. No key, no registration, no proxy.
  Discovery is the server-rendered search directory `/recherche-jobs-maroc?page={page}` (page 1 takes no query string): 25 ads per page, pager through page 26. The 120-row cap (`EMPLOI_MA_MAX_JOBS_PER_RUN`) over 6 listing pages is the normal mode.
  TRAPS: (1) ad URLs are `/offre-emploi-maroc/<slug>-<id>` and the trailing id is the stable `source_job_id`; (2) every ad publishes a Schema.org `JobPosting`, but some blocks carry unescaped double quotes from inline HTML (`data-olk-copy-source="MessageBody"`) that no `strict=False` can parse - `json_ld_job_posting` now repairs them by re-escaping only the `description` string, which keeps the well-formed company/location/date fields (before this the block was discarded and the employer was lost on 4/20 measured ads); (3) `addressCountry` is the French label `Maroc`, not a `ref.countries` name, so `SOURCE_HOME_COUNTRY["emploi_ma"] = "MA"` keeps every ad on Morocco while city matching runs first; (4) the origin intermittently answers 502/503/504 with a Cloudflare "Gateway time-out" page that has an `h1` and text, so it passed the rendered check and was stored as a 60-word job description - the new `error_markers` config now makes that a per-ad fetch failure instead of content; (5) `baseSalary` was absent on every sampled ad, so no amount is invented: `salary_disclosed` is false and MAD/monthly state the market.
  Seeded 30 Moroccan cities and renamed `ref.locations` 715 (country-level MA, `city_id/region_id NULL`, `remote_country`) from the leftover label `Casablanca` to `Morocco`; both rekrute_com and emploi_ma fall back to it. Registered `ref.sources` `source_id=2307`.
  Verified locally: 20 fetched, 20 parsed, 20 cleaned, 20 with bodies (41-214 words), 0 failed, all 20 rows resolved to MA, company present on 16/20 ("N.C." is the site's own placeholder), 0 salary rows invented. An immediate re-run left 16 unchanged and updated 4 (the JSON-LD repair recovering their employers). Earlier origin 504 rows (5) were purged before the fix and re-fetched cleanly.
  GitHub Actions CI run 44683774390 (browser group, commit 8d44702): the runner's datacenter IP was served the `Just a moment...` challenge, the listing never exposed its ad links within the 60 s wait, and `discover_detail_paths` raised `BrowserChallengeError` with 0 records. The identical headless UC config parses the board from a residential IP, so this is IP reputation, not the config. Kept BUILT (Disabled in CI) with its site config so it runs locally and can be re-enabled when the block lifts.

- **`empleate_es`** (Spain, empleate.gob.es) - 2026-11-20. Empléate is SEPE's own public employment portal, so it is a government source rather than a commercial board; it is not Spain's first source (the `trabajos_es` board predates it), but it is the largest single official Spanish dataset added so far. No key, no registration, no proxy.
  The 2026-10-04 probe recorded a `CertificateVerifyError` and reached nothing. Re-probed 2026-11-20 the host serves a valid chain to Windows Schannel, but its TLS handshake omits the intermediate certificate, so every OpenSSL-based client (`requests`, `curl_cffi`, `openssl`) fails `unable to get local issuer certificate`; the leaf is issued by `Entrust OV TLS Issuing RSA CA 2` under the Sectigo `Public Server Authentication Root R46` that `certifi` already ships and Schannel succeeds only because the OS had cached the intermediate. The missing intermediate was fetched from the leaf's own AIA URL, verified with `openssl verify -CAfile <certifi> -untrusted <intermediate> <leaf>` -> `OK`, shipped with the scraper under `certs/` (a `.crt`, because `*.pem` is gitignored repo-wide for private keys), and appended to a copy of `certifi`'s roots; certificate verification therefore stays **on** (no `verify=False`). The intermediate is valid until 2027-12-10; if the issuer rotates the run fails loudly with the same error rather than degrading.
  robots.txt (`/empleate/robots.txt`) is `User-agent: *` / `Allow: /` with no `Crawl-delay`; only the logged-in employer/candidate areas are disallowed and this scraper touches none of them.
  Discovery and content are the SAME request: the AngularJS front end reads postings from a public Solr endpoint `/empleate/open/offersearch/selectBuscador?q.op=AND&q=*&wt=json&fq=checkVisible:true&rows=100&start=N&sort=fechaCreacion desc,id desc`, which returns the whole posting (title, employer, full description, province, locality, contract type, salary bounds) inside the listing document, so one request per 100 ads covers discovery and content and there is no per-ad detail stage (the SPA's `open/offer/load/<id>` adds only display formatting).
  Measured 2026-11-20: 26,073 visible ads; `rows` is silently capped at 100 server-side (`rows=200` returns 100); `start` pages to the very end (`start=26072` returned the final document). The default order is relevance, so `sort` is mandatory, and `fechaCreacion desc` alone is NOT deterministic because dozens of ads share one second in the nightly SNE batch - the `id desc` tie-breaker was measured to give stable, non-overlapping page boundaries.
  Freshness: 760 new ads/24h and 3,636/7d, almost all in one nightly batch. The newest ~12,000 documents are that batch and carry no `creador`/`experienciaF`/`horario` (measured at `start=12000`: 43% `creador`, 23% `experienciaF`, 37% `horario`), so the budget defaults to 1,000 with `fresh_rows=800` (above the daily volume, so the batch is covered) and the archive tail rotates one window-width per hour across the four scheduled runs. A pinned `start_offset` is an ABSOLUTE corpus offset (page-aligned, pushed past the fresh region) so a manual or test run is reproducible.
  TRAPS/MAPPINGS: (1) contract type comes from the portal's own `open/master/contracttypes` (0 unspecified, 1 ContractToHire, 2 Contract, 3 Temporary, 4 SelfEmployed, 5 Internship, 6 Apprenticeship) combined with `jornada` from `open/master/daytypes` (1 COMPLETA, 2 PARCIAL, 3 INDIFERENTE, 4 FLEXIBLE); (2) `modality` (facet: 0 No informado 24091, 1 Presencial 1885, 2/3 remote, 4 Mixto 83) treats 0 as on-site, because it is the portal default, not a claim of remote work; (3) `salarioMin`/`salarioMax` are Spanish-formatted strings (`21,000`, `16261,86`) and `0` - with `verSalarioMin/Max="0"` - means missing, not zero; the offer page renders `Brutos/año` while the SPA's JSON-LD says `unitText MONTH`, so amounts are stored yearly EUR following the visible label and both the raw strings and the inconsistency are recorded in `raw_payload`; (4) location is `<ciudadF>; <provinciaF>; <ISO2>` - 2,478 distinct municipalities, of which only Madrid and Barcelona collide with a seeded city and both are Spanish - and `paisF` maps `ESPAÑA`->ES plus 11 foreign labels (`HOLANDA`->NL, `FRANCIA`->FR, `ANDORRA`->AD, ...).
  Scope added for this source: an Andorra `ref.countries` row (`AD`/`AND`, EUR), 52 Spanish provinces as `ref.regions` (byte-identical to the portal's `provinciaF` facet values, because the resolver matches `region_name` exactly - hence uppercase `A CORUÑA`, `ILLES BALEARS`, `STA.CRUZ DE TENERIFE`), and `SOURCE_HOME_COUNTRY["empleate_es"] = "ES"`. Registered `ref.sources` `source_id=2324`, `trust_score 0.90` like the other government portals (`jobbank`, `govt_portal`).
  Verified locally: 250 fetched, 250 parsed, 250 inserted, 0 failed across 3 pages; an archive run at `start-offset 12000` added 150 more with 100 unchanged (page 0 is re-read and deduped by content hash, not duplicated). All 400 rows resolved to ES, 0 NULL country, 0 global-remote fallback, 47 resolved locations (210 `region_exact`, 49 `city_exact`, 1 `country_exact` aliases), EUR/yearly salaries on all rows, 30 employers, posting dates 2026-10-02..2026-11-20.
  GitHub Actions CI run 44718454947: 1,000 fetched, 1,000 inserted, 0 failed, rows exported to Hugging Face, PASSED; every resolved location ends in ES (445 distinct locations plus one country-level ES).
  LIVE and enabled in scheduled CI matrix.

- **`chiletrabajos_cl`** (Chile, chiletrabajos.cl) - 2026-11-20. Chiletrabajos is one of Chile's large generalist boards - a commercial board, not a government portal (the state board `bne_cl` is already built). No key, no registration, no proxy, and no browser. Its robots.txt default group allows the whole site, disallowing only `/partners/` and `/ofertasmuchomas` (neither touched) and advertising its sitemap; a separate `User-agent: Scrapy,proximic / Disallow: /` block is a targeted bot ban and neither token is sent; no `Crawl-delay` is advertised, so a polite one-second gap is kept anyway.
  Reachability: the domain resolves worldwide (US/Canada/Brazil/Germany probes get HTTP 200 from the same address) but TCP 80/443 times out from the Bangladesh build network, so the parser was written against the site's own archived markup (2026-05..2026-11) and verified end-to-end in CI (GitHub Actions, United States).
  Discovery is the advertised sitemap, a single `<urlset>` of `/trabajo/<slug>-<id>` URLs in newest-first order: 34,473 entries on 2026-11-20 (up from 32,993 measured 2026-10-09). A `<sitemapindex>`, or a root that is not `<urlset>`, raises a clear error instead of returning nothing.
  Content is one request per ad. Every `/trabajo/` page carries a Schema.org `JobPosting` JSON-LD block alongside a `BreadcrumbList` and a related-ads `ItemList`; the extractor walks `@graph` too. TRAPS/MAPPINGS: (1) `baseSalary.value` has a CAPITALISED `Value` key (`"1570000"` or an int) and `0` means "not published" - stored as no salary, never zero pesos; (2) `datePosted` is `"YYYY-MM-DD HH:MM:SS"` (space, not `T`) and `validThrough` is ISO-8601; (3) `employmentType` is one code or a comma-joined pair (`"PART_TIME, FULL_TIME"`); a pair is two different codes, so it is stored as `None` with the raw value kept rather than guessing one; (4) `jobLocation.address.addressRegion` is the ISO 3166-2:CL two-letter code (`AT`/`AN`/`LL`/`LI`/`RM`/`BI` measured), not a name, so it is mapped onto the full seeded region name.
  Capped runs stay useful in both directions: the newest 120 `fresh_rows` entries are always taken, and the rest of the budget (default 500) comes from a tail window whose start advances one budget-width per calendar day (`start_offset` pins it), so older ads are covered over successive runs instead of the same first page being re-read forever. A failed ad page is recorded and skipped rather than turned into a half-record, because the sitemap carries no fallback title or employer.
  Scope added for this source: Chile's 16 regions in `ref.regions` (with their `CL-XX` codes and the exact full names the parser maps to - byte-identical, because the resolver matches `region_name` exactly), 58 comunas from the board's own city list in `ref.cities`, and `SOURCE_HOME_COUNTRY["chiletrabajos_cl"] = "CL"` so an ad with an incomplete address still lands in Chile instead of the global-remote row. Registered `ref.sources` `source_id=2341`, `trust_score 0.70`.
  GitHub Actions CI run 44725446124 (api group, commit 7e2ae8c): 34,473 sitemap entries, 500 selected, 500 ad pages fetched, 0 fetch failures, 500 parsed, 500 cleaned, batch validation PASSED, 500 inserted, 0 updated, 0 failed; exported to HF as `shards/source=chiletrabajos_cl/dt=2026-11-20/part-20261120T112301Z.parquet` (522.2 KiB, 500 rows). All 500 rows resolved to CL/Chile (0 NULL country, 0 global-remote fallback), 225 at city level (37 distinct cities) and the rest at region/country level, 38 distinct location strings across all 16 regions; 126 rows disclosed a CLP/monthly salary, 23 flagged `Remote (Country-restricted)` from `jobLocationType: TELECOMMUTE`, 327 distinct employers, `data_quality_score` 0.65-0.95, posting dates 2026-09-10..2026-11-20.
  LIVE and enabled in scheduled CI matrix.

- **`maukerja_my`** (Malaysia, maukerja.my) - 2026-11-20. MauKerja is AJobThing's large generalist Malaysian board - a commercial board, not a government portal - and Malaysia's first built source (the other two slots in the workbook are jobstreet.com.my, a Cloudflare login wall, and hiredly.com, a disabled build). No key, no registration, no proxy, and no browser.
  Discovery is the board's ADVERTISED sitemap chain, not its listing page: `/jobsearch/all-jobs` sits behind a Cloudflare interstitial (HTTP 403 "Just a moment..."), so it is not scraped. `/sitemap.xml` (a sitemapindex) points at `/mk_job.xml` (another index) which points at `/mk_job1.xml`, a single `<urlset>` of 46,652 `/job/<id>-<slug>` ad URLs in newest-first order (measured 2026-11-20, ~9.0 MB, top lastmod 2026-11-20, bottom 2020-09-04). The walk follows only children whose file name matches `mk_job*.xml`, so it finds the job sitemap while `mk_company_job*.xml` (company-scoped listings) and `mk_jobsearch*.xml` are skipped, and a future `mk_job2.xml` is picked up automatically. A `<sitemapindex>` root where a `<urlset>` is expected (or vice versa) raises a clear error rather than returning nothing.
  Content is one request per ad. Every `/job/` page carries a Schema.org `JobPosting` JSON-LD block alongside a `BreadcrumbList`; the extractor walks `@graph` too. TRAPS/MAPPINGS: (1) `identifier` is a `PropertyValue` whose `value` is the 10-char ad id (matching the URL); (2) `baseSalary.value` is a `QuantitativeValue` with `value`/`minValue`/`maxValue` and `unitText: MONTH`, and an all-zero value means "not published" - stored as no salary, never zero ringgit; `salaryCurrency` is MYR; (3) `employmentType` is a list of Schema.org codes and is frequently multi-value at the code level (`["FULL_TIME","PART_TIME"]`), which maps to no code rather than one guess (raw value kept in `raw_payload`); (4) `datePosted`/`validThrough` are ISO-8601 with a literal `Z`, and older ads carry a far-future `validThrough` (e.g. 2119) as a "never expires" sentinel, stored as published; (5) `jobLocation.address.addressRegion` is usually a state name but is sometimes the federal-territory form `WP Kuala Lumpur` (normalised to `Kuala Lumpur`) or a bare postal code (rejected), and `addressCountry` is `MY` with the occasional neighbouring `SG`; (6) `jobLocationType` was absent on every ad sampled, so nothing is inferred remote from prose - only an explicit `TELECOMMUTE` sets `remote_country`; (7) roughly one ad in twenty-five returns HTTP 200 with NO `JobPosting` block (stable on retry, not transient), and such an ad is skipped and counted as a failure rather than stored half-empty, because with no block there is no title, employer or body to store.
  Capped runs stay useful in both directions: the newest 120 `fresh_rows` entries are always taken, and the rest of the budget (default 500) comes from a tail window whose start advances one budget-width per calendar day (`start_offset` pins it), so older ads are covered over successive runs instead of the same first page being re-read forever.
  Scope added for this source: 21 more Malaysian cities in `ref.cities` (on top of the 30 seeded with `hiredly`) and `SOURCE_HOME_COUNTRY["maukerja_my"] = "MY"` so an ad with an incomplete address still lands in Malaysia instead of the global-remote row. The board's own few Singapore ads carry their own `SG` segment, so they resolve to Singapore. Registered `ref.sources` `source_id=2358`, `trust_score 0.70`.
  Verified locally: 20 fetched, 20 parsed, 20 inserted, 0 failed; all 20 rows resolved to MY, salaries MYR/monthly, employment types mapped. GitHub Actions CI run 44749107293 (api group, commit 2b0000e): 46,652 sitemap entries, 500 selected, 500 ad pages fetched, 0 fetch failures, 500 parsed, 500 cleaned, batch validation PASSED, 500 inserted, 0 updated, 0 failed; exported to HF as `shards/source=maukerja_my/dt=2026-11-20/part-20261120T141337Z.parquet` (232.0 KiB, 500 rows). 494 rows resolved to MY and 6 to SG, 0 NULL country, 0 global-remote fallback; 437 rows at city level across 22 cities (Kuala Lumpur 186, Shah Alam 55, Petaling Jaya 49, Puchong 36, Seri Kembangan 24, ...); 475 rows disclosed a MYR/monthly salary, 5 flagged `Remote (Country-restricted)` from `jobLocationType: TELECOMMUTE`, `data_quality_score` 0.85-0.95, posting dates 2026-09-21..2026-11-20.
  LIVE and enabled in scheduled CI matrix.

- **`jobup_ch`** (Switzerland, jobup.ch) - 2026-11-20. Jobup is JobCloud AG's French-Swiss brand, a DISTINCT inventory from the jobs_ch sibling this repo already runs (8 of 15 sampled jobup.ch ad UUIDs resolved on none of the en/fr/de jobs.ch detail paths, all 404), so it is a new source rather than a duplicate. No key, no registration, no proxy and no browser.
  Discovery is the board's ADVERTISED sitemap index, not its listing page: `/sitemaps/jobup/en/sitemap.xml` (a `<sitemapindex>`) points at `/sitemaps/jobup/en/job/sitemap.job-en.xml.gz`, a single gzip `<urlset>` of 30,590 `/en/jobs/detail/<uuid>/` ad URLs. The file is written OLDEST-first, so the client parses each `lastmod` and sorts descending to keep the newest ads - that is what makes `fresh_rows` meaningful. A `<sitemapindex>` where a `<urlset>` is expected (or vice versa) raises a clear error rather than returning nothing. robots.txt (HTTP 200) allows every path this scraper uses.
  Content is one request per ad. Every detail page carries a Schema.org `JobPosting` JSON-LD block alongside a `BreadcrumbList`; the extractor reads `@graph` too. TRAPS/MAPPINGS measured 2026-11-20: (1) `identifier` is a `PropertyValue` whose `value` is the ad UUID (matching the URL path); (2) `employmentType` is either a list of Schema.org codes or free prose - a list holding two DIFFERENT codes (or prose such as "Permanent position") is stored as no employment type rather than one guess, and the raw value is kept in `raw_payload`; (3) `baseSalary` is a CHF `MonetaryAmount` whose `value` is a `QuantitativeValue` with `minValue`/`maxValue` and `unitText: YEAR`, and an EMPTY `QuantitativeValue` is UNDISCLOSED, never zero francs; (4) `datePosted`/`validThrough` are ISO-8601; (5) `jobLocation.address.addressLocality` is often EMPTY and `addressRegion` often holds a TOWN instead of a canton, so a region slot that is not one of the 26 cantons is REUSED as the locality (a seeded town then matches a `ref.cities` row, while a genuine canton stays a region; an unseeded town honestly falls back to country level), with trailing parentheticals, a "<town> - <street>" tail and a trailing canton code stripped; (6) `applicantLocationRequirements` is a Country eligibility statement ("Country: Switzerland"), NOT a remote signal, so only `jobLocationType: TELECOMMUTE` sets remote (`remote_country`).
  Capped runs stay useful: the newest `fresh_rows` ads are always taken and the rest of the budget (default 500) comes from a tail window whose start advances one budget-width per calendar day (`start_offset` pins it), so older ads are covered over successive runs instead of the same first page being re-read forever. A failed ad page is recorded and skipped rather than turned into a half-record.
  Scope added for this source: the 26 Swiss cantons in `ref.regions` (recorded with their official `CH-XX` `region_code`) and 99 Swiss cities in `ref.cities` (alongside the pre-existing "Zurich" row); `SOURCE_HOME_COUNTRY["jobup_ch"] = "CH"` so an ad with an incomplete address still lands in Switzerland; and CHF in the `_USD_CONVERSION_RATES` table (1 CHF = 1.1856250 USD, 20 Nov 2026) because jobup.ch is the first source that pays in CHF. Registered `ref.sources` `source_id=2375`, `trust_score 0.70`.
  Verified locally: 80 ad pages fetched, 80 parsed, 80 cleaned, batch validation PASSED, 0 failed; all 80 rows resolved to CH, 0 NULL country, 0 global-remote fallback, 34 at city level, 33 with a disclosed CHF/yearly salary. GitHub Actions CI run 44761231830 (api group, commit a0d2bb5): 30,590 sitemap entries, 500 selected, 497 ad pages fetched (3 fetch failures), 497 parsed, 497 cleaned, batch validation PASSED, 497 inserted, 0 updated, 0 failed; exported to HF as `shards/source=jobup_ch/dt=2026-11-20/part-20261120T152726Z.parquet` (685.9 KiB, 497 rows). All 497 rows resolved to CH/Switzerland (0 NULL country, 0 global-remote fallback), 270 at city level (Lausanne 55, Bern 41, Geneve 31, Zurich 29, Luzern 19, ...); 132 rows disclosed a CHF/yearly salary and all 132 normalised to USD (0 NULL among disclosed); employment types Full-time 61, Temporary 54, Part-time 28, Apprenticeship 11 and none 343; every row carries a description.
  LIVE and enabled in scheduled CI matrix.

- **`rwandajob_com`** (Rwanda, rwandajob.com) - 2026-11-20. Rwandajob is the AfricaWork portal for Rwanda, the same Drupal/Emploi network the repo already runs for Cote d'Ivoire (`emploi_ci`), DR Congo (`emploi_cd`), Benin (`emploibenin_com`) and Cameroon (`emploi_cm`), and a DISTINCT board from the already-built `jobinrwanda` (which publishes no location field and no posting date). No key, no registration, no proxy and no browser.
  Discovery is the server-rendered search directory `/job-vacancies-search-rwanda` (page 1 has no query string; page N is `?page=N`); on 2026-11-20 it held 116 offers over 5 pages (25 x 4 plus a final page of 16), pages do not overlap, and a page past the last one returns HTTP 200 with zero ad links, which is the stop signal. Ad URLs are `/job-vacancies-rwanda/<slug>-<id>`; the URL is only the discovery key and the canonical id is the JSON-LD `identifier.value` on the detail page. robots.txt (HTTP 200) allows the search and ad paths and asks for `Crawl-delay: 10`, honoured between any two requests, so a full board costs ~20 minutes and a capped 120-row window is the normal mode.
  Content is one request per ad. Every detail page carries a Schema.org `JobPosting` block (plus a `WebSite` block that is ignored). TRAPS/MAPPINGS measured 2026-11-20: (1) `datePosted` IS the real per-ad posting date - page-5 ads read `2026-09-29` while page-1 ads read `2026-11-20`, and the visible `Published on <dd.mm.yyyy>` line agrees - so it is stored; (2) `employmentType` is often multi-valued (`Permanent contract - Fixed-term contract - Freelance`) and a value with two or more DIFFERENT mapped codes is stored as no employment type rather than one guess, with the raw value kept in `raw_payload`; (3) the same unescaped-quote defect the AfricaWork sister boards have appears in `description` (3 of a 9-ad sample), repaired by dropping only the description field and parsing the rest, then reading the body from `div.job-description`; (4) `jobLocation.address.addressCountry` is the clean label `Rwanda`, but `addressRegion` is NOT a region - it is the `-`-joined list of provinces the ad is open to (`Eastern Province - Kigali Province - ... - International`) - so the region is used for remote detection only and never stored as a place; (5) `baseSalary` was absent on every sampled ad, so no amount is invented and rows carry currency RWF with period monthly.
  Capped runs stay useful: the newest `fresh_rows` ads are always taken and the rest of the budget (default 120) comes from a tail window whose start advances one budget-width per calendar day (`start_offset` pins it), so older ads are covered over successive runs instead of the same first page being re-read forever. A failed ad page is recorded and skipped rather than turned into a half-record.
  Scope added for this source: `SOURCE_HOME_COUNTRY["rwandajob_com"] = "RW"` so a remote ad with no country still lands in Rwanda (the country is already seeded as RW/RWA with default currency RWF, and Kigali is already a `ref.cities` row). Registered `ref.sources` `source_id=2392`, `trust_score 0.70`.
  Verified locally: 20 ad pages fetched, 20 parsed, 20 cleaned, batch validation PASSED, 0 failed. GitHub Actions CI run 44770131474 (api group, commit 99a7a5c): 116 discovered, 116 fetched, 116 parsed, 116 cleaned, batch validation PASSED, 116 inserted, 0 updated, 0 failed; exported to HF as `shards/source=rwandajob_com/dt=2026-11-20/part-20261120T163047Z.parquet` (126.0 KiB, 116 rows). All 116 rows resolved to RW/Rwanda (0 NULL country, 0 flagged `is_global_remote`), 51 at city level (Kigali) and 65 at country level; 68 On-site, 47 Remote (Global) and 1 Remote (Country-restricted) from the board's own locality/region signals; all 116 undisclosed salary in RWF/monthly; employment types Full-time 21, Temporary 19, Internship 5, Freelance 4, Part-time 1 and none 66; every row carries a description and both a posting and a closing date (posting range 2026-09-29 to 2026-11-20).
  LIVE and enabled in scheduled CI matrix.
- **`jobindex_dk`** (Denmark, jobindex.dk) - 2026-11-20. Jobindex is Denmark's largest commercial job board. No key, no registration, no proxy and no browser. The 2026-10-04 sweep recorded "HTTP 403 - bot/login wall on the listing page"; the site now serves plain HTML to a browser user agent.
  robots.txt (HTTP 200) has a generic `User-agent: *` group and NO `Crawl-delay`. It disallows the paged/sorted/filtered search URLs (`page=`, `sort=`, `jobage=`, `archive=`, `subid=`, `supid=`, `companyid=`, `radius=`, `flag=`, `geoareaid=`, `/jobsoegning?*&*&`, `/jobsoegning/*?*&`, `/jobsoegning/kort`, `/jobsoegning/uopfordret`, `/jobsoegning/analyse`), every `/c?` redirect link, and `/jobannonce/korrektur/` and `/jobannonce/embed/`; none of these is fetched. The surfaces this scraper uses - the `/jobsoegning` and `/jobsoegning/<area>` listing pages, the advertised `/sitemap/area.gz`, `/vis-job/<tid>` and `/jobannonce/<tid>/<slug>` - are all allowed, and a courtesy gap (`rate_limit_delay=0.25`) is kept even though no Crawl-delay is published.
  Discovery never walks `?page=` (disallowed): it reads the newest-first `/jobsoegning` page (20 rows) plus a rotating window of the 759 advertised `/jobsoegning/<area>` pages and dedupes by ad id (`tid`). There is no ad sitemap to walk - `googleforjobs.gz` is an EMPTY `<urlset>` (0 `<loc>`, even fetched as Googlebot) and `company.gz`/`salaryindex.gz`/`content.gz` hold company profiles, salary pages and articles, not ads - so the area window is the discovery surface, and its start advances one window-width per calendar day (`start_offset` pins it) so the long tail is covered over successive runs instead of the same first page being re-read forever. The row set is sorted newest-first by `firstdate` then numeric ad id; the newest `fresh_rows` (80) are always taken and the rest of the budget (default 500) comes from the rotating window.
  Content is one request per ad: `/jobannonce/<tid>/<slug>` when the listing snippet exposes the canonical URL (full body in `section.jobtext-jobad__body`), otherwise `/vis-job/<tid>` whose `<link rel="canonical">` is followed when it points at a `/jobannonce/` page. The slug is required (a wrong or missing slug returns HTTP 200 with no body). Measured on 60 sampled ads, 15 (25%) carry a full body (1,708-8,149 chars) and 45 (75%) are employer-paid ads that publish only a ~530-695 char teaser on Jobindex and link out to the employer, whose full text is therefore NOT on this board; a teaser is stored as the description and flagged via `raw_payload["description_source"]="vis_job_teaser"`, and no external employer page is ever fetched. Three body layouts are handled (standard `section.jobtext-jobad__body`; employer custom `div.jobcontent`/`div.jobtext`/`div.job-box` read as prose blocks while skipping the JIX info box, the online-application button, the header title/location and "Ansoeg/Apply/Laes mere" chrome; and the paid teaser). Employment type and remote work are read from the sidebar card (`<dl><dt>Label:</dt><dd>`) or the custom `div.jix-info` (`<p><b>Label:</b> value</p>`); a value that maps to two DIFFERENT codes is stored as no type rather than one guess, and a card value beats body text. An area suffix "... og mulighed for hjemmearbejde" is stripped from the location and treated as hybrid. `closing_date` comes from the listing `apply_deadline` (ISO), then the detail card "Ansoegningsfrist", then `lastdate`.
  Capped runs stay useful: the newest `fresh_rows` ads are always taken and the rest of the budget (default 500) comes from an area-window whose start advances one window-width per calendar day (`start_offset` pins it). A failed ad page is recorded and skipped rather than turned into a half-record.
  Scope added for this source: `SOURCE_HOME_COUNTRY["jobindex_dk"] = "DK"` so an ad with an incomplete address still lands in Denmark. Danish city coverage is deliberately left at COUNTRY level (only `Copenhagen` is a `ref.cities` row and no DK regions are seeded), so rows resolve to DK/Denmark rather than to a city. Salary is DKK/monthly; 7 of 389 rows published a salary and 382 did not, and DKK is not yet in the `_USD_CONVERSION_RATES` table, so those 7 rows keep their DKK amount with NULL `*_usd` columns rather than a guessed conversion. Registered `ref.sources` `source_id=2393`, `trust_score 0.70`.
  Verified locally: dry-run and a 60-ad live quality probe parsed cleanly (all three body layouts, 0 failed). GitHub Actions CI run 44782909941 (api group, commit 9753569): 61 listing pages scraped, 391 ads discovered, 389 of 391 ad pages fetched (2 fetched as HTTP 429 from the runner's datacenter IP after the 3 bounded retries and recorded as fetch failures), 389 parsed, 389 cleaned, batch validation PASSED, 389 inserted, 0 updated, 0 failed; exported to HF as `shards/source=jobindex_dk/dt=2026-11-20/part-20261120T184642Z.parquet` (396.1 KiB, 389 rows). All 389 rows resolved to DK/Denmark (0 NULL country, 0 flagged `is_global_remote`), 0 at city level by design (country-level resolution, see above); 385 rows carry a description; employment types Full-time 71, Part-time 37, Temporary 1 and none 280; remote work On-site 371, Hybrid 12, Remote (Country-restricted) 6; posting dates 2026-10-23..2026-11-20 and a closing date on every row; salary 7 disclosed / 382 undisclosed in DKK/monthly.
  LIVE and enabled in scheduled CI matrix.
- **`vdab_be`** (Belgium, vdab.be) - 2026-11-21. VDAB is Flanders' public employment service and its official vacancy database, a distinct inventory from any commercial Belgian board. No key, no registration, no proxy and no browser.
  robots.txt (HTTP 200) has a generic `User-agent: *` group and NO `Crawl-delay`. It disallows `/vac/`, `/vacatures/`, `/api/vindeenjob/`, `/include/vacature/` and `/*action=*`; the two used `/rest/vindeenjob/v4/` surfaces match none of those rules (the prefix `/vacatures/` does not match `/vindeenjob/vacatures/...`), and neither the disallowed `/api/vindeenjob/` base nor the Angular ad pages are ever fetched. A polite 0.25 s gap is kept anyway.
  Discovery is `POST /rest/vindeenjob/v4/vacatureLight/zoek` with `{"criteria":{"onlineSindsCode":"9000","sorteerVeld":"DATUM"},"pagina":N,"zoekmodus":"C2","paginaGrootte":200}`; it reported 212,800 active ads on 2026-11-21. Rows are re-sorted locally by `eerstePublicatieDatum` desc then id desc, and a capped run always takes the newest 200 plus a tail window that advances one width per calendar day, so successive runs cover the scanned set instead of re-reading the same head.
  Content is one request per ad: `GET /rest/vindeenjob/v4/vacatures/<id>?preview=false`, whose Schema.org `jobPosting` arrives as a JSON string. Every request sends the static `vej-key-monitor` correlation id from the site's own `chunk-CpGZcmxc.js`; it is a public front-end constant, not a credential, and without it the API answers 403 with an empty body.
  Mappings measured on the live payload: description is `functie.omschrijving.plainText` (markdown `jobPosting.description` and the HTML block are fallbacks), so no employer page is fetched; `validThrough` is a real closing date on ~2-6% of ads and None otherwise; no salary field exists anywhere, so rows are EUR/monthly with `salary_disclosed=False` and no amount is invented; employment type is `functie.arbeidscircuit.code`, with ordinary G/GC split full/part by `profiel.dienstregeling.arbeidsDuur` (V/D) and FL/WS/E left None because those codes have no honest `ref.employment_types` equivalent; remote work is a conservative Dutch/French phrase scan defaulting to `on_site` (the payload has no `jobLocationType` and the filter catalogue has no telewerk facet). `apply_url` is the board's own ad page; the employer's `logischeLocatie.webadres` is kept in `raw_payload.external_apply_url` because it is often a campaign redirect.
  Scope added for this source: `SOURCE_HOME_COUNTRY["vdab_be"] = "BE"` so an ad whose place is a bare municipality still lands in Belgium (Belgium is seeded as BE/BEL with default currency EUR). Belgian city coverage stays at COUNTRY level (only Brussels is a `ref.cities` row and no BE regions are seeded), so all rows resolve to the existing BE country-level `ref.locations` row and `city_name` is NULL by design.
  Verified locally: dry-run plus a 60-ad live quality probe parsed cleanly (0 failed), and a 10-ad DB-backed run inserted 10 rows, all BE, 0 NULL country, 0 global-remote, EUR/monthly, 0 empty descriptions. GitHub Actions CI run 44804506553 (api group, commit 21199fc): 40 search pages, 7,980 ads discovered, 500 detail payloads fetched, 500 parsed, 500 cleaned, batch validation PASSED, 500 inserted, 0 updated, 0 unchanged, 0 failed; exported to HF as `shards/source=vdab_be/dt=2026-11-20/part-20261120T194825Z.parquet` (326.6 KiB, 500 rows). All 500 rows resolved to BE/Belgium (0 NULL country, 0 flagged `is_global_remote`, 0 at city level by design); 500 carry a description (average 146 words); salary 500 undisclosed in EUR/monthly; employment types Temporary 347, Full-time 110, none 38, Part-time 5; remote work On-site 499, Hybrid 1; 11 rows carry a closing date; posting dates 2026-11-20..2026-11-20 (the newest-first scan window).
  LIVE and enabled in scheduled CI matrix.

- **`lexpress_mu`** (Mauritius, lexpress-petites-annonces.mu) - 2026-11-21. L'Express is the island's main daily newspaper and its classifieds arm runs a genuine `Emplois` jobs board (mostly employer postings), a distinct inventory from the already-built `myjob` MU API source. No key, no registration, no proxy and no browser.
  The news host `lexpress.mu` only links out; the ads live on the sister host `lexpress-petites-annonces.mu`. robots.txt on BOTH hosts (HTTP 200) is a generic `User-agent: *` group with an EMPTY `Disallow` (allow-all) and no `Crawl-delay`; a polite 0.5 s gap is kept anyway.
  Discovery is the server-rendered category `/c/emplois`, which paginates with `?page={n}` (page 1 is the bare path): 126+ ads across 11+ live pages on 2026-11-21, ~12 ads/page, and ad URLs are `/annonce/<YYYYMMDD>-<digits>` (the whole token is the stable `source_job_id`). Ad links are site-relative.
  Content is one request per ad, and the pages carry NO schema.org JSON-LD and NO employer or salary field. TRAPS: (1) `<title>` and `og:*` are SITE-wide (`L'Express Petites Annonces`) and must never be used as the job title - it comes from `<h1>`; (2) the posting date is French long form (`16 novembre 2026`) and is read with a French month table, because the shared English date parser cannot; (3) the breadcrumb (`Emplois > Full-Time|Part-Time`) and the `Localisation: <place>` line share the exact class `text-sm text-gray-500` and are told apart by the breadcrumb containing `>`; the employment type is the breadcrumb tail, mapped Full-Time/Part-Time/Contract/Temporary/Internship/Freelance to the ref code; (4) salary, when stated, is prose in the body (`Salary Package: MUR 27,000 - MUR 35,000 per month.`): a `MUR`/`Rs` figure is parsed to min/max with the stated period, defaulting to monthly (the Mauritius convention, see `myjob`) and recording that assumption in `raw_payload`; an ad with no figure is stored undisclosed, never as zero; (5) there is no employer field - it is best-effort from the ad's Google-Maps query when present, else a conservative `<Name> is looking/recruiting` body heuristic guarded against pronouns, function words and places (measured false captures `We are ...`, `La compagnie ...`, `Maurice et ...`, `Branded Retail Store is actively ...` and the location `Port Louis` are all rejected, so the board reads mostly `Unknown employer` rather than wrong names), else `Unknown employer`; (6) contact emails are Cloudflare-obfuscated (`data-cfemail`, key = first byte XOR) and the decoded address is recovered for audit; (7) a remote-work phrase (`teletravail`/`remote`/...) is recorded in `raw_payload` but NEVER mapped to a `remote_work_type_code`, because a classifieds line saying `remote` never states how remote.
  Scope: `SOURCE_HOME_COUNTRY["lexpress_mu"] = "MU"` (Mauritius is already seeded as MU/MUS with default currency MUR via `myjob`), so an ad naming only a local place (`Moka`, `Roches Noires`) still lands in Mauritius rather than the global-remote row. Mauritian cities are deliberately left at COUNTRY level: names like `Phoenix` and `Moka` collide with seeded cities elsewhere and `_match_city` treats duplicate names as ambiguous, so every row resolves to the existing country-level MU `ref.locations` row and `city_name` is NULL by design. Registered `ref.sources` `source_id=2425`, `trust_score 0.70`.
  The category also still links expiring/expired ads that now return HTTP 404 (30 of a 120-ad run, 25%), so a capped run records those as fetch failures and persists the rest; this is a property of the board, not a bug, and the batch still validates.
  Verified locally: 48 fetched, 48 parsed, 48 cleaned, batch validation PASSED (0% skip), 0 failed; an immediate re-run left all 48 unchanged. GitHub Actions CI run 44814387287 (html group, commit bafd67d): 120 fetched, 30 fetch failures (all HTTP 404), 90 parsed, 90 cleaned, batch validation PASSED (25.0% skip rate - all fetch failures), 90 inserted, 0 updated, 0 failed; exported to HF as `shards/source=lexpress_mu/dt=2026-11-20/part-20261120T204959Z.parquet` (76.1 KiB, 90 rows). All 90 rows resolved to MU/Mauritius (0 NULL country, 0 flagged `is_global_remote`, 0 at city level by design); all 90 carry a description (average 79 words); employment types Full-time 65, Part-time 10, Freelance 2 and none 13; salary 7 disclosed (MUR/monthly) and 83 undisclosed; remote work unset on all rows (the board never states how remote); 7 distinct employers resolved from the Maps query or the body heuristic and 83 `Unknown employer`; posting dates 2026-02-01..2026-11-16; `data_quality_score` 0.43-0.86.
  LIVE and enabled in scheduled CI matrix.

- **`revolico_cu`** (Cuba, revolico.com) - 2026-11-21. Revolico is Cuba's large general classifieds site, and its Empleos category carries an employers' sub-board, `Ofertas de Empleo`, that is a genuine jobs board: hundreds of employer postings paginated ~100 to a page (the sibling `Busco Empleo` holds job-seekers and is NOT walked). Cuba had ZERO coverage before this source. No key, no registration, no proxy and no browser.
  robots.txt (HTTP 200) is a generic `User-agent: *` group that allows everything except `/checkout/`, `/cdn-cgi/`, `/account`, `/auth` and `/favorites/`, none of which are used; a polite 0.5 s gap is kept anyway. TLS certificate verification stays ON (no `verify=False` anywhere).
  Discovery is the server-rendered Next.js search page `/search?category=empleos_&subcategory=empleos-ofertas-de-empleo`; the subcategory slug ALONE returns an empty page and the numeric category id returns HTTP 500, so BOTH params are required. Pagination is `?page={n}` (page 1 is the bare path), ~100 ads/page, and ad URLs are `/item/<slug>-<id>` with `<id>` the stable `source_job_id`.
  There is NO schema.org JSON-LD and NO separate API: each page embeds its data in `<script id="__NEXT_DATA__">`, and the ads are the `AdType:*` entries of `props.pageProps.__APOLLO_STATE__`; `ProvinceType`/`MunicipalityType` refs are resolved against the same state. Listings carry partial ads (no body), so one detail request is made per ad. TRAPS: (1) there is NO employer field - the ad's `name` is the poster, kept as `poster_name`, and the employer stays `Unknown employer`; (2) there is NO salary field - `price`/`currency` are unreliable (absent on 55 of 102 sampled ads and a placeholder `1` on many of the rest), so no row is treated as a disclosed salary, both are kept in `raw_payload`, and salary is always undisclosed; (3) there is no original posting date, only `updatedOnByUser` (the last bump), whose date is used and flagged in `raw_payload`; (4) a remote-work phrase is recorded in `raw_payload` but NEVER mapped to a `remote_work_type_code`.
  Scope: `currency_iso_code` is the home-market `CUP` (Cuba's first `ref.currencies` row) with NO CUP rate added to `salary_standardization.py`, because nothing is a salary; `SOURCE_HOME_COUNTRY["revolico_cu"] = "CU"` places every ad in Cuba (Cuba's first `ref.countries` row). No Cuban city is seeded, because names like `Florida` collide with seeded cities elsewhere, so every row resolves to the country-level CU `ref.locations` row and `city_name` is NULL by design. Registered `ref.sources` `source_id=2452`, `trust_score 0.70`.
  Verified locally: a 12-ad dry run parsed cleanly and a default 200-ad run inserted 200 rows, 0 failed, batch validation PASSED (all CU, 0 NULL country, CUP/yearly, salary undisclosed on all rows). GitHub Actions CI run 44820045605 (html group, commit 827e644): 200 fetched, 200 parsed, 200 cleaned, batch validation PASSED (0% skip), 200 inserted, 0 updated, 0 failed; exported to HF as `shards/source=revolico_cu/dt=2026-11-20/part-20261120T212935Z.parquet` (104.7 KiB, 200 rows). All 200 rows resolved to CU/Cuba (0 NULL country, 0 flagged `is_global_remote`, 0 at city level by design); 191 carry a description (average 62 words); salary 0 disclosed / 200 undisclosed in CUP/yearly; remote work unset on all 200; `Unknown employer` on all 200 (the board has no employer field); posting dates 2026-08-18..2026-11-20; `data_quality_score` 0.71-1.00.
  LIVE and enabled in scheduled CI matrix.
