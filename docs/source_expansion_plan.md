# Source expansion plan — 2026-10-14

Triages the two candidate lists now on hand against the corpus's actual
coverage gaps, and records the compliance decision that governs all of it.

**Inputs**

| List | Size | Nature |
|---|---:|---|
| `DataBase/job_sites_by_country_SCRAPEABILITY.xlsx` | 325 probed domains | technical classification, built by probing homepages |
| `WebsiteToScrape.docx` | 200 named sites, 13 regions | project owner's curated shortlist |
| overlap already built | 9 | Indeed (×3), Reed, RemoteOK, Remotive, WWR, TheMuse, Himalayas |

**Starting position:** the corpus is **68.2% Iran / 66.3% Persian**, and only
**7 countries hold 1% or more** of rows. That, not raw row count, is the
constraint. More Iranian or Southeast-Asian volume makes it worse.

---

## 1. Compliance decision (item 1)

The project owner has reviewed the candidate list and states these are sites
they are willing to scrape. That is the decision, and it is recorded here so
the reasoning is not relitigated per source.

What was measured, so the decision is made on facts rather than on the
workbook's label:

- **No probed target disallows a research user agent on its job paths.**
  An earlier reading suggested `jobkorea`, `work_ua` and `rabota_by` were fully
  blocked; that was wrong. Their `Disallow: /` lines sit inside
  user-agent groups addressed to named bots (`GPTBot`, `ClaudeBot`,
  `anthropic-ai`, `Googlebot`, `Yandex`), not the generic `*` group. Under
  RFC 9309 group matching they permit a research crawler.
- **Unreadable policy is unknown, not permitted.** `urllib.robotparser`
  returns *allowed* when `robots.txt` cannot be read — `cv-library.co.uk`
  returns 403 and `vinnumalastofnun.is` returns 404. Any tooling built on that
  default will scrape sites whose policy it never saw. **When adding a source,
  fetch `robots.txt` explicitly and record the verdict; never let a library
  default stand in for the check.**
- **Several sites name AI crawlers as unwelcome.** `jobkorea` disallows `/` for
  GPTBot/ClaudeBot/anthropic-ai; `work.ua` for ClaudeBot. The `*` group
  permits us so the robots check passes, but this project's purpose is an AI
  training corpus, so that is the owner's call to make — made here — rather
  than something a script should quietly decide.

---

## 2. Open data is the path (item 2)

The commercial boards fail on anti-bot, not on ambition. Measured on the
free-tier targets from the workbook:

| target | homepage | listings reachable? |
|---|---|---|
| `jobbkk.com` (TH) | 200 | **no** — captcha on every listing URL |
| `merojob.com` (NP) | 200 | **no** — `/jobs` redirects to a login wall |
| `werk.nl` (NL) | 200 | **no** — 404/400 on listing paths |
| `vinnumalastofnun.is` (IS) | 200 | **no** — domain dead, redirects to `island.is` |
| `jobindex.dk` (DK) | 200 | partly — 44 job links, 1 detail link |

Four of five cannot be scraped. Government employment portals and open-data
feeds do not have this problem: they publish machine-readable feeds precisely
so people can use them. The docx list is strong on exactly these — USAJOBS,
France Travail, Bundesagentur, Arbetsförmedlingen, NAV, Eluta, Job Bank,
MyCareersFuture, EURES.

**The single most important constraint: every one of these needs an account I
cannot create.** The scrapers can be written, but they go live the moment you
paste a key.

---

## 3. The ranked plan

### Tier A — built, no credentials required ✅

**Greenhouse: 30 → 96 verified boards** (PR #10). One ATS, one code path, no
key, no anti-bot. These boards are US/UK/Canada/DACH-heavy — precisely the
missing coverage.

And the fix mattered more than the list: the walk was spending its entire
1,000-row budget on the two largest boards, so **94 of 96 boards had never
been fetched in any run, ever**. Rotation means the existing CI budget now
covers the whole list over a cycle.

### Tier B — one free registration each, biggest coverage gain

| Source | Coverage | Key | Why first |
|---|---|---|---|
| **Adzuna** | **~11 countries** (GB, FR, DE, IN, CA, AU, US, NL, BR, MX, PL, RU) | free `app_id`/`app_key` at adzuna.com | **Highest leverage remaining.** One integration resolves more countries than any other source on either list. |
| **USAJOBS** | US federal | free `Authorization-Key` at data.usajobs.gov | US is 2.8% of the corpus. Endpoint confirmed live (401 without a key = alive). |

Both are verified-live-but-credential-gated, not guesses. Adzuna returns 400
without credentials; USAJOBS returns 401. Both are one env var away.

### Tier C — government open data, worth investigating

| Source | Country | Status |
|---|---|---|
| France Travail | FR | official API, free `client_id`; SPA currently intercepts the API host — needs the documented base URL |
| Arbetsförmedlingen | SE | `jobsearch.api.jobtechdev.se`, keyless; 404 on the paths tried — endpoint may have moved |
| NAV | NO | **dropped 2026-10-15 — no public feed exists.** `nav.no` is a Next.js SPA; its 120 KB job-search page carries zero job records. The only feed-shaped endpoints are a 4-item news RSS and a 15,099-URL **CMS** sitemap whose 1,742 job-ish URLs are labour-market statistics tables, not postings. Vacancies sit behind an employer login. The earlier "public feed" note was the wrong inference from correct 404s. See `source_requirements.md`. |
| Job Bank / Eluta | CA | government; `jobbank.gc.ca/api/jobsearch` returned 404 — may be retired |
| Bundesagentur | DE | official API, now OAuth-gated (403 without a client) |
| MyCareersFuture | SG | `api.mycareersfuture.gov.sg`, needs the right path |

These need path/auth archaeology before a scraper is worth writing. Probing
them is cheap; writing scrapers speculatively is what produced the captcha-
walled dead ends in #9.

### Tier D — do not build

Captcha- or Cloudflare-walled commercial boards (most of the 134 HTML tier and
101 browser tier), and the legacy entries the docx itself flags — Stack Overflow
Jobs, GitHub Jobs, Internet Explorer. A scraper built against an interstitial
looks complete and collects nothing, which is the failure mode this project
has already hit repeatedly.

---

## 4. What I recommend next, in order

1. **Register for Adzuna and USAJOBS.** Two free accounts, five minutes. Then
   say the word and I will build both scrapers — they follow the existing
   Reed/RemoteOK `api` pattern, so each is mechanical.
2. **Run a focused probe of Tier C** with correct paths and any keys, so the
   next build decision rests on extracted records rather than on 404s.
3. **Add a `robots_verdict` field to `config/sources.json`** so every source
   carries its recorded compliance status, checked explicitly rather than
   inherited from a library default that returns *allowed* when it could not
   read anything.

One caution about coverage, stated plainly: adding sources fixes *country*
coverage faster than it fixes *balance*. Even with Adzuna, USAJOBS and Tier C
live, the corpus stays Iranian-dominated for some time, because `jobvision` at
61k rows is already larger than most single-country sources will ever be. Any
published analysis should weight or stratify by source rather than report
whole-corpus averages, and the dataset card should keep the concentration
figure at the top rather than in a footnote.