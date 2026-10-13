# Source feasibility re-check — 2026-10-13

Re-probed the highest-value unbuilt targets from
`DataBase/job_sites_by_country_SCRAPEABILITY.xlsx`, because "add the remaining
proposed scrapers" cannot be executed as written and the reason is worth
recording before anyone spends time on it.

## The workbook's FREE bucket is not a permission or a feasibility claim

`FREE API` in that workbook means *"the homepage returned 200 and the HTML
references an `/api/*` path"*. That is a statement about the homepage, not
about whether job postings can be read. Re-probing the targets themselves
rather than their homepages:

| target | homepage | job listings reachable? |
|---|---|---|
| `jobbkk.com` (TH) | 200 | **no** — captcha on every listing URL; 0 detail links |
| `merojob.com` (NP) | 200 | **no** — `/jobs` redirects to a login wall; 0 detail links |
| `werk.nl` (NL) | 200 | **no** — 404/400 on listing paths; 0 links |
| `vinnumalastofnun.is` (IS) | 200 | **no** — domain redirects to `island.is` and 404s |
| `jobindex.dk` (DK) | 200 | **partly** — 44 job links, but 1 detail link |

Four of five are captcha-walled, login-gated, or defunct. The fifth yields one
structured record per page.

Of the remaining 21 free-tier targets probed the same way, the same pattern
held: Cloudflare interstitials on merojob, tecoloco (×4), cv-library, and
recaptcha on jobbkk, jobs.ch, jobup.ch, rabota.by, 51job-style boards.

## robots.txt: none forbid us, but that is not the whole picture

Evaluating each file per RFC 9309 (most specific matching `User-agent` group
wins) against a research-scraper user agent, **no target disallows the job
search paths**. An earlier naive read of the same files suggested
`jobkorea`, `work_ua`, `rabota_by` and others were fully blocked — that was
wrong. Their `Disallow: /` lines sit inside groups addressed to named bots,
not the generic `*` group.

Two things are still true and are not captured by that verdict:

1. **`urllib.robotparser` defaults to permitted.** When `robots.txt` is
   unreadable — `cv-library.co.uk` returns **403**, `vinnumalastofnun.is`
   returns **404** — `RobotFileParser.can_fetch()` returns `True`. A tool that
   treats that as "allowed" will silently scrape sites it has not checked.
   Unreadable policy should be *unknown*, not *allowed*.
2. **Several sites target AI crawlers explicitly.** `jobkorea.co.kr` lists
   `Disallow: /` for `GPTBot`, `ClaudeBot` and `anthropic-ai`; `work.ua` lists
   it for `ClaudeBot`. The generic `*` group permits us, so a robots check
   passes — but this project's purpose is an AI training/forecasting corpus, so
   whether a site that names AI crawlers as unwelcome is appropriate to ingest
   is a judgement for the project owner, not something a robots check settles.

## What this means for the source plan

Current: **11 of 325** probed domains have a scraper. All 11 came from the
free tier, and all 11 work — which is why the corpus exists.

The remaining pool is not 314 straightforward additions:

- **~101 browser-tier** sites need Selenium plus a dedicated runner (shared
  runner IPs are blocked), and Indeed is already disabled for exactly this
  reason.
- **~134 HTML-tier** sites are mostly captcha- or Cloudflare-walled, which is
  what the probe found on every HTML-tier target tested.
- **the free tier is nearly exhausted in practice**, not in theory.

Adding all of them is not a bounded piece of work, and building scrapers
against sites that return interstitials produces scrapers that look complete
and collect nothing — the failure mode this project has already hit repeatedly.

## Recommended next step

Treat source expansion as gated on a per-candidate probe that records
*extracted records*, not HTTP status. `scripts/probe_free_apis.py` already
exists and is the right home for that. A candidate that cannot return at least
one record with a title and a company should not get a scraper, however many
API references its homepage mentions.

The highest-value candidates that did survive probing:

- `jobindex.dk` — the only remaining target returning structured detail links
- `werk.nl` — has a real `/api/search/suggest/` endpoint worth investigating
- `island.is` — the Icelandic government's replacement for the defunct
  `vinnumalastofnun.is`, and a public-sector jobs portal of the kind that
  tends to publish an open data feed

Countries with zero coverage and a plausible open-data feed are a better bet
than commercial boards behind captchas: Denmark, Korea, Switzerland, Nepal,
Thailand and Ukraine all have government employment portals or open-data
datasets that would sidestep the anti-bot problem entirely.