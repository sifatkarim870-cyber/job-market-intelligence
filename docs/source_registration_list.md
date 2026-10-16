# Sources that need a registration, an API key, or a proxy

Generated 2026-10-16 from `WebsiteToScrape.docx` joined against
`job_sites_by_country_SCRAPEABILITY_backup_20261007.xlsx` and a live re-probe.

Every URL below was **requested during this triage** and its HTTP status is
recorded, because reciting an API endpoint from memory is how people end up
signing up for one that has moved. Where a URL failed to resolve today, that is
said rather than quietly dropped.

Nothing on this list has been built. Nothing here needs the scraper to exist
first -- each entry is blocked purely on a credential or a network capability.

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

## B. Blocked on anti-bot, not on a credential

These need **no account**. They return HTTP 403 / a captcha challenge from this
network and would need a **residential proxy** to be scrapable at all.

| Site | Region | Observed on 2026-10-16 |
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
| BrighterMonday | Kenya | captcha challenge |
| Jobberman | Africa | captcha challenge |
| Laimoon | Middle East | HTTP 503 |

**A residential proxy unblocks more coverage than anything else on this page.**
Fourteen boards, including India's largest (Naukri), Spain's InfoJobs,
Switzerland's Jobs.ch and Russia's HeadHunter.

---

## C. JS-rendered, no anti-bot -- possible without a credential

These are reachable and not walled, but the listing is rendered client-side, so
they need a browser-based fetcher rather than plain HTTP. The project already
runs `indeed` that way, so the machinery exists.

| Site | Region |
|---|---|
| APEC | France |
| IrishJobs | Ireland |
| Jobs.ie | Ireland |
| JobScout24 | Switzerland |
| Nationale Vacaturebank | Netherlands |
| Totaljobs | UK |
| Trade Me Jobs | New Zealand |
| StepStone Germany | Germany |
| Stellenanzeigen | Germany |
| Profesia | Slovakia |
| PNet | South Africa |

---

## D. Already investigated and resolved

| Site | Outcome |
|---|---|
| NAV Norway (arbeidsplassen.nav.no) | **No public feed exists.** Vacancies sit behind an employer login. Corrected in PR #17 after the original verdict blamed a missing key. |
| Bundesagentur für Arbeit (Germany) | `jobsuche/service-api` redirects to `/jobsuche/` (HTTP 200, 134 KB) -- the "API" path is not an API. Needs its own investigation; not yet attempted. |

---

## Recommended order

1. **France Travail** -- an entire country, authoritative source, documented API.
2. **A residential proxy** -- unblocks 14 boards, several of them large national
   or regional leaders.
3. **MyCareersFuture** -- a country (UK) with thin coverage, but confirm the
   host is reachable for you first.
4. The browser-rendered group in section C, which needs no credential at all --
   only engineering time.
