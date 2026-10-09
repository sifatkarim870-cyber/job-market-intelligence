"""Probe a wide list of candidate Greenhouse board slugs.

Greenhouse is the highest-leverage free source here because ONE code path
covers any company that runs on it -- so the marginal cost of another 50
companies is one line in config, not a new scraper. This finds which slugs
actually exist and how many postings each carries, so DEFAULT_COMPANY_SLUGS
holds only verified values instead of guesses.

Run:  uv run python scripts/probe_greenhouse_boards.py
"""

from __future__ import annotations

from job_market_intel.common.http_client import (
    PermanentHTTPError,
    TransientHTTPError,
    fetch_json,
)

#: Well-known companies that use Greenhouse for careers. Guesses are fine --
#: a wrong slug costs one HTTP request and is reported as MISSING.
CANDIDATES: list[str] = [
    "gitlab", "stripe", "datadog", "reddit",
    "gitlablab", "openai", "anthropic", "scaleai", "cohere", "huggingface",
    "figma", "notion", "airtable", "zapier", "gusto", "brex", "ramp",
    "plaid", "robinhood", "coinbase", "kraken", "chainalysis",
    "cloudflare", "hashicorp", "elastic", "mongodb", "confluent", "snowflake",
    "segment", "amplitude", "mixpanel", "posthog", "heap", "intercom",
    "zendesk", "hubspot", "asana", "miro", "algolia", "typeform",
    "sentry", "sourcegraph", "grafana", "circleci", "buildkite",
    "netlify", "vercel", "render", "fly", "railway", "supabase",
    "prisma", "dbt", "fivetran", "airbyte", "dagster", "prefect",
    "weightsandbiases", "scale", "modal", "banana", "replit",
    "1password", "crowdstrike", "paloaltonetworks", "fortinet", "okta",
    "auth0", "snyk", "veracode", "checkout", "twilio", "sendgrid",
    "databricks", "snowplow", "segmentio", "rust", "foundationdb",
]


def main() -> int:
    good: list[tuple[str, int]] = []
    missing: list[str] = []
    total = 0
    for slug in CANDIDATES:
        url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
        try:
            payload = fetch_json(url, timeout_seconds=20.0)
            jobs = payload.get("jobs") if isinstance(payload, dict) else None
            if isinstance(jobs, list):
                good.append((slug, len(jobs)))
                total += len(jobs)
                print(f"  OK       {slug:<22}{len(jobs):>6} postings")
            else:
                missing.append(slug)
                print(f"  EMPTY    {slug}")
        except PermanentHTTPError:
            missing.append(slug)
            print(f"  MISSING  {slug}")
        except (TransientHTTPError, Exception):  # noqa: B014 - probing many hosts
            missing.append(slug)
            print(f"  ERR      {slug}")

    good.sort(key=lambda kv: -kv[1])
    print(f"\n=== {len(good)}/{len(CANDIDATES)} boards resolve, {total:,} postings total ===")
    print("\nPaste into DEFAULT_COMPANY_SLUGS (highest volume first):")
    print(repr([slug for slug, _ in good]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
