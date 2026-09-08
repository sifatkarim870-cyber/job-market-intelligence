"""Typed model for a single raw We Work Remotely job record.

Mirrors the role ``scrapers/remoteok/models.py`` plays for RemoteOK: this
is the raw, source-specific shape of the data, one step before cleaning
(``cleaning/weworkremotely_cleaner.py``) maps it onto the shared
``CleanedJob`` contract. Where RemoteOK's raw model is a close-to-1:1
alias mapping of RemoteOK's own JSON field names, We Work Remotely's RSS
feed needs real transformation to get from "what the feed literally
sends" to "a usable, typed record" — confirmed by fetching the live feed
directly (not assumed from documentation), the structural differences
are:

    - No numeric per-posting ID anywhere. ``guid`` and ``link`` are both
      the job's full canonical URL
      (e.g. ``https://weworkremotely.com/remote-jobs/acme-corp-engineer``).
      ``source_job_id`` is derived from the URL's trailing slug — see
      ``_extract_slug_from_guid`` below.
    - ``<title>`` combines company and job title into one string
      (``"Company: Job Title"``) rather than sending them as separate
      fields — split in ``_split_company_and_title`` below.
    - ``<skills>`` is a single comma-separated string (often empty), not
      a JSON array — split in ``_split_comma_separated_skills`` below.
    - Dates (``<pubDate>``, ``<expires_at>``) are RFC 822 strings (e.g.
      ``"Tue, 25 Aug 2026 07:31:11 +0000"``), not ISO-8601 — a
      genuinely different parser is needed; see
      ``_parse_rfc822_date`` below.
    - There is no structured salary field anywhere in the feed. Any
      salary mentioned on a posting lives only in free text inside the
      HTML description. This model therefore has no ``salary_min``/
      ``salary_max`` fields at all — extracting a figure from free text
      is an NLP task belonging to a later phase (skill extraction /
      salary standardization), not something this raw model or the
      cleaner built on top of it attempts.
    - WWR provides an explicit ``<expires_at>`` (posting expiration) that
      RemoteOK's feed never offered — modeled here as ``closing_date``,
      which ``CleanedJob`` now also carries (see that model's docstring).
    - Location arrives as three separate, unresolved signals
      (``region``, ``country``, ``state``) rather than RemoteOK's single
      ``location`` string. All three are kept as raw, uninterpreted
      optional fields — no attempt is made here to judge which is most
      reliable (``state`` looked inconsistent with the company's
      described location on some live-feed samples, e.g. a Delaware
      value on a New York-headquartered company's posting — possibly
      incorporation state rather than work location, but that's a
      resolution judgment call for Step 28 geographic normalization, not
      this step).

Field requirements below reflect what We Work Remotely's live feed
actually returns, confirmed by fetching it directly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RawWWRJob(BaseModel):
    """A single validated job record as returned by We Work Remotely's RSS feed.

    Attributes:
        source_job_id: Derived from We Work Remotely's ``guid`` (the
            job's canonical URL) — the URL's trailing slug, since the
            feed has no separate numeric identifier. Paired with the WWR
            ``source_id`` for deduplication, same as every other source.
        job_title: The raw, unmodified job title, split out of WWR's
            combined ``"Company: Job Title"`` string.
        company_name: The raw, unmodified employer name, split out the
            same way. Canonical company resolution is a later, separate
            step (Step 25), same as every other source.
        company_logo_url: URL to the company's logo image, from the
            feed's optional ``<media:content>`` element. Not every
            posting includes one.
        skills: We Work Remotely's own free-text skill list, split from
            the feed's single comma-separated ``<skills>`` string. Often
            empty. Still free-text at this point, same treatment as
            RemoteOK's ``tags`` — skill extraction (Step 24) resolves
            these onto ``ref.skills`` rows later.
        region_raw: WWR's broad remote-work region string (e.g.
            "Anywhere in the World"), unparsed.
        country_raw: WWR's comma-separated eligible-country list (often
            includes flag emoji), unparsed.
        state_raw: WWR's "state" string. Reliability unconfirmed — see
            the module docstring. Kept raw and uninterpreted.
        category_raw: WWR's own job-category label (e.g. "Sales and
            Marketing", "DevOps and Sysadmin"). Raw hint; resolving this
            onto ``ref.job_categories`` is a later normalization step.
        employment_type_raw: WWR's employment-type label (e.g.
            "Full-Time", "Contract"). Same treatment as
            ``category_raw`` — raw hint, not yet resolved.
        description_raw: The full, unmodified job description as HTML.
            Cleaning/HTML-stripping happens in the cleaner, not here.
        original_url: The canonical URL of the job posting on We Work
            Remotely (WWR's ``<link>``). Required — a job record with no
            URL cannot be traced back to its source.
        posting_date: The UTC timestamp WWR reports for when the job was
            posted, parsed from ``<pubDate>``'s RFC 822 format.
        closing_date: The UTC timestamp WWR reports for when the posting
            expires, parsed from ``<expires_at>``'s RFC 822 format. A
            field RemoteOK's feed never provided.
        raw_payload: The complete, unmodified raw dictionary for this job
            exactly as ``WWRClient`` extracted it from the XML. Kept for
            auditability, same principle as every other source.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    source_job_id: str = Field(alias="guid", min_length=1)
    job_title: str = Field(min_length=1)
    company_name: str = Field(min_length=1)
    company_logo_url: str | None = Field(default=None, alias="media_content_url")
    skills: list[str] = Field(default_factory=list, alias="skills")
    region_raw: str | None = Field(default=None, alias="region")
    country_raw: str | None = Field(default=None, alias="country")
    state_raw: str | None = Field(default=None, alias="state")
    category_raw: str | None = Field(default=None, alias="category")
    employment_type_raw: str | None = Field(default=None, alias="type")
    description_raw: str | None = Field(default=None, alias="description")
    original_url: str = Field(alias="link", min_length=1)
    posting_date: datetime | None = Field(default=None, alias="pubdate")
    closing_date: datetime | None = Field(default=None, alias="expires_at")
    raw_payload: dict = Field(default_factory=dict, exclude=False)

    @model_validator(mode="before")
    @classmethod
    def _split_company_and_title(cls, data: object) -> object:
        """Split WWR's combined ``"Company: Job Title"`` string.

        Splits on the FIRST ``": "`` (colon + space, not a bare colon) to
        minimize the chance of a false split inside a title that happens
        to contain a colon without a following space. Every item on the
        live feed observed while building this scraper followed the
        "Company: Job Title" pattern.

        If ``job_title``/``company_name`` are already present in the
        input (e.g. a test constructing a ``RawWWRJob`` directly), this
        is a no-op — explicit values win and no split is attempted.

        A title with no recognizable separator raises ``ValueError``,
        which Pydantic surfaces as a ``ValidationError`` — the parser's
        existing skip-and-log-don't-crash handling
        (see ``parser.py``) applies naturally, same as any other
        malformed record.
        """
        if not isinstance(data, dict):
            return data
        if "job_title" in data and "company_name" in data:
            return data
        raw_title = data.get("title")
        if not isinstance(raw_title, str) or ": " not in raw_title:
            raise ValueError(
                "Could not split We Work Remotely title into company and "
                f"job title (expected 'Company: Job Title' format): {raw_title!r}"
            )
        company_name, _, job_title = raw_title.partition(": ")
        data = dict(data)
        data["company_name"] = company_name.strip()
        data["job_title"] = job_title.strip()
        return data

    @field_validator("source_job_id", mode="before")
    @classmethod
    def _extract_slug_from_guid(cls, value: object) -> str:
        """Derive source_job_id from WWR's guid/link URL.

        We Work Remotely's feed has no numeric per-posting ID anywhere
        (confirmed by inspecting the live feed) — ``guid`` and ``link``
        are both the job's full canonical URL. The URL's trailing path
        segment (the slug) is WWR's closest equivalent to RemoteOK's
        numeric ``id`` and is what the ``(source_id, source_job_id)``
        dedup key uses for this source.

        If the value has no ``"/"`` in it at all (e.g. a test
        constructing this model with an already-plain identifier), it's
        returned unchanged — this validator only *extracts from* a
        URL-shaped value, it never invents structure that isn't there.
        """
        if not isinstance(value, str) or not value.strip():
            raise ValueError("guid/source_job_id must be a non-empty string")
        slug = value.strip().rstrip("/").rsplit("/", 1)[-1]
        if not slug:
            raise ValueError(f"Could not extract a slug from guid: {value!r}")
        return slug

    @field_validator("skills", mode="before")
    @classmethod
    def _split_comma_separated_skills(cls, value: object) -> list[str]:
        """Split WWR's single comma-separated ``<skills>`` string into a list.

        WWR sends skills as one string (e.g. ``"Python, Django, AWS"``),
        often empty, not a JSON array like RemoteOK's ``tags``. Splits on
        comma and strips whitespace here so every downstream consumer
        sees a plain ``list[str]``, matching what ``CleanedJob.skills``
        expects. Individual entries are NOT lowercased or deduplicated
        here — that's cleaning's job (see ``weworkremotely_cleaner.py``),
        matching the parser/cleaner boundary RemoteOK already
        established.
        """
        if value is None:
            return []
        if isinstance(value, list):
            return [str(entry) for entry in value]
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return []

    @field_validator("posting_date", "closing_date", mode="before")
    @classmethod
    def _parse_rfc822_date(cls, value: object) -> datetime | None:
        """Parse WWR's RFC 822 date strings into a timezone-aware UTC datetime.

        WWR's ``<pubDate>``/``<expires_at>`` fields use RFC 822 format
        (e.g. ``"Tue, 25 Aug 2026 07:31:11 +0000"``), the RSS 2.0
        convention — genuinely different from RemoteOK's ISO-8601
        format, so ``datetime.fromisoformat`` (what RemoteOK's parser
        uses) would not parse these correctly.
        ``email.utils.parsedate_to_datetime`` is the stdlib's built-in
        RFC 822 parser (written for email headers, which use the same
        date format) and already returns a timezone-aware datetime when
        the string includes a UTC offset, as every WWR date observed on
        the live feed does. Returns ``None`` (rather than raising) for
        anything unparseable, matching RemoteOK's skip-don't-crash
        philosophy for dates — a missing posting or closing date is
        recoverable downstream, a missing job title or URL is not.
        """
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        if isinstance(value, str):
            try:
                parsed = parsedate_to_datetime(value)
            except (TypeError, ValueError):
                return None
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        return None
