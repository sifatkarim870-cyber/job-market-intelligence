# What each candidate needs — measured 2026-10-14

Two passes, because the first one measured the wrong thing.

**Pass 1 (homepage reachability):** 54 representative sites from
`WebsiteToScrape.docx` → 23 reachable, 28 challenge-walled, 3 robots-blocked.

**Pass 2 (extracted job records):** of 15 of the "reachable" ones checked for
actual postings, only **3** returned extractable records. The rest were 404s on
guessed listing URLs, JS-rendered shells, or captcha.

Reachable homepage ≠ extractable listings. A scraper built against a homepage
that lists nothing is the dead-end pattern from #9, so pass 2 is the one that
decides anything.

## Corrected categories

| Needs | Count | What it is |
|---|---:|---|
| **Build now** | 3 | wellfound (50 detail links), jobbank/Canada (25), builtin (24) |
| **Buildable, needs URL archaeology** | ~20 | reachable, but listing path/params unknown |
| **Needs a residential proxy** | ~28 | Cloudflare/captcha/403 — Cloudflare interstitials on duunitori, jobboom, pracuj, stepstone, jobs.cz, pnet, jooble, seek, wuzzuf, naukrigulf |
| **Needs a free API key** | ~6 | Adzuna, USAJOBS, France Travail, Bundesagentur, NAV, Eluta |
| **Robots-unreadable — needs your call** | ~5 | naukri, adzuna, otta, pnet, pracuj all return 403 on robots.txt. Unreadable is *unknown*, not forbidden. |
| **Genuinely disallowed** | 1 | ziprecruiter (`Disallow: /` for our UA) |

### Correction carried forward

The first pass marked 19 sites robots-blocked. That was wrong: `jobindex`,
`naukri`, `seek`, `infojobs` and 12 others carry `Disallow: /` inside groups
addressed to named bots (GPTBot, ClaudeBot, Googlebot), not the generic `*`
group. Re-evaluated under RFC 9309 group matching, 16 of them are permitted.

---

# The answer: three things, one of which is optional

## 1. A residential proxy — unlocks the largest chunk (~28 sites)

This is the single highest-leverage item. Every Cloudflare/captcha board in
both lists needs it, and you already run one for Indeed: `.env.example`
documents `INDEED_PROXY_SERVER` / `INDEED_PROXY_USERNAME` /
`INDEED_PROXY_PASSWORD`. The same variables, generalised to a per-source
proxy setting, cover duunitori, jobboom, pracuj, stepstone, jobs.cz, pnet,
jooble, seek, wuzzuf, naukrigulf, monsterg, careerjet and the rest.

Without it those ~28 sources are not buildable at any effort level — they
return interstitials, not postings.

## 2. Free API registrations (~6 sources, biggest coverage per source)

| Service | Covers | Takes 2 min to get |
|---|---|---|
| **Adzuna** | ~11 countries in one integration | adzuna.com → `app_id`, `app_key` |
| **USAJOBS** | US federal | data.usajobs.gov → `Authorization-Key` |
| France Travail | France | francetravail.gouv.fr → `client_id` |
| Bundesagentur | Germany | arbeitsagentur.de → OAuth client |
| NAV | Norway | public feed |
| Eluta | Canada | public |

I can write all six scrapers now and leave them dark until the key lands in
`.env` — they follow the existing Reed pattern exactly. But they cannot be
*verified* end-to-end without the key, and an unverified scraper is exactly
what #9 warns about.

## 3. Nothing at all — for the ~23 reachable sites

I can start on these immediately. They need no input from you. The work is
per-site URL and selector archaeology, which is slow rather than blocked, and
I will build them in descending coverage order.

---

# What I am doing without waiting

Starting on the buildable set now, in this order:

1. **Job Bank Canada** — government (open data), 25 detail links, JSON-driven
2. **Wellfound** — global startups, 50 detail links, `__NEXT_DATA__` island
3. **Built In** — US tech, 24 detail links

Then the ~20 reachable-but-uncharactered sites, working down the list.

Every one lands through the same pipeline the project already has: client →
parser → validator → cleaner → `CleanedJob` → repository, plus a
`config/sources.json` line and `register_source.py`. No new architecture.

**The thing that would most change my plan:** the proxy. Without it I can
build ~23 of the ~57 sites in this sample. With it, ~51. That is worth an hour
of your time above everything else on this list.