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

- **`timesjobs_in`** (India, timesjobs.com) - 2026-11-21. TimesJobs is India's long-running job board (a Times Internet property), and its public search is backed by a keyless JSON API rather than server-rendered HTML. No key, no registration, no proxy and no browser.
  robots.txt on the public site (HTTP 200) is a generic `User-agent: *` group allowing everything except `/timesJobWebApp/`, `/logout.html`, `/AutoLogin.html` and `/times_logout`, none of which are used. The API host `tjapi.timesjobs.com` serves NO readable robots.txt (`/robots.txt` and `/` both return HTTP 502 from its nginx gateway); the project owner reviewed this and approved the source on 2026-11-21, recording the 502 as an observed fact rather than treating it as permission (matching the api.p.hr.ge 404 / cupid.51job.com 400 / api.il.jobmaster.co.il 200 precedent). TLS certificate verification stays ON (no `verify=False` anywhere).
  Discovery is `POST https://tjapi.timesjobs.com/search/api/v1/search/jobs/list` with body `{keyword, location, experience, page, size, jobFunctions, company, industry, functionAreaId, jobFunction}`, returning `{total, page, size, totalPages, jobs}`; the default feed is date-descending by `postDate` and `size` accepts at least 500. No location filter is applied, so the per-city location text survives (a country filter such as `India` collapses every row's location to the bare string "India"). Every listing row is then hydrated by `GET https://tjapi.timesjobs.com/job-api/api/jobs/public/<token>`, where `<token>` is the text after `jobid-` in the listing `jobDetailUrl` (including its trailing `&source=srp`), URL-encoded as a single path segment; the site's own `__PLUS__`/`__SLASH__` escapes resolve to HTTP 200 unchanged.
  TRAPS: (1) salary is effectively hidden - every sampled detail row carried `hideCtcFromCandidate: true` with `minCtc`/`maxCtc` at `-1`, so the cleaner drops non-positive bounds and a positive pair is still mapped when one appears; (2) `employmentType` is usually "Full-time" but occasionally repeats the work mode "On-site", so the cleaner maps recognized employment labels and ignores the work-mode words in that slot, while `jobType` ("On-site") maps to `remote_work_type_code`; (3) the listing `description` is truncated (~220-250 chars) while the detail carries full HTML.
  Scope: `currency_iso_code` is `INR` (every listing row carried `currency: "INR"`), `pay_period` is `yearly` (annual CTC by Indian convention), and `SOURCE_HOME_COUNTRY["timesjobs_in"] = "IN"` keeps an unresolvable row on IN rather than collapsing it onto the global-remote location. Registered `ref.sources` `source_id=2463`, `trust_score 0.70`.
  Verified locally: a 20-row dry run parsed/cleaned cleanly and a default 200-row run inserted 200 rows, 0 failed, batch validation PASSED. GitHub Actions CI run 44875597413 (api group, commit 207c25e): 200 fetched, 200 parsed, 200 cleaned, batch validation PASSED (0% skip), 200 inserted, 0 updated, 0 failed; exported to HF as `shards/source=timesjobs_in/dt=2026-11-21/part-20261121T062956Z.parquet` (395.0 KiB, 200 rows). Country resolution: IN 122, US 35, MY 8, SG 4, AE 3, AR 3, CA 3, FR 2, JP 1 and NL 1, plus 8 rows at the global-remote location (country NULL by design, the ads that name only a remote/unspecified location); 200 carry a description (average 622 words); salary 0 disclosed / 200 undisclosed in INR/yearly; employment `full_time` on all 200; remote work `on_site` on 199 (1 unset); experience present on 187; 26 distinct locations; posting dates 2026-11-19; `data_quality_score` 0.50-0.75.
  LIVE and enabled in scheduled CI matrix.

- **`zangia_mn`** (Mongolia, zangia.mn) - 2026-11-21. Zangia is Mongolia's long-running job board. Its public site is a Next.js SPA whose HTML renders empty to a plain client (the 2026-10-04 sweep's "(self.__next_f); unsupported config-only" verdict), but the listing and every detail are plain keyless JSON GETs on `hr-api.zangia.mn` - no key, no registration, no proxy, no browser, and TLS verification stays ON.
  There is NO readable robots.txt anywhere on the property: `zangia.mn`, `www.zangia.mn`, `hr-api.zangia.mn` and `new-api.zangia.mn` all return HTTP 404, i.e. no policy file exists. The owner reviewed this and approved building on 2026-11-21, recording the 404s as an observed fact and relying on RFC 9309's allow-all posture for an absent robots.txt (the same posture as the api.p.hr.ge 404, cupid.51job.com 400, api.il.jobmaster.co.il 200 and tjapi.timesjobs.com 502 precedents).
  Discovery is `GET https://hr-api.zangia.mn/api/job/public/list/search` with `{data,page,limit,total,totalPages}` (default 90/page, `limit` accepts >=500, newest-first by `sortTime`; 6,099 rows at scoping), and every listing row is hydrated by `GET https://hr-api.zangia.mn/api/job/public/detail/<code>` (the 200 envelope is `{data,message}`; a bad code is a 404 "ES Job not found"). The listing row's `code` is the URL slug (public page `https://zangia.mn/job/<code>`) and the stable `source_job_id`.
  TRAPS: (1) salary is always stated as `salary{id,phrase,min,max}` in whole MNT quoted monthly - min/max are reversed on some rows (swap them), and non-positive bounds are dropped rather than read as "negotiable"; (2) `timetype.name_en` is "Full-time" or "Shift" - Shift is a work schedule, not an employment type, so it is left unmapped instead of being forced into contract/part-time; (3) `isFeatured` is a featured-until timestamp, NOT a posting date (the posting time is `sortTime`/`time`, epoch seconds); (4) `company.logo` is an opaque code with no resolvable CDN URL, so `company_logo_url` is None rather than a dead link; (5) `api.zangia.mn` is a partner gateway that demands an app code/token and is NOT needed.
  Scope: `currency_iso_code` is `MNT`, `pay_period` is `monthly`, and `SOURCE_HOME_COUNTRY["zangia_mn"]="MN"` keeps an unresolvable row on MN. Descriptions fold the detail's `description`, `requirements` and `additional` HTML into one cleaned text; `skills` keep the board's English names.
  Verified locally: a 20-row dry run parsed/cleaned cleanly and a default 200-row run inserted 200 rows, 0 failed, batch validation PASSED. GitHub Actions CI run 44880089306 (`scrape_api.yml -f only=zangia_mn`) reproduced it: 200 fetched/parsed/cleaned/inserted, 0 failed, validation PASSED; its inline HF export hit the repo's 128-commits/hour limit (HTTP 429) and the shard was uploaded on retry as `shards/source=zangia_mn/dt=2026-11-21/part-20261121T075855Z.parquet` (191.7 KiB, 200 rows). All 200 rows resolve to Mongolia (the 16 distinct district labels are not in the curated city seed, so ref.locations collapses them to the country-level row while core.location_aliases keeps each string), 195 disclose a monthly MNT salary (1.2M-7.5M), 125 companies, posted 2026-10-22..2026-11-21.
  LIVE and enabled in scheduled CI matrix.

- **`anpe_bf`** (Burkina Faso, www.anpe.gov.bf) - 2026-11-21. Burkina Faso's national employment agency (ANPE, rebranded "Agence Burkinabe Pour l'Emploi - Faso Tonlo Zi") publishes its recruitment notices on `www.anpe.gov.bf`. The old `anpe.bf` / `www.anpe.bf` domain the 2026-10-04 sweep recorded no longer resolves (both NXDOMAIN); `www.anpe.gov.bf` (196.13.207.92, Apache/2.4.58) is a WordPress install, and its public REST API is keyless -- no key, no registration, no proxy, no browser, TLS verification stays ON.
  robots.txt (HTTP 200) is readable and permissive: a generic `User-agent: *` group with `Allow: /` and no `Disallow` lines at all.
  Discovery is `GET https://www.anpe.gov.bf/wp-json/wp/v2/posts?categories=77&per_page=100&page=N`, which returns the site's own `offres-demplois` category as a JSON array with `X-WP-Total: 97` / `X-WP-TotalPages: 1` (the whole category fits one 100-row page; oldest 2024-09-13, newest 2026-07-03). Category `77` is the recruitment category; category `54` is general news and is deliberately excluded.
  Each post is the WHOLE record (`{id, date, modified, link, title.rendered, content.rendered, excerpt.rendered}`) -- there is no second detail call to merge. `id` is the stable `source_job_id`; `link` is the public notice URL.
  TRAPS: (1) there is NO structured salary, employer, location or contract field -- everything is French prose; (2) salary is NEVER stated ('francs CFA'/'F CFA' occurs only in stamp-fee instructions), so `salary_disclosed` is always False and no bounds are invented; (3) `pay_period` is a required `str` with no 'unknown' member, so it takes the documented inert default (`yearly`, the Jobicy/Reed/TheMuse convention) and is never used to annualise anything; (4) a bare 'stage' is almost always 'attestation de stage' (proof of a past internship), so only `stagiaire`/"stage d'initiation" map to `internship`; (5) the employer is not a field, so `company_name` is the publishing agency and no client is guessed from the title; (6) some titles use Unicode mathematical-bold letters, normalised with NFKC.
  Scope: `currency_iso_code` is `XOF` (the CFA franc, already seeded), and `SOURCE_HOME_COUNTRY["anpe_bf"] = "BF"` is load-bearing because the notices name only a commune/mairie/province that matches no seeded city/country string. 62 of 97 rows therefore resolve to the country-level Burkina Faso row (the 52 distinct commune strings are kept in `core.location_aliases`); the other 35 carry no place phrase at all and stay NULL by design.
  Verified locally: a live dry run parsed/cleaned 97/97 cleanly and a default DB run inserted 97 rows, 0 failed, batch validation PASSED. GitHub Actions CI run 44894387816 (`scrape_api.yml -f only=anpe_bf`) reproduced it: 97 fetched/parsed/cleaned/inserted, 0 failed, validation PASSED; exported to HF as `shards/source=anpe_bf/dt=2026-11-21/part-20261121T102855Z.parquet` (117.0 KiB, 97 rows). Salary undisclosed on all 97; employment full_time 12, internship 4, contract 1, unset 80; 1 company (the agency); posted 2024-09-13..2026-07-03.
  LIVE and enabled in scheduled CI matrix.

- **`anpe_mali`** (Mali, anpe-mali.org) - 2026-11-21. Mali's national employment agency (ANPE, "Agence Nationale Pour l'Emploi"; the site brands itself "Republique du Mali - Service public de l'emploi") runs https://anpe-mali.org, a WordPress install using the WP Job Manager plugin. The domain the earlier sweep recorded, anpe.ml, no longer resolves (NXDOMAIN), so this is a domain-change build like anpe_bf.
  robots.txt (HTTP 200) is readable: a generic `User-agent: *` group with `Disallow: /wp-admin/` and `Allow: /wp-admin/admin-ajax.php`. /wp-admin/ is never fetched and the /wp-json/ path used here is not disallowed, so the policy is respected (no browser, no proxy, no key, TLS verification on).
  Discovery is `GET https://anpe-mali.org/wp-json/wp/v2/job-listings?per_page=100&page=N`, which returns the `job_listing` post type as a JSON array (`X-WP-Total: 15`, one page at scoping). `_embed=wp:featuredmedia` folds each listing's company logo into the same request, so there is no per-listing detail call; the site's own sitemap (`wp-sitemap-posts-job_listing-1.xml`) lists the same 15 `/poste/<slug>/` URLs, cross-checking the count.
  Each listing is the WHOLE record (`{id, date, modified, link, slug, title.rendered, content.rendered, meta, job-types, job-categories, class_list}`). The structured fields live under `meta` (`_company_name`, `_job_location`, `_application`, `_remote_position`, `_job_salary`).
  TRAPS: (1) salary is NEVER stated - `meta._job_salary` is the empty string on all 15 listings - so `salary_disclosed` is always False and no bounds are invented; (2) location is free text ("Bamako" 7, "Mali"/"MALI" 3, "Sur site" 4, empty 1) and "Sur site" names a work arrangement, not a place, so it becomes `remote_work_type_code = on_site` instead of a location; (3) the contract type is the `class_list` `job-type-<slug>` taxonomy - cdi -> full_time, cdd -> contract, interim -> temporary, independant -> freelance, stage -> internship - and a multi-value row is left unset rather than guessed (`job-types` term ids are a fallback only when `class_list` is absent); (4) a minority of titles carry Unicode soft-hyphens and compatibility characters, so titles are NFKC-normalised.
  Scope: `currency_iso_code` is `XOF` (Mali's CFA franc, already seeded) and `pay_period` takes the documented inert default (`yearly`) that the required-str model column forces, never used to annualise anything; `SOURCE_HOME_COUNTRY["anpe_mali"] = "ML"` is load-bearing because "Bamako" matches no seeded city, so without it those rows would have a NULL country (the country row "Mali" was added to `seed/countries.py`). The employer IS a field here (`meta._company_name`), unlike ANPE BF, and the logo comes from the embedded featured media; when no employer is named the agency itself is used and no client is guessed from the title.
  Verified locally: a live dry run parsed/cleaned 15/15 cleanly and a default DB run inserted 15 rows, 0 failed, batch validation PASSED. CI run 44896473387 (scrape_api.yml -f only=anpe_mali): 15 fetched, 15 parsed, 15 cleaned, 15 inserted, 0 failed; exported to HF as `shards/source=anpe_mali/dt=2026-11-21/part-20261121T105513Z.parquet` (86.7 KiB, 15 rows).
  LIVE and enabled in scheduled CI matrix.

- **`llv_li`** (Liechtenstein, llv.li / jobs.smartrecruiters.com) - 2026-11-21. The Liechtensteinische Landesverwaltung (the Principality's state administration, the "AVW" of the master workbook) publishes its official vacancies on its SmartRecruiters board, linked from https://www.llv.li/de/karriere/jobs as careers.smartrecruiters.com/LiechtensteinischeLandesverwaltung. The board is server-rendered and every detail page is `https://jobs.smartrecruiters.com/LiechtensteinischeLandesverwaltung/<id>-<slug>` with schema.org microdata, so this is a config-only build on the generic HTML framework - no key, no registration, no proxy, no browser, TLS verification stays ON.
  robots.txt: `jobs.smartrecruiters.com/robots.txt` answers HTTP 404 (no policy file, RFC 9309 allow-all); `careers.smartrecruiters.com/robots.txt` returns the SPA's HTML document with no robots directives; `www.smartrecruiters.com/robots.txt` is a real `User-agent: *` file that Disallows a list of specific companies and does NOT list LiechtensteinischeLandesverwaltung. The JSON API host `api.smartrecruiters.com` answers `User-agent: *` / `Disallow: /`, so it is deliberately NOT used - only the HTML board and detail pages are fetched.
  Discovery is the board page `https://jobs.smartrecruiters.com/LiechtensteinischeLandesverwaltung` (a 301 to careers.smartrecruiters.com, followed), which lists `li.opening-job a.js-job-ad-link` links (7 at scoping). Each detail page is one request and is the whole record.
  Field map: title `og:title` (the first `h1` is an empty overlay header; the real title is `h1.job-title`), company `meta[itemprop='name']`, location `meta[itemprop='addressLocality']` (Vaduz 5, Schaan 2), body `.job-sections`, posted date `meta[itemprop='datePosted']`, employment type `li[itemprop='employmentType']`, remote work `spl-job-location[workplacetype]`.
  TRAPS: (1) salary is never stated anywhere, so `salary_disclosed` is always False and no bounds are invented; `currency_iso_code` is `CHF` and `pay_period` takes the documented inert default (`monthly`) that the required-str column forces; (2) the employment labels are German - `Vollzeit` -> full_time and `Teilzeit` -> part_time - so both were added to the shared `_EMPLOYMENT_MAP`; (3) `spl-job-location` carries `workplacetype="on_site"` (schema.org underscore form), so the shared `_ONSITE_PATTERN` was widened to accept `on_site`; (4) `base_url` must be `jobs.smartrecruiters.com` or the quality filter's `_same_site` rejects the absolute detail URLs, and `detail_url_pattern` `.*/LiechtensteinischeLandesverwaltung/\d+-.*` bypasses the path-keyword gate; (5) the board auto-redirects to the careers host, which the client follows.
  Scope: Liechtenstein had no `ref.countries` row, so it was added to `seed/countries.py` (`LI`, `LIE`, Europe, `CHF` - already seeded); `SOURCE_HOME_COUNTRY["llv_li"] = "LI"` is load-bearing because the postings name only a local place that matches no seeded city, so both Vaduz and Schaan resolve to the country-level Liechtenstein row instead of the global-remote location.
  Verified locally: a live dry run parsed/cleaned 7/7 cleanly and a default DB run inserted 7 rows, 0 failed, batch validation PASSED. CI run 44899321625 (`scrape_html.yml -f only=llv_li`) reproduced it: 7 fetched/parsed/cleaned/inserted, 0 failed, validation PASSED; exported to HF as `shards/source=llv_li/dt=2026-11-21/part-20261121T113105Z.parquet` (49.5 KiB, 7 rows). All 7 rows resolve to Liechtenstein; salary undisclosed on all 7 (CHF); employment full_time 4, part_time 3; remote-work on_site 7; 1 company; posted 2026-09-30..2026-11-20; data_quality_score 0.86 on all 7.
  LIVE and enabled in scheduled CI matrix.

- **`bdjobs_com`** (Bangladesh, bdjobs.com) - 2026-11-21. Bdjobs is Bangladesh's largest job board; its public single-page app (https://bdjobs.com/h/) is backed by two keyless JSON endpoints on `api.bdjobs.com`, both copied verbatim from the site's own bundled config chunk `https://bdjobs.com/h/chunk-SMUS2CWI.js` (keys `searchEndpoint` and `detailsApiBaseUrl`), so they are the endpoints the app itself calls. No key, no registration, no proxy, no browser, TLS verification stays ON.

  Discovery is `GET https://api.bdjobs.com/jobs/api/v1/JobSearch/GetJobSearch` with `pg=N&rpp=100`, answering `{message, statuscode, data[], premiumData[], common{total_records_found, totalpages, total_vacancies}}` (newest-first; ~5,747 rows over 58 pages at scoping). `data` is the paginated feed and `premiumData` is a small rotating set of promoted rows, so both are merged and de-duplicated by `Jobid`. Every row is then hydrated by `GET https://api.bdjobs.com/jobs/api/v1/JobSubsystem/jobDetails` with `jobId=<id>&ln=1&IsCorporate=false`; a browser User-Agent is enough (no extra header needed).

  robots.txt drove the design: `bdjobs.com/robots.txt` (HTTP 200) declares a `User-agent: *` group that disallows a list of asset paths and then a SECOND `User-agent: *` group with `Disallow: /`, and RFC 9309 combines rules for the same user-agent, so the effective policy for `*` is disallow-all; `jobs.bdjobs.com/robots.txt` (HTTP 200) has the same shape. The API host is separate and open: `api.bdjobs.com/robots.txt` answers HTTP 404 (an IIS HTML not-found page, no policy file), which RFC 9309 treats as "unavailable" and permits - the same allow-on-404 reading this repo applied to `jobs.smartrecruiters.com` for `llv_li`. Accordingly the scraper fetches ONLY `api.bdjobs.com` and never any `bdjobs.com` / `jobs.bdjobs.com` HTML page; the public `https://bdjobs.com/h/details/<id>` URL it stores is a link for humans, never a request.

  Field map: title `JobTitle`/`jobTitle`; company `CompanyNameENG` then the site's own misspelling `CompnayName` then `companyName`; description `JobDescription` with `AdditionJobRequirements`, `EducationRequirements` and `JobOtherBenifits` folded into one cleaned description; skills the comma-split `SkillsRequired` plus `SuggestedSkills`; location `JobLocation`/`location`; dates ISO `publishDate`/`deadlineDB` or the human `PostedOn`/`Deadline`; apply `ApplyURL` or a `mailto:` from `JobAppliedEmail`.

  TRAPS: (1) salary is often undisclosed - `ShowSalary` is `"0"` on some rows, many disclosed rows are "Negotiable" (bounds 0), and the rest carry `"Tk. <min> - <max> (Monthly)"`; the cleaner keeps positive BDT bounds, honours `ShowSalary == 0` as a site-side withhold, and swaps a reversed pair; (2) `JobNature` (Full Time/Contractual/Part Time) maps to `ref.employment_types` and `JobWorkPlace` (Work at office/Work from home/blank) to `ref.remote_work_types` - "Work from home" maps to `remote_country` (remote within Bangladesh), and a blank workplace falls back to the shared mapper; (3) currency is BDT and the pay period is read from the range text, defaulting to monthly (the Bangladesh convention); (4) the two HTML hosts are disallow-all, so the API host is the only one ever fetched.

  Scope: Bangladesh (`BD`, `BGD`, Asia, `BDT`) was already seeded via `job_com_bd`, so no `seed/countries.py` change was needed; `SOURCE_HOME_COUNTRY["bdjobs_com"] = "BD"` is load-bearing because postings name free-text places ("Dhaka", "Chattogram", a bare "Bangladesh") that need not match a seeded city.

  Verified locally: 22 targeted unit tests pass; a default DB run fetched/parsed/cleaned/inserted 200/200 rows, 0 failed, batch validation PASSED. CI run 44901629797 (`scrape_api.yml -f only=bdjobs_com`) reproduced it: 200 fetched/parsed/cleaned/inserted, 0 failed, validation PASSED; exported to HF as `shards/source=bdjobs_com/dt=2026-11-21/part-20261121T120146Z.parquet` (282.4 KiB, 200 rows). All 200 rows resolve to Bangladesh except one (a posting naming a UK place); salary disclosed on 69 (BDT 9,000-110,500 monthly), undisclosed on 131; employment full_time 193, contract 5, part_time 2; remote-work on_site 152, remote_country 7, unset 40.

  LIVE and enabled in scheduled CI matrix.

- **`blmis_bt`** (Bhutan, blmis.gov.bt) - 2026-11-21. The workbook records this state jobs portal as `jobs.molhr`, but that domain no longer exists: both `molhr.gov.bt` and `jobs.molhr.gov.bt` are NXDOMAIN at the `.bt` authoritative nameservers (`dns.google/resolve`, Status 3). MoLHR's labour functions now sit under MOICE, and the portal is the **Bhutan Labour Market Information System** at https://www.blmis.gov.bt, so this is a successor build in the same spirit as `llv_li` (whose state vacancies had moved onto a SmartRecruiters board). No key, no registration, no login, no cookie, no proxy, no browser; TLS verification stays ON.

  `robots.txt` (HTTP 200) is a bare `User-agent: *` group with an EMPTY `Disallow` (allow-all) and no `Crawl-delay`. The whole inventory is one plain GET: `/jobseeker_page/mispage` ("Vacancies & Trainings") is a Laravel Livewire page that server-renders the current vacancies into the component's `wire:initial-data` attribute (an HTML-entity-encoded JSON blob) BEFORE any JavaScript runs, so no browser and no AJAX follow-up are needed. `serverMemo.data` carries six overlapping browse facets over the SAME inventory - `job_by_categories`, `job_by_location`, `job_by_company`, `job_by_qualification`, `job_by_yelp` and `job_by_oversea` - so the client merges all six and de-duplicates by `application_no` (442 unique at scoping; `job_by_company` alone held 362).

  Field map: title `designation`; company `company_name` then `business_name` then the named `placement` for a domestic row with neither; description `job_description` with `qualification`, `eligible_criteria`, `terms_conditon` (the site's own spelling) and `remarks` folded into one cleaned description; location `gewog_name` + `dzongkhag_name` (sub-district, district) for a domestic posting, or `placement` (the destination country) for an overseas one; posted date `created_at` (`"2026-11-19 09:23:25"`); closing date `last_date_registration` (`"2026-12-10"`); employment type `employment_type` (Regular -> `full_time`, Contract -> `contract`, Intern -> `internship`); salary `starting_salary`, a single monthly figure with no range and no currency code.

  TRAPS: (1) salary is a single figure, so it is stored as `salary_min` with `salary_max` left honestly unstated rather than mirrored; (2) a figure of `0` or `1` is the board's "not stated" placeholder (measured on a "sales manager" post quoting `"1.00"`) and is read as undisclosed, the same "a placeholder is not a salary" rule `jobwebghana_cleaner` applies; (3) currency is BTN (ngultrum) for domestic rows, while an overseas row (`vacancy_type_id` 516) quotes the destination currency, mapped from the `placement` country (Qatar -> QAR) with a BTN fallback; (4) the rare combined employment label "Casual/Freelance" is deliberately left unmapped because it names two engagement types at once - the raw value stays in `raw_payload`; (5) there is no skills or work-mode field, so `skills` stays empty and `remote_work_type_code` stays `None`; (6) the stored `original_url` is the public detail page `https://www.blmis.gov.bt/jobseeker_page/jobdetails/<application_no>`, a link for humans that is never fetched (that route returns only the SPA shell).

  Scope: Bhutan had no `ref.countries` row and BTN no `ref.currencies` row, so both were seeded as part of this build (`BT`, `BTN`, Asia); `salary_standardization.py` gained USD reference rates for BTN (derived from the BTN/INR 1:1 and INR/NPR 1.6 pegs against this table's own NPR entry) and QAR (the 3.64 per USD peg); `SOURCE_HOME_COUNTRY["blmis_bt"] = "BT"` is load-bearing because a domestic posting names a Bhutanese dzongkhag and never a country, and no Bhutanese city is in the curated seed.

  Verified locally: 27 targeted unit tests pass; a DB run fetched/parsed/cleaned/inserted 428/428 rows, 0 failed, batch validation PASSED. CI run 44919717232 (`scrape_api.yml -f only=blmis_bt`) reproduced it: 428 fetched/parsed/cleaned/inserted, 0 failed, validation PASSED; exported to HF as `shards/source=blmis_bt/dt=2026-11-21/part-20261121T153411Z.parquet` (177.2 KiB, 428 rows). 426 rows resolve to Bhutan and the 2 overseas postings to Qatar (0 NULL country, 0 global-remote fallback), every domestic row on the country-level Bhutan location with its gewog/dzongkhag string kept in `core.location_aliases`; all 428 carry a description (average 58.8 words); salary disclosed on 424 (BTN 1,000-50,000 monthly = USD 143.28-7,164.00 annualised; QAR 1,785 monthly on the two Qatar rows) and undisclosed on 4; employment full_time 385, contract 40, internship 1, unset 2; 360 companies; posting dates 2022-09-28..2026-11-20; data_quality_score 0.25-0.75 (average 0.65).

  LIVE and enabled in scheduled CI matrix.

- **`bongthom_com`** (Cambodia, bongthom.com) - 2026-11-21. BongThom is one of Cambodia's largest job boards. Its public Laravel front end is backed by keyless `*_Controller` JSON routes plus a server-rendered detail page. No key, no registration, no login, no cookie, no proxy, no browser; TLS verification stays ON.

  `robots.txt` on `bongthom.com`, `www.bongthom.com` and `front.bongthom.com` (HTTP 200) serves the application's HTML marketing page under `text/html` rather than a policy file, so there is no robots policy to obey - the same app-shell-instead-of-a-policy-file posture `llv_li` documented. `account.bongthom.com/robots.txt` is an independent 404. The scraper reads only the three public routes below.

  Discovery is `GET https://bongthom.com/Job_Controller/get_all?page=N`, the board's own Laravel paginator envelope `{current_page, data[], last_page, per_page:40, total, ...}`; `data` is the newest-first feed and `per_page` is fixed at 40 (the `per_page`/`limit` params are ignored). The whole board held 263 jobs over 7 pages at build time. Each job is hydrated by two keyless GETs: (1) the structured `GET https://bongthom.com/Job_Controller/get_embed/<id>` JSON, whose `positions[]` carry an HTML `description`, `duties[].text`, `benefits[].benefit`, `skill_knowledges[].skill` and `.skill_type` (`language`/`soft`/`hard`), `categories[].name_en`, `qualifications[].major` and `experiences[]` with numeric `years`; and (2) the rendered `GET https://bongthom.com/job_detail/view_detail_<id>.html` page, whose 'Workplace Circumstances' list is the only place the displayed work location, salary and schedule appear (`get_embed` leaves `schedule`/`salary` null for most rows and its `locations` objects are legacy office addresses, not the work site).

  Field map: title/company/logo from the embed with the discovery row as fallback, and the board's `error_pic` logo placeholder dropped; description folds the position descriptions, duties, benefits, qualifications and experience bullet text into one cleaned description; skills = `skill_knowledges[].skill` cleaned, lowercased and de-duplicated; `experience_years_min` = `min(experiences[].years)`; location = the rendered 'Location' value(s) joined by '; '; salary = the rendered 'Salary' value; employment = the rendered 'Schedule' value.

  TRAPS: (1) the rendered page writes every label/value row into `li.clearfix.en` regardless of display language, so a Khmer-default posting puts Khmer label text in that same class - the parser keeps a row only when its `<strong>` label is a known English label ('environment', 'languages', 'location', 'career category', 'schedule', 'salary'), not by trusting the class; (2) salary is a `$` string - `$<min> - $<max>` is parsed as a range, a lone `$<value>` is stored as `salary_min` with `salary_max` honestly unstated, and 'Negotiable'/'Based on Experience'/'N/A'/'Other Benefits' is undisclosed; (3) currency is USD (Cambodia's dollarised economy) and monthly; (4) a combined schedule label ('Full-time, Part-time') is deliberately left unmapped because it names two engagement types at once - the raw value stays in `raw_payload`; (5) a location list naming 'Working from home'/'online' maps to `remote_country` (remote within Cambodia); (6) some postings ('Call for Application', consultancy notices) keep their content in an attached PDF and carry no inline description.

  Scope: Cambodia had no `ref.countries` row, so it was seeded as part of this build (`KH`, `KHM`, Asia, default currency `USD` - the dollar is Cambodia's default currency and USD was already seeded). `SOURCE_HOME_COUNTRY["bongthom_com"] = "KH"` is load-bearing because a posting names a province ('Phnom Penh', 'Siemreap Province'), a home-working label or, rarely, a neighbour ('Laos'), never a country, and no Cambodian city is in the curated seed.

  Verified locally: 52 targeted unit tests pass (the BongThom module plus the source-registry guards); a DB run fetched/parsed/cleaned/inserted 263/263 rows, 0 failed, batch validation PASSED. CI run 44930081190 (`scrape_api.yml -f only=bongthom_com`) reproduced it: 263 fetched/parsed/cleaned/inserted, 0 failed, validation PASSED; exported to HF as `shards/source=bongthom_com/dt=2026-11-21/part-20261121T173720Z.parquet` (526.0 KiB, 263 rows). All 263 rows resolve to Cambodia (0 NULL country, 0 global-remote fallback); no Cambodian city is seeded, so every row sits on the country-level Cambodia location with its province string kept in `core.location_aliases` (33 distinct); 221 carry a non-empty cleaned description (average 519.9 words among those; the 42 zero-word rows are attachment-only calls for application and consultancy); salary disclosed on 47 (USD 150-2,500 monthly = USD 1,800-30,000 annualised) and undisclosed on 216; employment full_time 208, part_time 6, temporary 3, unset 46; remote-work remote_country 2, unset 261; `experience_years_min` present on 65 (3-12 years); 194 companies; posting dates 2026-10-24..2026-11-21; data_quality_score 0.25-1.00 (average 0.71).

  LIVE and enabled in scheduled CI matrix.

- **`cvonline_hu`** (Hungary, cvonline.hu) - 2026-11-22. CVOnline.hu is one of Hungary's main generalist job boards, built on Joomla. It is the first Hungarian source built (the country's only workbook row, profession.hu, is still BACKLOG). No key, no registration, no login, no cookie, no proxy; because the board serves a JavaScript 'Bot Check' interstitial to non-browsers, it is a BROWSER source (Selenium via seleniumbase undetected Chrome, `scripts/run_browser_scraper.py`). TLS verification stays ON (no `verify=False`).

  `robots.txt` on https://www.cvonline.hu/robots.txt (HTTP 200) is a generic `User-agent: *` group with `Crawl-delay: 10` (honoured through `inter_request_delay_seconds = 10.0`) and a list of Disallows that cover only Joomla infrastructure paths ('/includes/', '/misc/', '/modules/', '/profiles/', '/scripts/', '/themes/', '/admin/', '/comment/reply/', '/filter/tips/', '/node/add/', '/search/', ...). The search directory and the ad paths are not Disallowed, so the crawl-delay is the only constraint and the scraper honours it between requests.

  Discovery is the server-rendered directory `GET https://www.cvonline.hu/hu/allashirdetesek`, paged `?page={page}`; the directory held 257 pages at scoping with about 20 ad links per page. `job_link` is `a[href*='/allas/']` and `detail_url_pattern` `/(?:[a-z]+/)?allas/[^/]+-[0-9]+$` keeps only the ad URLs, which include the three paid listing templates `/hu/premium/allas/<slug>-<id>`, `/hu/lite/allas/<slug>-<id>` and `/hu/freemium/allas/<slug>-<id>` alongside the plain `/hu/allas/<slug>-<id>`; the ad id is the trailing run of digits (`id_url_regex` `-([0-9]+)$`).

  Field map: each ad publishes a schema.org `JobPosting` block in `application/ld+json` (title, `datePosted`, `validThrough`, `hiringOrganization.name`, `employmentType[]`, `jobLocation[].address.addressCountry`/`.addressLocality`, and an HTML `description`), read through `detail_json_ld` plus `detail_json_map` and rendered into the markup the shared parser expects; an ad with no block falls back to the rendered page. `detail_ready_selector` `div.node-job` is what waits out the Bot Check interstitial, because `node-job` appears only on a real ad page and never on `botchallenge.html`. `baseSalary` is published but its `value.minValue`, `value.maxValue` and `value.unitText` were empty strings on every ad sampled (plain and premium alike), so salary is left undisclosed rather than guessed; currency HUF, monthly.

  TRAPS: (1) the interstitial is a JavaScript 'Bot Check' page (`botchallenge.html`) served with HTTP 200 that sets a `bot_verified` cookie and replaces the location after a short delay - it is not a captcha, and the browser framework clears it by waiting for `div.node-job`; (2) `h1` is not a safe ready selector because the challenge page renders its own heading, so the wait keys on the ad body instead; (3) `baseSalary` is present-but-empty (the currency is real, the range is not), so it must not be read as a disclosed range; (4) the ad id is the trailing number and the slug before it is free text, so the id comes from the URL, not the slug.

  Scope: Hungary is already seeded (`HU`/`HUN`, Europe, default currency `HUF`), so no reference data was added. `SOURCE_HOME_COUNTRY["cvonline_hu"] = "HU"` covers a locality the curated city seed does not hold; when the ad's `addressLocality` is a seeded city ('Budapest') the row resolves to the city, otherwise to the country-level Hungary location.

  Verified locally: `--no-db` and DB runs fetched/parsed/cleaned/inserted 3/3 rows, 0 failed, 0 NULL country, batch validation PASSED. CI run 44938286096 (`scrape_browser.yml -f only=cvonline_hu`) reproduced it: 60 fetched/parsed/cleaned/inserted, 0 failed, validation PASSED; exported to HF as `shards/source=cvonline_hu/dt=2026-11-21/part-20261121T191536Z.parquet` (81.0 KiB, 60 rows). All 60 rows resolve to Hungary (0 NULL country, 0 global-remote fallback): Budapest 12 and country-level Hungary 48; employment full_time 53, internship 7; salary disclosed on 0 and undisclosed on 60 (HUF, monthly); all 60 carry a non-empty description (44-300 words, average 141.0); 15 companies; posting dates all 2026-11-21; `experience_years_min` present on 1; data_quality_score 0.86 on every row.

  LIVE and enabled in scheduled CI matrix.

- **`emploiburkina_com`** (Burkina Faso, emploiburkina.com) - 2026-11-22. The AfricaWork portal for Burkina Faso and the live successor of the recorded Emploi.bf host: both emploi.bf and www.emploi.bf are NXDOMAIN, but the AfricaWork footer on www.emploi.ci names www.emploiburkina.com, which answers HTTP 200 to plain requests. No key, no registration, no login, no cookie, no proxy, no browser; TLS verification stays ON (no verify=False).

  `robots.txt` on https://www.emploiburkina.com/robots.txt (HTTP 200) is a generic `User-agent: *` group with `Allow: /` and `Crawl-delay: 10`, honoured through `inter_request_delay_seconds = 10.0`; the Disallow list covers only Drupal infrastructure paths (/includes/, /misc/, /modules/, /profiles/, /scripts/, /themes/, /admin/, /search/, /user/login/, ...), so the search directory and the ad paths are allowed.

  Discovery is the server-rendered Drupal search directory `GET https://www.emploiburkina.com/recherche-jobs-burkina-faso`, paged `?page={page}` (page 1 takes no query string); it held 25 ad links per page and the run walks up to 4 pages. `job_link` is `a[href*='/offre-emploi-burkina-faso/']` and `detail_url_pattern` `offre-emploi-burkina-faso/[^/]+` keeps only the ad URLs; the ad id is the trailing run of digits (`id_url_regex` `-([0-9]+)$`).

  Field map: each ad publishes a schema.org `JobPosting` block in `application/ld+json` (title, `datePosted`, `validThrough`, `hiringOrganization.name`, `employmentType`, `jobLocation.address.addressLocality`/`.addressRegion`/`.addressCountry`, and an HTML `description`), read through `detail_json_ld` plus `detail_json_map`. The block carries the same unescaped-quote defect as the other AfricaWork boards (inline HTML such as `<p dir="ltr">`), repaired by the shared JSON-LD reader.

  TRAPS: (1) `jobLocation.address.addressRegion` is not a region but the list of cities the ad is open to, kept for context only; (2) a remote ad can carry an international locality ("France") with the home country left on `addressCountry`, which is why `SOURCE_HOME_COUNTRY["emploiburkina_com"] = "BF"` is the fallback; (3) `baseSalary` was absent on every sampled ad, so `salary_disclosed` is false and XOF/monthly states the home market, not an amount.

  Burkina Faso (BF, country_id 7123) and XOF (currency_id 506) were already seeded, and the board has a single country-level location, so every ad resolves to BF via `source_default_country`.

  Verified locally: 8 fetched, 8 parsed, 8 inserted, 0 failed, batch validation PASSED (all Burkina Faso, XOF/monthly, descriptions 97-359 words, data_quality_score 0.86, 6 companies).

  GitHub Actions CI run 44944252512: 52 fetched, 52 parsed, 52 inserted, 0 failed, PASSED; 52 rows exported to Hugging Face (shards/source=emploiburkina_com/dt=2026-11-21/part-20261121T201625Z.parquet, 84.2 KiB).

  LIVE and enabled in scheduled CI matrix.

- **`ghanajob_com`** (Ghana, ghanajob.com) - 2026-11-22. GhanaJob is the AfricaWork portal for Ghana and a board distinct from the bespoke jobwebghana source. No key, no registration, no login, no cookie, no proxy; because the host sits behind a Cloudflare managed challenge that plain requests cannot clear, it is a BROWSER source (Selenium via seleniumbase undetected Chrome, `scripts/run_browser_scraper.py`). TLS verification stays ON (no verify=False).

  `robots.txt` on https://www.ghanajob.com/robots.txt (HTTP 200) is a Cloudflare-managed generic `User-agent: *` group with `Allow: /` and a Content-Signal line (`search=yes,ai-train=no,use=reference`); only `Amazonbot` is Disallowed, so the search directory and the ad paths are allowed. There is no Crawl-delay, and the scraper keeps a polite `inter_request_delay_seconds = 3.0`.

  The challenge clears in about 6 seconds on the first navigation and the session cookie then carries every later request, so listing discovery and the detail reads are ordinary renders. Discovery is the server-rendered Drupal search directory `GET https://www.ghanajob.com/job-vacancies-search-ghana/`, paged `?page={page}` (page 1 takes no query string); it held 25 ad links per page and the config walks up to 8 pages. `job_link` is `a[href*='/job-vacancies-ghana/']`; the ad id is the trailing run of digits (`id_url_regex` `-([0-9]+)$`) and `detail_url_pattern` is `job-vacancies-ghana/[^/]+$`.

  Field map: each ad at `/job-vacancies-ghana/<slug>-<numeric id>` publishes a schema.org `JobPosting` block in `application/ld+json` (title, `datePosted`, `validThrough`, `hiringOrganization.name`, `employmentType`, `jobLocation.address.addressLocality`/`.addressRegion`/`.addressCountry`, and an HTML `description`), read through `detail_json_ld` plus `detail_json_map`. The block carries the same unescaped-newline defect as the other AfricaWork boards, repaired by the shared JSON-LD reader. The rendered listing keeps Cloudflare's passive `challenge-platform` script, declared inert through `ignore_challenge_markers`.

  TRAPS: (1) the rendered listing HTML contains Cloudflare's `challenge-platform` marker on a fully rendered page, so it must be ignored or every listing would be rejected as a bot challenge; (2) `baseSalary` was absent on every sampled ad, so `salary_disclosed` is false and GHS/monthly states the home market, not an amount; (3) the ad body is an HTML `description` that the shared reader repairs from the JSON-LD's raw newlines.

  Ghana (GH, country_id 49) was already seeded and GHS is `ref.currencies` currency_id 501; the board resolves its country from the ad's clean `addressCountry` label with `SOURCE_HOME_COUNTRY["ghanajob_com"] = "GH"` as the fallback for a country-less row.

  Verified locally: 6 fetched, 6 parsed, 6 cleaned, 0 failed, batch validation PASSED.

  GitHub Actions CI run 44950153873: 60 fetched, 0 fetch failures, 59 parsed, 59 cleaned, 59 inserted, 0 failed, batch validation PASSED (1.7% skip rate); 59 rows exported to Hugging Face (shards/source=ghanajob_com/dt=2026-11-21/part-20261121T212034Z.parquet, 83.7 KiB).

  LIVE and enabled in scheduled CI matrix.

- **`jobat_be`** (Belgium, jobat.be) - 2026-11-22. Jobat is a general Belgian job board distinct from the already-built VDAB (Flanders) source. No key, no registration, no login, no cookie, no proxy; because the listing renders its vacancy cards client-side, it is a BROWSER source (Selenium via seleniumbase undetected Chrome, `scripts/run_browser_scraper.py`). TLS verification stays ON (no verify=False).

  `robots.txt` on https://www.jobat.be/robots.txt (HTTP 200) is a generic `User-agent: *` group that disallows only account/article paths (`/secure/login`, `/myjobat/login`, `/nl/artikels-zoeken`, `/*/art/<year>/*`, `/nl/jobs/bedrijvenold*`) and tracking query parameters (`*joblanguage=*`, `*action=*`), so the listing and the ad pages are allowed. The scraper keeps a polite `inter_request_delay_seconds = 2.0`.

  Discovery is the general feed `GET https://www.jobat.be/nl/jobs/results`, paged `?page={page}` (about 50 ad links per page); `job_link` is `a[href*='/job_']`, an ad is `/nl/jobs/<slug>/job_<numeric id>` and the id is the trailing digits (`id_url_regex` `/job_([0-9]+)$`).

  Field map: unlike the other boards here, a Jobat ad publishes schema.org **microdata** (`itemscope itemtype="http://schema.org/JobPosting"`), not a JSON-LD block, so fields come from CSS selectors: `h1` title, `a[itemprop='name']` company, `meta[itemprop='addressLocality']@content` location, `meta[itemprop='datePosted']@content` posted date, `meta[itemprop='employmentType']@content` employment type, and `.JobDetails-content` as the ad body.

  TRAPS: (1) the rendered listing keeps Cloudflare's passive `challenge-platform` marker on a fully rendered page, declared inert through `ignore_challenge_markers`; (2) `baseSalary` is absent on the sampled ads, so `salary_disclosed` is false and EUR/monthly states the home market, not an amount; (3) a disclosed ad prints its range in the `#jobdetail` header, matched by the salary selector without picking up the recommendation cards.

  Belgium (BE, country_id 12) was already seeded and EUR is `ref.currencies` currency_id 2; the board resolves its country from the ad's location with `SOURCE_HOME_COUNTRY["jobat_be"] = "BE"` as the fallback for a country-less row.

  Verified locally: 6 fetched, 6 parsed, 6 cleaned, 0 failed, batch validation PASSED.

  Disabled in CI 2026-11-22 (kept BUILT): the GitHub Actions runner's datacenter IP is served a persistent Cloudflare "Just a moment" managed challenge on the listing (CI runs 44954059787, 44954574960 and 44955776144 all failed with "never showed a[href*='/job_']" and matched "just a moment"), and neither `ignore_challenge_markers=challenge-platform` nor `uc_open_with_reconnect` (4 s) cleared it. It runs correctly from a residential IP, so it is kept BUILT (Disabled in CI) and can be re-enabled when the runner's IP block lifts. Belgium is already covered by `vdab_be` (active in CI).
- **`jobbsafari_se`** (Sweden, jobbsafari.se) - 2026-11-22. JobbSafari is a Swedish job board distinct from the already-built JobTech state source. No key, no registration, no login, no cookie, no proxy; because the whole host sits behind a Cloudflare managed challenge (plain requests get HTTP 403 "Just a moment..." on every path, robots.txt included) it is a BROWSER source (Selenium via seleniumbase undetected Chrome, `scripts/run_browser_scraper.py`). TLS verification stays ON (no verify=False).

  `robots.txt` (fetched through the browser, since plain requests get the challenge) is a generic `User-agent: *` group with `Allow: /` that disallows only `/api`, `/monitoring` and the facet query parameters (`/lediga-jobb*yrke=*`, `*ort=*`, `*kategori=*`, `*foretag=*`), so the plain `/lediga-jobb` listing and the `/jobb/<slug>-<numeric id>` ad pages are allowed.

  JobbSafari is a Next.js site; `/lediga-jobb` is server-rendered (about 31 ad links per page) and paged `?page={page}`, and the browser clears the challenge in a few seconds on the first navigation before discovery begins. `job_link` is `a[href^='/jobb/']` and the ad id is the trailing digits (`id_url_regex` `-([0-9]+)$`).

  Field map: each ad publishes a schema.org `JobPosting` block in `application/ld+json`, read through `detail_json_ld` plus `detail_json_map` (title, `hiringOrganization.name`, `jobLocation.address.addressLocality`, `datePosted`, `employmentType` and the HTML `description`). The block carries no `addressCountry`, which is what the country fallback is for.

  TRAPS: (1) `jobLocation.address.addressLocality` prints a Swedish county (for example "Stockholms lan") rather than a city, and the sampled ads were sometimes Norwegian, so the row's country comes from the ad text with the fallback only for a country-less row; (2) `employmentType` is `OTHER` on the sampled ads and maps to no `ref.employment_types` code; (3) `baseSalary` is null, so `salary_disclosed` is false and SEK/monthly states the home market, not an amount.

  Sweden (SE, country_id 15) was already seeded and SEK is `ref.currencies` currency_id 16; `SOURCE_HOME_COUNTRY["jobbsafari_se"] = "SE"` is the fallback for a country-less row.

  Verified locally: 6 fetched, 6 parsed, 6 cleaned, 0 failed, batch validation PASSED.

  Disabled in CI 2026-11-22 (kept BUILT): the GitHub Actions runner's datacenter IP is served a persistent Cloudflare "Just a moment" managed challenge on the listing (CI runs 44954073006, 44954588593 and 44955791669 all failed with "never showed a[href^='/jobb/']" and matched "just a moment"), and `uc_open_with_reconnect` (4 s) did not clear it. It runs correctly from a residential IP, so it is kept BUILT (Disabled in CI) and can be re-enabled when the runner's IP block lifts. Sweden is already covered by `jobtech_se` (active in CI).

- **`jobs_ps`** (Palestine, jobs.ps) - 2026-11-22. Jobs.ps is the leading Palestinian job board and a territory the corpus did not cover at all before this (Palestine had ZERO postings). No key, no registration, no login, no cookie, no proxy; because the host sits behind a Cloudflare managed challenge that plain requests cannot clear, it is a BROWSER source (Selenium via seleniumbase undetected Chrome, `scripts/run_browser_scraper.py`). TLS verification stays ON (no verify=False).

  `robots.txt` on https://jobs.ps/robots.txt (HTTP 200) is a Cloudflare-managed policy (it ends with a `# END Cloudflare Managed Content` block); its generic `User-agent: *` group does not disallow `/search` or `/jobs/`, so the search listing and the ad pages are allowed, and the scraper keeps a polite `inter_request_delay_seconds = 2.0`.

  Discovery is the general search feed `GET https://www.jobs.ps/search`, paged `?page={page}` (10-20 ad links per page; `/search?page=2` and `/search?page=3` return new ids rather than repeating page 1); `job_link` is `a[href*='/jobs/']`, an ad is `/jobs/<slug>-<numeric id>` and the id is the trailing digits (`id_url_regex` `-([0-9]+)$`).

  Field map: each ad publishes a schema.org `JobPosting` block in `application/ld+json`, read through `detail_json_ld` plus `detail_json_map` (title, `hiringOrganization.name`, `jobLocation[].address.addressLocality`, `datePosted`, `employmentType` and the HTML `description`).

  TRAPS: (1) the rendered page keeps Cloudflare's passive `challenge-platform` marker on a fully rendered page, declared inert through `ignore_challenge_markers`; (2) `jobLocation` is a LIST of `Place` objects, so the map path uses `jobLocation[]`; (3) `baseSalary.value.value` is a non-numeric string ('N/A' or an Arabic sentence), so `salary_disclosed` is false and ILS/monthly states the home market, not an amount; (4) `employmentType` is Arabic and maps to no `ref.employment_types` code; (5) `jobLocation[].address.addressCountry` is the Arabic word for Palestine, which the resolver does not know, so `SOURCE_HOME_COUNTRY["jobs_ps"] = "PS"` is what places a row.

  Palestine (PS) was NOT seeded before this run: `seed/countries.py` gained `("PS", "PSE", "Palestine", "Asia", "ILS")` and `python -m seed.run_all` inserted it as country_id 7621 with ILS as `default_currency_id` (`ref.currencies` currency_id 15). The board resolves its country from the ad's location with the source home country as the fallback for a country-less row.

  Verified locally: 6 fetched, 6 parsed, 6 cleaned, 0 failed, batch validation PASSED; a DB run inserted 3 rows, all resolved to Palestine (country_id 7621, `is_global_remote` false).

  Disabled in CI 2026-11-22 (kept BUILT): the GitHub Actions runner's datacenter IP is served a persistent Cloudflare "Just a moment" managed challenge on `/search` (CI run 44981947839 failed with "never showed a[href*='/jobs/']" and matched "just a moment"), the same datacenter-IP wall that blocks the sibling sources `jobat_be` and `jobbsafari_se` (where `uc_open_with_reconnect` (4 s) did not clear it). It runs correctly from a residential IP, so it is kept BUILT (Disabled in CI) and can be re-enabled when the runner's IP block lifts.

- **`jobstreet_ph`** (Philippines, jobstreet.com.ph) - 2026-11-22. JobStreet Philippines is the SEEK/JobStreet board for the Philippine market (a distinct inventory from the state PhilJobNet and the local Kalibrr source this repo already runs). No key, no registration, no login, no cookie, no proxy; it is a BROWSER source (Selenium via seleniumbase undetected Chrome, `scripts/run_browser_scraper.py`) because the listing and detail pages are client-rendered. TLS verification stays ON (no verify=False).

  `robots.txt` on https://ph.jobstreet.com/robots.txt (HTTP 200) is a generic `User-agent: *` group that disallows `*/job/*?*type=` and a bare `*?` (plus `/api` and the facet-query paths) but ALLOWS the clean `/jobs` listing and the clean `/job/<id>` ad page. The ad hrefs the page ships carry a tracking query (`?type=standard&ref=search-standalone#sol=...`); the new OPT-IN framework knob `detail_url_strip_query` (default off, added in this change) trims each discovered detail URL to its bare path - query string and fragment removed - before the fetch, so every request targets a robots-allowed URL.

  Discovery is the server-rendered `GET https://ph.jobstreet.com/jobs`, which renders 90 ad anchors (30 unique ad ids, about 3 anchors per card: title, card, logo). A robots-allowed paginated listing was not available to a generic crawler, so this source scrapes PAGE 1 ONLY (`max_pages = 1`, `listing_pagination` empty). `job_link` is `a[href*="/job/"]`; an ad is `/job/<numeric id>` and the id is the trailing digits (`id_url_regex` `/job/(\d+)$`).

  Field map: each ad publishes a schema.org `JobPosting` block in `application/ld+json`, read through `detail_json_ld` plus `detail_json_map` (title, `hiringOrganization.name`, `jobLocation.address.addressLocality` / `addressRegion` / `addressCountry`, `datePosted`, `employmentType` and the HTML `description`).

  TRAPS: (1) `employmentType` is a LIST (`FULL_TIME` / `PART_TIME`) and maps to one `ref.employment_types` code; (2) `addressCountry` is the clean label `Philippines` and a remote ad may leave the location empty, which is what `country_fallback` and `SOURCE_HOME_COUNTRY[\"jobstreet_ph\"] = \"PH\"` are for; (3) `baseSalary` is null on the sampled ads, so `salary_disclosed` is false (PHP/monthly states the home market, not an amount).

  Philippines (PH) was already seeded (country_id 33) with PHP as `default_currency_id` (`ref.currencies` currency_id 33).

  Verified locally: 6 fetched, 6 parsed, 6 cleaned, 0 failed, batch validation PASSED; a DB run inserted 3 rows, all resolved to the Philippines (country_id 33, `is_global_remote` false).

  Disabled in CI 2026-11-22 (kept BUILT): the GitHub Actions runner's datacenter IP is served a bot/captcha wall on `/jobs` (CI run 44983367212 failed with \"never showed a[href*='/job/']\" and matched \"captcha-container\"), the same datacenter-IP wall that blocks the sibling sources `jobat_be`, `jobbsafari_se` and `jobs_ps`. It runs correctly from a residential IP, so it is kept BUILT (Disabled in CI) and can be re-enabled when the runner's IP block lifts.

- **`jobstreet_sg`** (Singapore, jobstreet.com.sg) - 2026-11-22. JobStreet Singapore is the SEEK/JobStreet board for Singapore, the sibling of jobstreet.com.ph and built on the same browser framework (a distinct inventory from the state MyCareersFuture source this repo already runs). No key, no registration, no login, no cookie, no proxy; BROWSER source (seleniumbase undetected Chrome). TLS verification stays ON (no verify=False).

  `robots.txt` on https://sg.jobstreet.com/robots.txt (HTTP 200) is a generic `User-agent: *` group that disallows `*/job/*?*type=` and a bare `*?` but ALLOWS the clean `/jobs` listing and the clean `/job/<id>` ad page, so the tracking query on every ad href is trimmed to the bare path via `detail_url_strip_query` (the opt-in knob added in this change) before the fetch.

  Discovery is the server-rendered `GET https://sg.jobstreet.com/jobs`, which renders 90 ad anchors (30 unique ad ids); a robots-allowed paginated listing was not available to a generic crawler, so this source scrapes PAGE 1 ONLY (`max_pages = 1`). `job_link` is `a[href*="/job/"]`; an ad is `/job/<numeric id>` and the id is the trailing digits (`id_url_regex` `/job/(\d+)$`).

  Field map: each ad publishes a schema.org `JobPosting` block in `application/ld+json`, read through `detail_json_ld` plus `detail_json_map` (title, `hiringOrganization.name`, `jobLocation.address.*`, `datePosted`, `employmentType` and the HTML `description`).

  TRAPS: (1) `employmentType` is a LIST and maps to one `ref.employment_types` code; (2) an ad may carry only `addressCountry` `Singapore` or only a locality, and a remote ad may leave the location empty, which is what `country_fallback` and `SOURCE_HOME_COUNTRY[\"jobstreet_sg\"] = \"SG\"` are for; (3) `baseSalary` is null on the sampled ads, so `salary_disclosed` is false (SGD/monthly).

  Singapore (SG) was already seeded (country_id 31) with SGD as `default_currency_id` (`ref.currencies` currency_id 11).

  Verified locally: 6 fetched, 6 parsed, 6 cleaned, 0 failed, batch validation PASSED; a DB run inserted 3 rows, all resolved to Singapore (country_id 31, `is_global_remote` false).

  Disabled in CI 2026-11-22 (kept BUILT): the GitHub Actions runner's datacenter IP is served a bot/captcha wall on `/jobs` (CI run 44983376850 failed with \"never showed a[href*='/job/']\" and matched \"captcha-container\"), the same datacenter-IP wall that blocks the sibling sources `jobat_be`, `jobbsafari_se` and `jobs_ps`. It runs correctly from a residential IP, so it is kept BUILT (Disabled in CI) and can be re-enabled when the runner's IP block lifts.

- **`jobz_pk`** (Pakistan, jobz.pk) - 2026-11-22. Jobz.pk is the Pakistan board jobz.pk, a distinct inventory from the Rozee and Mustakbil sources this repo already runs. The 2026-10-04 sweep recorded a 403 bot wall to plain requests, but a real browser session reaches it; it is a BROWSER source (Selenium via seleniumbase undetected Chrome, `scripts/run_browser_scraper.py`). No key, no registration, no login, no cookie, no proxy; TLS verification stays ON (no verify=False).

  `robots.txt` on https://www.jobz.pk/robots.txt (HTTP 200) is a generic `User-agent: *` group with `Allow: /` (it sets `Crawl-delay 2` only for named crawlers such as ahrefsbot/semrushbot), so the listing and the ad pages are allowed.

  Discovery is the server-rendered `GET https://www.jobz.pk/jobs/` (identical to the homepage), which renders 130 ad links of the form `/<slug>_jobs-<numeric id>.html`. The board's own `/page/N/` pagination answers an ERROR page to a generic crawler, so this source scrapes PAGE 1 ONLY (`max_pages = 1`, `listing_pagination` empty). `job_link` is `a[href*='_jobs-']`; an ad is `/<slug>_jobs-<id>.html` and the id is the trailing digits (`id_url_regex` `_jobs-(\d+)`).

  Field map: the detail page publishes NO schema.org block. Instead a summary table of `<div class='row_job_detail'>` rows pairs a `<div class='job_detail_cell1'>` label with a `<div class='job_detail_cell2'>` value, read with soupsieve selectors - company from the 'Organization' cell, location from the 'Vacancy Location' cell, date from the 'Date Posted / Updated' cell and employment type from the 'Job Type' cell (all via `div.job_detail_cell1:-soup-contains(<label>) + div.job_detail_cell2`), and the body from `#ad-desc-cont`.

  TRAPS: (1) there is no Salary row, so `salary_disclosed` is false (PKR/monthly states the home market, not an amount); (2) the 'Vacancy Location' value is a full "<city>, <province>, Pakistan" string (e.g. `Gujrat , Punjab, Pakistan`), which resolves to PK on its own, and `SOURCE_HOME_COUNTRY[\"jobz_pk\"] = \"PK\"` is what places a row whose city is a bare town; (3) the board's own detail pages can briefly serve a stale template for a freshly-created ad, so a location is only as fresh as the ad.

  Pakistan (PK) was already seeded (country_id 38) with PKR as `default_currency_id` (`ref.currencies` currency_id 39).

  Verified locally: 6 fetched, 5 parsed, 0 failed, batch validation PASSED; a DB run inserted 3 rows, all resolved to Pakistan (country_id 38, `is_global_remote` false).

  Verified in CI 2026-11-22 (run 44984922725): 60 fetched, 58 parsed, 2 skipped (3.3% - posted titles ending in ' Jobs' that the shared quality gate treats as category titles), 58 inserted, 0 failed, batch validation PASSED. This source runs ACTIVE in CI.

- **`kariyer_net`** (Turkiye, kariyer.net) - 2026-11-22. Kariyer.net is Turkiye's largest generalist private-sector board, added because Turkiye had a single source in the corpus (`iskur_gov_tr`, the state employment portal). It is an API (bespoke client) source (`scripts/run_kariyer_net_scraper.py`): no key, no registration, no login, no cookie, no proxy, and TLS verification stays ON (no `verify=False`).

  The 2026-10-04 sweep recorded 'HTTP 403 - bot/login wall' and that wall is real: www.kariyer.net sits behind HUMAN/PerimeterX (app id PXqzR3QUY9) and hard-403s a non-browser client on every HTML path. The scraper reads the board's own public SPA gateways instead - both host names appear verbatim in its JavaScript bundle - search `POST https://candidatewebapigw.kariyer.net/jb/api/jobs/search` (body `{pageNumber, pageSize}`) and detail `GET https://api-web.kariyer.net/job?jobId=<id>` (the bundle's `VUE_APP_API_DOMAIN_V1`). The bundle's own detail call targets the PX-fronted V4 twin `candidatesearchapigateway.kariyer.net`, which serves the identical document but intermittently 403s a cookieless client, so it is kept as `detail_fallback_base_url` and the non-PX mirror is preferred. Both calls use `curl_cffi` with `impersonate="chrome"` because the detail gateways reject a plain `requests` TLS fingerprint, and the detail call must NOT send `Api-Version` (sending 1.1 turns a 200 into a 403).

  `robots.txt` on https://www.kariyer.net/robots.txt (HTTP 200) is a generic `User-agent: *` group that disallows `/filtre*`, `*?v=`, `*?ckw*`, `*?copilot*` and the candidate/account paths, and ALLOWS `/is-ilanlari` (the listing) and `/is-ilani/` (the ad pages); the scraper requests no disallowed path and links back to the allowed `/is-ilani/<slug>-<id>` URL.

  Discovery is the search gateway's `pageNumber` windows, but a requested `pageSize` caps at ~53 rows and the windows OVERLAP AND ROTATE (22,696 live ads on 2026-11-22; page 1 returned 53), so de-duplication by `jobId` is mandatory, not an optimisation. Each ad's detail document (`data.jobGeneralInformation` / `jobPositionInformation` / `jobCandidateCriteria` / `jobCompanyInformation`) supplies the HTML body (`qualificationsWithHtml`, plain fallback `qualifications`), ISO `postingDate`, `closingDateNumeric` (dd.mm.yyyy), `locations[]`, `workType`/`workTypeText`, `workModel`, `positionLevelText` and the education/experience criteria.

  TRAPS: (1) `jobSalaryBudget` is null on every TR ad sampled, so `salary_disclosed` is false (TRY/monthly states the home market, not an amount); (2) `educationLevelText` is a LIST of EVERY level the ad accepts, ordered lowest first, so the requirement is the MINIMUM across the list - a `["Lise(Mezun)", ..., "Yuksek Lisans(Mezun)"]` ad is a high-school role, not a master's; (3) the locality carries Turkish letters and a side marker (`"Istanbul(Asya)"`), which the shared resolver cannot match against its ASCII `ref.cities` seed, so `location_cleaned` folds Turkish letters to ASCII and drops the parenthetical, letting `Istanbul` resolve to `city_id` 41 (the only Turkish city seeded); (4) `SOURCE_HOME_COUNTRY["kariyer_net"] = "TR"` keeps the country on a non-Istanbul posting.

  Turkiye (TR) was already seeded (country_id 25, `country_name` 'Turkey') with TRY as `default_currency_id` (`ref.currencies` currency_id 23); the pre-existing Turkiye source is `iskur_gov_tr`.

  Verified locally: 30 fetched, 0 detail failures, 30 parsed, 30 inserted, batch validation PASSED; the DB then held 32 rows on country TR, currency TRY, with Istanbul rows resolving to `city_id` 41.

  Verified in CI 2026-11-22 (run 44991622516): 60 fetched, 0 detail failures, 60 parsed, 60 inserted, 0 failed, batch validation PASSED. This source runs ACTIVE in CI.

- **`nationalevacaturebank_nl`** (Netherlands, nationalevacaturebank.nl) - 2026-11-22. Nationale Vacaturebank is one of the Netherlands' largest generalist job boards (run by DPG Media) and is the first source in the corpus for NL. It is an HTML (bespoke client) source (`scripts/run_nationalevacaturebank_nl_scraper.py`): no key, no registration, no login, no cookie, no proxy, and TLS verification stays ON (no `verify=False`).

  The 2026-10-04 sweep recorded 'SELENIUM/PLAYWRIGHT REQUIRED (headless browser) - HTTP 403 with anti-bot signals; homepage not fetchable with requests'. The 403 is real for a plain client, but only for a plain client: a `curl_cffi` client with `impersonate="chrome"` gets HTTP 200 and the site is ordinary server-rendered HTML, so no browser is needed. A fresh session's first HTML response can be the 'DPG Media Privacy Gate' consent wall (~8 KB); simply re-requesting the same URL on the same session (the first GET sets the `authId`/`xAuthId` cookies) returns the real page, and the gate's own `/privacygate-confirm` callback (HTTP 403) is never called.

  `robots.txt` on https://www.nationalevacaturebank.nl/robots.txt (HTTP 200) is a generic `User-agent: *` group. It DISALLOWS `/vacatures/*?page=` (and `/vacatures/*?*&page=`) - so pagination is off-limits - plus `/vacature/zoeken?*`, `/vacature/uitgebreid-zoeken`, `/vacature/bookmarken|delen|apply|external-url|website|bladeren`, `/archief/`, `/zzp/`, and the candidate/account and most `/werkgever`/`/recruiter` paths. It ALLOWS everything this scraper reads: `/vacatures`, the `/vacatures/vakgebied|branche|provincie|dienstverband|uren|opleiding/` category pages, the published `/vacatures/sitemap.xml`, and the `/vacature/<uuid>/<slug>` ad pages. The API host `api.nationalevacaturebank.nl` is `Disallow: /` and is NEVER requested.

  Discovery is the board's own `/vacatures/sitemap.xml`: it lists 241 category URLs, of which 91 are content categories; a deterministic rotating window of 4 is walked per run, reading PAGE 1 ONLY of each because `?page=` is disallowed (no query string is ever appended), with links merged round-robin and de-duplicated by UUID.

  Every ad page (~95-110 KB) publishes a schema.org `JobPosting` block with title, `hiringOrganization.name`, `jobLocation.address` (locality/region/country/postal code plus lat/lon), `datePosted`, `validThrough`, `employmentType`, `educationRequirements.credentialCategory`, `experienceRequirements.monthsOfExperience`, `workHours`, `occupationalCategory`, `industry`, `jobLocationType`, `directApply`, `description` and `baseSalary`.

  TRAPS: (1) `datePosted`/`validThrough` are stamped at 22:00Z/23:00Z - midnight in the Netherlands - so both are converted to Europe/Amsterdam before the date is taken (the raw UTC date dates every ad one day early); (2) `baseSalary.value.unitText` lies when it says MONTH: the board stamps hourly rates with `"MONTH"`, so a value far too small for a month (sampled: a "bruto uurloon van EUR 18,43 - 23,99" ad shipped `23` with `unitText: "MONTH"`) is re-read as `hourly` and flagged via `salary_period_assumed`, while a genuine monthly figure (sampled EUR 3.198 - 4.779) is kept; (3) an ad with no `baseSalary` is stored salary-undisclosed in EUR with `pay_period = monthly` (the Dutch convention, and a required column); (4) `employmentType` is usually the list `["FULL_TIME","PART_TIME"]` - the board's 'either' default - so a type is assigned only when the list resolves to exactly one value (INTERN -> internship, CONTRACTOR -> contract, TEMPORARY -> temporary) and a mixed list stays `None`; (5) the second `Occupation` block's `estimatedSalary` is the board's MARKET ESTIMATE, so it is kept in `raw_payload` only and never mapped to the salary fields; (6) withdrawn ads answer HTTP 410 (or HTTP 200 with no `JobPosting` block) and are counted and skipped, and a run that finds no live ad at all raises rather than returning empty.

  Netherlands (NL) was already seeded (country_id 11, `country_name` 'Netherlands') with EUR as `default_currency_id`. Only ONE Dutch city is seeded in `ref.cities`, so most towns ('Groningen', 'Amersfoort', 'Emmen') resolve to no seeded city; `SOURCE_HOME_COUNTRY["nationalevacaturebank_nl"] = "NL"` is what keeps those rows on the Netherlands instead of the shared global-remote location. EUR is not yet in `salary_standardization._USD_CONVERSION_RATES`, so `normalized_annual_*` stay NULL for this source (pre-existing platform behaviour, not a scraper defect).

  Verified locally: 60 fetched, 60 parsed, 60 cleaned, 0 failures, batch validation PASSED.

  Verified in CI 2026-11-22 (run 45026658755): 60 fetched, 0 fetch failures, 60 parsed, 60 inserted, 0 failed, batch validation PASSED. This source runs ACTIVE in CI.

- **`nea_gov_kh`** (Cambodia, nea.gov.kh) - 2026-11-22. The National Employment Agency is Cambodia's state employment portal (run under the Ministry of Labour) and a distinct inventory from the existing `camhr_com` and `bongthom_com` sources. No key, no registration, no login, no cookie, no proxy; TLS verification stays ON (no verify=False). Transport is `curl_cffi` with `impersonate="chrome"`: the bare root `/` answers a Cloudflare JS-challenge shell (~1.7 KB) to a non-browser client, but the content paths this scraper reads are ordinary server-rendered HTML (the 2026-10-04 sweep's 'SELENIUM/PLAYWRIGHT REQUIRED ... cf=True' verdict was measured on that bare root), and the bare root is NEVER requested.

  `robots.txt` on https://www.nea.gov.kh/robots.txt (HTTP 200) is the Cloudflare-managed generic `User-agent: *` group with `Allow: /` (plus `Content-Signal: search=yes,ai-train=no,use=reference`); the later training-crawler groups (GPTBot, ClaudeBot, ...) do not name this scraper's ordinary browser User-Agent and none restricts `/vacancy/`.

  Discovery is a POST of the board's own search form to `/vacancy/dtlSearch.do` (`condDiv=SEARCH`, `condText=""`, `condSort=""`, `currentPageNo=N`): ten rows per page, each navigating via `fnVacancyViewNew('<32 hex>')`. The board reported 654 vacancies on 2026-11-22 (~66 pages); the scraper reads the first six pages per run (60 detail pages). Detail is `GET /vacancy/view.do?condSeq=<32 hex>` (~60-72 KB, no schema.org block): title in `#vacancyTitle`, employer in the first `.tit_box span.tit`, a summary block of `.cont > strong.tit` + `span.con` pairs, and labelled sections in `.form_wrap` (`.form_title h3` + `.view_form strong.title` + `p.cont_box`/`div.cont_box`).

  TRAPS: (1) U+200B zero-width spaces are embedded inside Khmer words, so labels are normalised (invisibles stripped) before matching and values are cleaned; (2) the Khmer address row appears TWICE - the employer's address in the summary block and the JOB CENTRE's address near the bottom - and only the first non-empty value (the employer's) is used; (3) the Khmer 'number of workers required / workplace' summary row encodes the workplace as '<vacancies> / <province>', so the province after the slash is the location and the full employer address is the fallback; (4) salaries are USD per month (sampled Khmer 'month' + '$180~$250' and '$210~$250'), the dollar sign being Cambodia's quoting convention rather than a currency conversion, so the currency is USD and pay_period is always monthly even when no amount is published; (5) the Khmer recruitment-period row reads 'dd/mm/yyyy ~ dd/mm/yyyy' - start = posting date, end = closing date, and a literal 00/00/0000 is discarded; (6) the description section is frequently the literal placeholder 'Job Descriptions Responsibilities Duties' (38 chars), so a factual description is composed from the structured fields rather than shipping the placeholder; (7) ambiguous Khmer education ('has not yet finished university', a candidate statement rather than a completed level) is deliberately left unmapped while unambiguous degrees map, and 'no experience required' maps to 0 years -> entry.

  Cambodia (KH) is seeded (country_id 7573, `country_name` 'Cambodia'; USD is the dollarised market currency) but `ref.cities` holds NO Cambodian city at all, so `SOURCE_HOME_COUNTRY["nea_gov_kh"] = "KH"` is what keeps every province on Cambodia instead of the shared global-remote location. The pre-existing Cambodia sources are `camhr_com` and `bongthom_com`.

  Verified locally: 60 fetched, 0 failures, 60 parsed, 60 cleaned, batch validation PASSED.

  Verified in CI 2026-11-22 (run 45036048939): 60 fetched, 0 fetch failures, 60 parsed, 60 inserted, 0 failed, batch validation PASSED. This source runs ACTIVE in CI.

- **`occ_com_mx`** (Mexico, occ.com.mx) - 2026-11-22. OCC Mundial is Mexico's largest job board and the first Mexican source in the corpus (a distinct inventory from the existing `mx_computrabajo_com` and `empleo_gob_mx`). No key, no registration, no login, no cookie, no proxy; TLS verification stays ON (no verify=False). robots.txt on https://www.occ.com.mx/robots.txt (HTTP 200) is the generic `User-agent: *` group: it disallows `/rest` and the account/help paths and allows `/rest?server=jobs|jobProfiles|relatedSearches`; `/empleos/` (the listing this scraper reads) is not restricted.
  The listing is behind a Cloudflare managed challenge that plain HTTP answers with a 403/shell; an undetected Chrome (seleniumbase UC, headless) clears it in about five seconds, so the browser framework's client is used for the LISTING ONLY. Discovery cannot be anchor-based: every result is `<li class="vacancy-card" data-id="...">` and the card navigates with JavaScript, so there is no `<a href>` to follow; instead each rendered listing page publishes a well-formed schema.org `ItemList` JSON-LD block whose `itemListElement[].url` values are the canonical ads. Four listing pages are read per run (18-20 cards each; pagination observed to page 499).
  Detail is browserless: `GET https://oferta.occ.com.mx/offer/<id>/d/j?ipo=41&iapo=1` via `curl_cffi` `impersonate="chrome"` returns HTTP 200 JSON with no challenge and no auth; the `ipo`/`iapo` params are required or the endpoint 404s. The payload's `o.*` fields are mapped through the shared HTML framework's `mapped_json_html`: `t`=title, `cn`=company, `c`/`l`=locality/state, `ld`=description HTML, `st`=posted date, `lset`=employment type ('Tiempo completo' -> full_time), `smin`/`smax`=monthly MXN salary. The page's own `JobPosting` JSON-LD is NOT used: it is PascalCase and ends in a stray `;`, so `json.loads` rejects it.
  TRAPS: (1) a hidden salary is published as `smin=smax=0`, not as a missing field, so the pair is nulled before mapping or a bogus '0 - 0' band would be stored; (2) the canonical ad URL is `o.ur` and carries a long tracking query, stripped for storage; (3) the ItemList URLs double the slash after the host (`//empleo/...`), normalised at discovery.
  Mexico is seeded (country_id 3, `country_name` 'Mexico') but `ref.cities` holds only 'Mexico City', so `SOURCE_HOME_COUNTRY["occ_com_mx"] = "MX"` is what keeps every ad on Mexico instead of the shared global-remote location. The MXN to USD reference rate was added to `salary_standardization._USD_CONVERSION_RATES` (1 MXN = 0.0524458 USD, 20 Nov 2026) so `normalized_annual_*` are populated.
  Verified locally: 60 fetched, 0 failures, 60 parsed, 60 cleaned, batch validation PASSED, 60 inserted, 0 failed.
  Verified in CI 2026-11-22 (run 45041534225, Scrape (browser), max_jobs=20): 20 fetched, 0 fetch failures, 20 parsed, 20 inserted, 0 failed, batch validation PASSED. This source runs ACTIVE in CI.

- **`olx_uz`** (Uzbekistan, olx.uz) - 2026-11-22. OLX.uz is a large Uzbek classifieds job board and a second inventory beside `hh_uz` (the state portal ish.mehnat.uz remains unreachable). No key, no registration, no login, no cookie, no proxy, no browser; TLS verification stays ON (no verify=False). robots.txt (HTTP 200) is the generic `User-agent: *` group: it disallows `*/search/`, `*/rss/`, `*/api/v1/offers/metadata/`, `*/api/v1/offers/*/suggested/`, `*/api/v1/offers/*/page-views/`, `*/api/v1/targeting/` and the account paths, and ends with `Allow: /`; `/rabota/` (the listing read here) is not restricted.
  The 2026-10-04 sweep measured 'HTTP 403 with anti-bot signals' and concluded a headless browser was required. That 403 is real for a plain `requests` client (both `/rabota/` and `robots.txt` answer 403, len 919), but it is a TLS/UA fingerprint block, not a challenge: `curl_cffi` with `impersonate="chrome"` returns HTTP 200, so the shared HTML framework handles it with no browser. The listing is server-rendered HTML: `https://www.olx.uz/rabota/` carries ~52 job-detail anchors per page, and pagination is the pager's own `?page={page}` query (pages 1 and 2 each returned 52 distinct ads). `job_link` is `a[href*='/obyavlenie/rabota/']`; `detail_url_pattern` `ID[0-9a-zA-Z]+\.html` keeps only the posting URLs, and `id_from_url` + `id_url_regex` `(ID[0-9a-zA-Z]+)\.html` make the board's own 'IDxxxxxx' token the stable `source_job_id`.
  Each ad page publishes a full schema.org `JobPosting` JSON-LD block, read via `detail_json_ld`: `title`, `hiringOrganization.name` (frequently 'confidential', a real signal kept verbatim), `jobLocation.address.addressLocality`/`addressRegion`/`addressCountry` ('UZ'), `description`, `datePosted`, `employmentType`, and the structured `baseSalary` (`detail_json_salary`: `currency`=`baseSalary.currency`, min/max from `baseSalary.value.minValue`/`maxValue`). OLX.uz's `baseSalary.value` carries NO `unitText`, so `pay_period` falls back to the board default 'monthly'; the ad's own currency wins per record (two ads state USD, the rest UZS).
  Uzbekistan is seeded (country_id 3851, `country_name` 'Uzbekistan', currency UZS id 3570) but `ref.cities` holds NO Uzbek city at all, so `SOURCE_HOME_COUNTRY["olx_uz"] = "UZ"` is what pins every ad to Uzbekistan; the Cyrillic locality stays as raw text ('Tashkent, UZ'). A UZS-to-USD reference rate was added to `salary_standardization._USD_CONVERSION_RATES` (1 UZS = 0.0000834173 USD, 1 USD = 11,987.91 UZS, 22 Nov 2026) so `normalized_annual_*` are populated.
  Verified locally: 60 fetched, 0 fetch failures, 53 parsed, 53 cleaned, batch validation PASSED, 53 inserted, 0 failed (7 ads dropped under the 80-char description floor; 53/53 resolved to Uzbekistan, 51 UZS + 2 USD, 41 full_time / 12 temporary).
  Verified in CI 2026-11-22 (run 45043200430, Scrape (HTML)): 60 fetched, 0 fetch failures, 52 parsed, 52 inserted, 0 failed, batch validation PASSED. This source runs ACTIVE in CI.

- **`pracuj_pl`** (Poland, pracuj.pl) - 2026-11-22. Pracuj.pl is the largest Polish job board and a distinct inventory beside the already-built `praca_pl` and `olx_pl`. No key, no registration, no login, no cookie, no proxy; TLS verification stays ON (no verify=False). Both the homepage and robots.txt answer Cloudflare's managed challenge ('Just a moment...') to plain `requests` and to `curl_cffi` under every browser profile, so this is a BROWSER source on the generic browser framework (`scripts/run_browser_scraper.py`, SeleniumBase undetected Chrome, headless); a real undetected Chrome clears the challenge in about 10-16 s. robots.txt, read through the cleared browser, is the generic `User-agent: *` group: it disallows only asset and account paths (`/_styles/`, `/_scripts/`, `/_images/`, `/_images-app/`, `/templates/`, `/_includes/`, `/_files/`, `/L/`, `/l/`, `/konto/`, `/mpimages/`, `/oferty-loga-firm/`, `/kompendium-hr/files/` and `images/`, `/e-pracodawcy/files/` and `images/`, `/e-praktyki/files/` and `images/`) and points at the `/SiteMaps/` index; `/praca` and the `,oferta,` ad pages are allowed.

  The listing is `/praca` (rendered after the challenge clears), with `listing_ready_selector` `a[href*=',oferta,']`; pagination is `?pn={page}`, and `?page=2` silently returns page 1, so the page parameter matters. `job_link` is `a[href*=',oferta,']`; an ad URL is `/praca/<slug>,oferta,<numeric id>`, `detail_url_pattern` is `,oferta,\d+`, and `id_url_regex` `,oferta,(\d+)` makes the numeric id the stable `source_job_id`. Each ad publishes a schema.org `JobPosting` JSON-LD block whose `@context` key is literally `@content` (a site quirk the JSON-LD reader tolerates), read via `detail_json_ld` + `detail_json_map`: `title`, `hiringOrganization` (always a bare string in a 10/10 sample), `jobLocation.address.addressLocality`/`addressRegion`/`addressCountry` (e.g. 'Warszawa, mazowieckie, Polska'), `datePosted`, and `employmentType`. `description` is null on about four ads in five, so the body is assembled from `description` plus `responsibilities`/`experienceRequirements`/`jobBenefits`.

  `detail_json_salary` reads `baseSalary.currency`/`minValue`/`maxValue`/`value`/`unitText`; about a third of ads disclose pay, in PLN monthly (the board itself labels an hourly-looking 28.70 zl as '/ mies.'), so `currency_iso_code` is PLN and `pay_period` is monthly. `employmentType` carries the Polish contract name (`umowa o prace`, `kontrakt B2B`, `umowa o staz / praktyki`); the shared cleaner does not map Polish contract names, so `employment_type` is NULL, as on `praca_pl`. Rendered pages keep a Cloudflare `challenge-platform` script after the challenge clears, so `ignore_challenge_markers` is `challenge-platform` and `uc_reconnect_seconds` is 0 (`uc_open_with_reconnect` made the challenge repeat). `inter_request_delay_seconds` is 2.0, `max_pages` 3 and `max_jobs_per_run` 60.

  Poland is already seeded (country_id 19, `country_name` 'Poland', default currency PLN id 19), so no country or currency seed was needed. `SOURCE_HOME_COUNTRY["pracuj_pl"] = "PL"` pins ads that omit an address. `ref.cities` seeds only one Polish city ('Warsaw') and no Polish region spellings, so the resolver's country fallback (`match_method=source_default_country`) puts every ad on the shared country-level PL location row (location_id 98, shared with `praca_pl`/`olx_pl`); the job's own `remote_work_type_id` stays NULL, so no ad is claimed remote. A PLN-to-USD reference rate was added to `salary_standardization._USD_CONVERSION_RATES` (1 PLN = 0.2463054 USD, 1 USD = 4.06 PLN, 22 Nov 2026) so `normalized_annual_*` are populated.

  Verified locally 2026-11-22: 60 fetched, 0 fetch failures, 60 parsed, 60 cleaned, batch validation PASSED, 60 inserted, 0 failed (60/60 country PL, currency PLN monthly, 21 ads with a salary, min 28.70 / max 16,000.00 PLN, posting dates 2026-05-22..2026-11-22).

  Verified in CI 2026-11-22 (run 45049477876, Scrape (browser), max_jobs=60): 60 fetched, 0 fetch failures, 60 parsed, 60 inserted, 0 failed, batch validation PASSED. This source runs ACTIVE in CI.

- **`robota_ua`** (Ukraine, robota.ua) - 2026-11-28. Robota.ua is the largest Ukrainian job board, and Ukraine's first source on the platform. No key, no registration, no login, no cookie, no proxy; TLS verification stays ON (no verify=False). The public website and its robots.txt sit behind Cloudflare and answer HTTP 403 'Just a moment...' to a plain client, so every call goes through `curl_cffi` impersonating Chrome, which clears it and returns HTTP 200.

  Compliance: the API host's own robots.txt (`https://dracula.robota.ua/robots.txt`, HTTP 200) is a generic `User-agent: *` group that only disallows `/swagger`, `/ui` and `/playground`, so `/graphql` is allowed; the website robots.txt (read through the cleared client) is a generic `User-agent: *` group that disallows only `/data/content/`, `/cvphotos/`, `/banner.aspx` and `/Export/*`, and its one `JoobleBot` group (`Disallow: /`) does not apply to us. `/vacancy/{id}` and the SPA discovery path are allowed.

  The API: discovery and detail are ONE unauthenticated GraphQL query at `https://dracula.robota.ua/graphql` (the `graphqlApi` value in the site's Angular bundle). `publishedVacancies(filter:{...}, sort:BY_DATE, pagination:{page,count})` returns `totalCount` and items carrying `title`, `fullDescription` (full HTML), `description` (~250-char snippet), `salary`, `company`, `city {name, region {name}}`, `address`, `schedules`, `subrubrics`, `employmentTypes`, `workTypes`, `sortDate`/`createdAt`/`firstPublishedAt`, `isActive`, `anonymous`, `isAgency` and `formApplyCustomUrl`. `totalCount` was 97,981 on 2026-11-28; 100 items per page were accepted, pages did not overlap, and 12 rapid queries showed no rate limiting (a 0.5 s pause is kept as politeness).

  Field mapping: `salary` is `{amount, amountFrom, amountTo, comment, isNet, currency}` with `currency` an ISO string (`UAH` observed). `amountFrom`/`amountTo` are the range, a single-value ad fills `amount`, and a missing or non-positive bound is undisclosed, never invented; pay is quoted monthly. `workTypes` are `REMOTE`/`HYBRID`/`OFFICE`, mapped to `remote_country`/`hybrid`/`on_site` (the board is Ukraine-only, so `REMOTE` is country-scoped, not global). `employmentTypes` are `FULL_TIME`/`PART_TIME`/`PROJECT_BASED`/`SHIFT`, mapped to `full_time`/`part_time`/`contract`/`None` (`SHIFT` describes working hours, not a contract type); a multi-valued list with no single mapping stays `None` with the raw list kept in `raw_payload`. `subrubrics` are English occupation names and become the lowercased `skills`. `posting_date` is `firstPublishedAt` (7-digit fractional seconds handled), falling back to `createdAt` then `sortDate`; there is no expiry field, so `closing_date` is NULL. `company.name` and `company.logoUrl` populate the employer; an anonymous ad becomes 'Confidential Employer'. The canonical URL is `https://robota.ua/vacancy/{id}`.

  A capped run must not re-read page 1 forever on a 97k board, so the client walks newest-first, skips already-stored `source_job_ids` (the pipeline passes `repository.get_all_source_job_ids`), stops at `ROBOTA_UA_MAX_JOBS_PER_RUN` unseen ads, and caps the walk at `max_pages=20`. A board with no usable postings and no exclusions raises (query change or block), never a silent zero-row no-op; with exclusions present, zero unseen postings is the honest 'corpus covered' outcome.

  `SOURCE_HOME_COUNTRY['robota_ua']='UA'` (Ukraine is seeded as UA/UKR, country_id 24; UAH is seeded, currency_id 41) so a remote ad keeps its country. `config/sources.json` carries the `api` entry (`enabled: true`, `max_env: ROBOTA_UA_MAX_JOBS_PER_RUN`).

  Verified locally 2026-11-28: 40 fetched, 40 parsed, 40 cleaned, batch validation PASSED, 40 inserted, 0 failed (40/40 country UA, currency UAH monthly, 23 ads with a salary, 0 NULL locations).

  Verified in CI 2026-11-28 (run 46082618415, Scrape (API), max_jobs=40): 40 fetched, 40 parsed, 40 cleaned, batch validation PASSED, 40 inserted, 0 failed, exported to HF as shards/source=robota_ua/dt=2026-11-27/part-20261127T232907Z.parquet (82.8 KiB). This source runs ACTIVE in CI.

- **`skywalker_gr`** (Greece, skywalker.gr) - 2026-11-28. Skywalker.gr is the largest Greek job board (operating since 1999) and Greece's first source on the platform. No key, no registration, no login, no cookie, no proxy; TLS verification stays on.

  Compliance: robots.txt (HTTP 200, 3,785 bytes) is a generic `User-agent: *` group that disallows only account, apply, contact and storage paths (`/manage/`, `/emails/`, the `/storage/` subtrees, the candidate and company login/password pages, `/el|en/epikoinonia/`, `/*/apply`, `/*/contact`, `*/delete-account`) and lists four sitemaps; the job listing `/el/aggelies-ergasias` and the ad pages `/el/aggelia-ergasias/<id>/<slug>` are allowed, and the `*` group carries no Crawl-delay. The managed-bot `Disallow: /` groups (NavuBot, SemrushBot-SWA, WARDBot, magpie-crawler, KimiBot, CitibotSiteCrawler) and the ClaudeBot crawl-delays name other agents, not the generic `*` group that applies to us.

  The board: the listing at `https://www.skywalker.gr/el/aggelies-ergasias` is server-rendered (plain requests get HTTP 200, about 584 KB, no challenge) and paginates `?page={page}` with 25 ads per page and a pager through page 6. Every ad page, however, answers HTTP 403 with a Cloudflare 'Just a moment...' interactive challenge to plain requests and to curl_cffi impersonating chrome, chrome110, chrome120, safari17_0, edge101 and firefox133, so this is a BROWSER source (`scripts/run_browser_scraper.py`, SeleniumBase undetected Chrome); UC with a 4 s reconnect clears the challenge and renders the ad. There is no ad JSON-LD (`json_ld_job_posting` returns None), so the fields are read from the rendered HTML.

  Field mapping: the ad block is `div.this-aggelia`. The title is `.aggelia-title h3` and `title_priority` is `selector,og:title` because the page `h1` is the generic site heading. The body is `.aggelia-main` (full HTML). The location is the `.plirofories-aggelias` badge `.text-small` (a Greek municipality or region name). The remaining facts sit in `.aggelia-data .etairia` nodes shaped `<h5>label</h5><h4>value</h4>` with no stable class, so the selectors use soupsieve `:has(h5:-soup-contains(label))` to read the value beside each labelled fact: the company, the posting date (`dd-mm-yyyy`), the employment type, the work model and the category. There is no closing date, so `closing_date` stays NULL. Employment type, work model and category are Greek words; `ref.employment_types`, `ref.remote_work_types` and `ref.job_categories` have no Greek mapping, so those codes stay NULL rather than being guessed (the same as the Estonian `tootukassa_ee`).

  Chrome and challenge handling: the ad page carries a passive reCAPTCHA widget (`g-recaptcha`) and a Cloudflare `challenge-platform` script, so both are named in `ignore_challenge_markers` (the default marker list would otherwise reject a page that rendered fine; every other built-in marker and every explicit `challenge_markers` entry still fires). `uc_reconnect_seconds` is 4, `headless` is true and `scroll_count` is 2. The `/apply` and 'small ads' (`/el/mikri-aggelia-ergasias/`) links are excluded from discovery. A recent-ads RSS feed exists at `/el/xml/aggelies-ergasias` (allowed) but carries only a ~150-character teaser, so the ad pages are read for the full body.

  `SOURCE_HOME_COUNTRY['skywalker_gr']='GR'` (Greece is already seeded, High confidence) so an ad whose Greek location string matches no seeded place keeps its country instead of collapsing onto the shared global-remote location. `config/sources.json` carries the `browser` entry with no `browser` key (the runner is the group script), `max_env: SKYWALKER_GR_MAX_JOBS_PER_RUN` and `timeout: 75`; it is `enabled: false` (see the CI note). Currency EUR and period monthly state the market; no sampled ad published a salary, so no amount is invented.

  Verified locally 2026-11-28: a `--no-db` run fetched 20, parsed 20, cleaned 20, batch validation PASSED, 0 failures; a DB run inserted 15 rows, 0 failed, 15/15 with a posting date and 0 NULL locations, all resolved to Greece (GR).

  GitHub Actions CI run 46086335716 (browser group, commit 732b910, Scrape (browser)): the runner's datacenter IP was served the `Just a moment...` challenge on the listing page itself, the listing never exposed its ad links within the 25 s wait, and `discover_detail_paths` raised `BrowserChallengeError` with 0 records. The identical headless UC config renders the listing and the ads from a residential IP (the 4 s reconnect clears the ad challenge), so this is IP reputation, not the config. Kept BUILT (Disabled in CI) with its site config (`enabled: false`) so it runs locally and can be re-enabled when the block lifts.

- **`snagajob_com`** (United States, snagajob.com) - 2026-11-28. Snagajob is the largest US hourly-work board (roughly 150k open hourly jobs) and a source distinct from the already-built usajobs (federal) and builtin (tech). No key, no registration, no login, no cookie, no proxy; TLS verification stays on.

  Compliance: robots.txt (read through the cleared browser, because it answers the Cloudflare challenge to plain requests) is a generic `User-agent: *` group that allows the `/find-jobs/<filter>` section fronts and the `/jobs/<id>` ad pages and disallows only account and apply paths (the candidate and company registration, login and apply URLs), the internal `/cdn-cgi/` path, and every paginated or query-string listing URL (`/find-jobs?*page=*`, `/find-jobs/page-*`, `/find-jobs/*?*page=*`, `/search?q=*`, the `/find-jobs/c-*,w-*,x-*` filter combinations, `/profiles/`, `/job-search/`, `/interview-invites/`, `/interviews/`, `/employer/dynamic-page`). Because pagination is not permitted, the crawl surface is the bare `/find-jobs` plus a fixed set of allowed section fronts, and each front's first page is read. The two `Disallow: /` groups name Bixeebot and OmniExplorer_Bot, not the generic `*` group that applies to us, and no Crawl-delay is present.

  The board: www.snagajob.com sits behind a Cloudflare managed challenge ('Just a moment...') that answers plain requests and curl_cffi (chrome124, chrome131, safari17_0, edge101, firefox133) with HTTP 403, robots.txt included; a real undetected Chrome clears it (uc_reconnect_seconds=4, headless, `uc_mode`), so this is a BROWSER source on the generic browser framework (`scripts/run_browser_scraper.py`, SeleniumBase undetected Chrome). Discovery uses the framework's new `BrowserSiteConfig.listing_paths` list: because the board's robots.txt forbids every paginated and query-string URL, discovery walks the bare `/find-jobs` plus 37 allowed section fronts (the 12 industry `i-*` fronts and 25 job-type `t-*` fronts), reads each front's first page (about 30-35 ads), and de-duplicates the `/jobs/<id>` links across every seed. The numeric id in the URL is the stable `source_job_id`. The ads publish no JSON-LD block, and there is no infinite scroll or 'load more' control, so the rendered first page is the whole listing per front.

  Field mapping: the ad block is the rendered page. The title is `h1` (`title_priority: h1,og:title,title-tag,selector`; there is no og:title). The employer is `.company__name`, the location `.company__address` (a street address plus 'City, ST zip'), and the body `div.job-description` (a full HTML description). The posting date is `.posting-details` with `posted_date_regex` `\d{4}-\d{2}-\d{2}` (the line reads 'Posting ID: ... Posted: 2026-11-27 Job Title: ...'). Employment type and pay come from the ad's own summary table rows, addressed with soupsieve `:has(th:-soup-contains(...))`: the 'Hours' row (e.g. 'Full-time, Part-time' -> full_time/part_time) and the 'Estimated Pay' row (e.g. '$14 per hour'). `salary_text_regex` reads the hourly '$N per hour' text into `salary_min` and `salary_unit_text=HOUR`; about two thirds of ads disclose pay in this shape. The board's default `pay_period` is hourly and currency USD; an ad that states its own unit overrides the default. There is no closing date, so `closing_date` stays NULL.

  `SOURCE_HOME_COUNTRY['snagajob_com']='US'` (the United States is already seeded) so an ad whose street-plus-town location resolves to no seeded city keeps its country instead of collapsing onto the shared global-remote location. `config/sources.json` carries the `browser` entry with no `browser` key (the runner is the group script), `max_env: SNAGAJOB_COM_MAX_JOBS_PER_RUN` and `timeout: 90`; it is `enabled: false` (see the CI note). Currency USD and period hourly state the market.

  Verified locally 2026-11-28: a `--no-db` run fetched 20, parsed 20, cleaned 20, batch validation PASSED, 0 failures; a DB run fetched 60, parsed 60, cleaned 60, batch validation PASSED, 60 inserted, 0 failed, 60/60 with a posting date and 0 NULL locations (all resolved to the United States), 42/60 with a disclosed hourly USD salary.

  GitHub Actions CI run 46090761625 (browser group, commit 2e9f4e6, Scrape (browser)): the runner's datacenter IP rendered the listing fronts (30 + 9 ad links discovered across `/find-jobs` and `/find-jobs/i-customer+service`) but the first detail page `/jobs/1318441463` was served a Cloudflare challenge (matched 'challenge-platform') and every ad fetch aborted, so the run collected 0 records (batch validation FAILED, 0 inserted). The identical headless UC config renders both the listing and the ads from a residential IP, so this is IP reputation, not the config. Kept BUILT (Disabled in CI) with its site config (`enabled: false`) so it runs locally and can be re-enabled when the block lifts.

- **`subito_it`** (Italy, subito.it) - 2026-11-28. Subito.it is Italy's largest general classifieds board and its Lavoro e servizi section carries the country's biggest pool of local job ads (about 37,000 live offerte-lavoro listings); it is Italy's second built source after the state portal cliclavoro_gov_it. No key, no registration, no login, no cookie, no proxy; TLS verification stays on.

  Compliance: robots.txt (590 bytes, HTTP 200) is a generic `User-agent: *` group. It opens with a comment ("It is expressively forbidden to use search robots or other automatic methods to access Subito.it."), but a comment is not an RFC 9309 directive, so only the Disallow lines bind: `/ai?preselect`, `/pr/`, `/ai/verify/`, `/vf/`, `/expaypalcheckout/`, `/paypalcheckout/`, `/ai/load/`, `/annunciutente/`, `/annunciutente-mobile/`, `/lim?`, `/li?`, `/vim/`, `/vi/`, `/hades/`, every paginated URL (`*/?o=*` and `*&o=*`) and `/utente/`. A second group (`User-agent: grapeshot`) is not us, and no Crawl-delay is present. The owner reviewed the anti-automation comment and approved building on the RFC 9309 directives only (the Disallow lines), on 2026-11-28. Because the `?o=` pager is disallowed, the crawl never paginates: it reads page 1 of each allowed front only.

  The board: www.subito.it sits behind Akamai; plain requests (robots.txt included) get HTTP 403 'Access Denied' (server AkamaiGHost, errors.edgesuite.net) while curl_cffi impersonating Chrome gets 200, so this is an HTML source on the generic framework (`scripts/run_html_scraper.py`) with `impersonate=chrome`. The listing renders no server-side anchors but ships its whole payload in `__NEXT_DATA__` under `props.pageProps.initialState.items.originalList` (30 ads per front). The national front is `/annunci-italia/vendita/offerte-lavoro/` (about 37,000 live ads) and each of Italy's 20 regions has its own `/annunci-<region>/vendita/offerte-lavoro/` front; discovery walks page 1 of the national front plus page 1 of every regional front via the framework's new `SiteConfig.listing_paths` list, de-duplicating ads across all fronts by canonical URL. `cerco-lavoro` (candidates seeking work) is deliberately excluded. The stable `source_job_id` is the numeric ad id in the URL (`id_from_url` with `id_url_regex` `-(\d+)\.htm$`) and `urls.default` is the canonical ad URL.

  Field mapping: because each listing ad already carries the full posting, `detail_json_from_listing=true` maps it with no detail fetch (`detail_json_map`): title `subject`, employer `advertiser.name` (blank on some ads, so 27 of the 60 stored locally became 'Unknown employer'), location `geo.town.value` + `geo.city.value` + `geo.region.value`, employment type `features./contract_type.values[].value`, description `body` (75-1,988 chars) and posted date `date` (a `YYYY-MM-DD HH:MM:SS` string). Salary is deliberately NOT mapped: no sampled ad published a price, so pay stays undisclosed rather than guessed; currency is EUR and pay period monthly for ads whose body mentions pay.

  `SOURCE_HOME_COUNTRY['subito_it']='IT'` (Italy is already seeded, country_id 10) so an ad whose Italian town/province/region string matches no seeded city keeps its country instead of collapsing onto the shared global-remote location; Italy's towns are not in `ref.cities`, so every ad folds into the country-level Italy location row (location_id 575) with the per-ad town/province/region preserved in `core.location_aliases`. `config/sources.json` carries the `html` entry (`script: scripts/run_html_scraper.py`, no `browser` key), `max_env: SUBITO_IT_MAX_JOBS_PER_RUN` and `timeout: 60`; it is `enabled: true`. Currency EUR and period monthly state the market.

  Verified locally 2026-11-28: a `--no-db` run of 5 parsed 5 with 0 failures and batch validation PASSED; a deeper `--no-db` run of 70 found 86 ads across the national, Abruzzo and Basilicata fronts (70 parsed, 0 failures, de-duplication working); a DB run fetched 60, parsed 60, cleaned 60, batch validation PASSED, 60 inserted, 0 failed, all 60 rows country IT with descriptions of 75-1,988 chars and 8 employer rows.

  GitHub Actions CI run 46128141632 (html group, commit 0e4c84d, Scrape (HTML)): success. The runner fetched 60 ads (30 on the national front, 29 new on Abruzzo, 1 new on Basilicata), dropped 1 record whose description was 23 characters, parsed 59, batch validation PASSED, inserted 59, 0 failed, and exported `shards/source=subito_it/dt=2026-11-28/part-20261128T085834Z.parquet` (79.8 KiB).

  Kept BUILT (Active in CI): the source runs both locally and from the CI datacenter IP with no block, and never touches a disallowed path.
