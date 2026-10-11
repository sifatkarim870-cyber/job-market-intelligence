# Which database does CI write to?

**Short answer: a new Neon project on the free account you already have. No card
needed.**

Set it once:

```bash
gh secret set CI_DATABASE_URL --body '<pooled connection string from the new project>'
```

That is the entire change. Every workflow already reads that secret.

---

## Why Neon again, when Neon already failed

The failure was never "Neon is unusable". It was **one project's quota being
spent**:

```
ERROR:  Your account or project has exceeded the quota.
```

Three facts, all from Neon's own documentation:

1. **Quotas are per project, not per account.**
   > "Compute quotas are measured per project, so 100 projects each get their
   > own 100 CU-hour bucket."
   — [Neon Free plan limits](https://neon.com/faqs/free-plan-limits-and-quotas)

   The Free plan allows **100 projects**. Exhausting one project's allowance
   does nothing to the other 99.

2. **Neon Free needs no credit card.** Stated in the same FAQ and on the
   pricing page. There is no card to be declined.

3. **Storage went UP, not down.** On 2026-10-02 Neon raised the Free plan from
   0.5 GB to **1 GB per project**, and existing projects picked it up
   automatically.

So the fix is a new project, not a new vendor. The old endpoint
(`ep-damp-band-b35ije4h`) is simply retired.

---

## Does 1 GB actually fit?

Measured on 2026-10-11 against the live database:

| Component | Size |
|---|---|
| `core.jobs` + `ref` + `salary` (identity and dedup) | 251 MB |
| `ref.*` alone (what the CI seed actually loads) | 2.6 MB |
| CI growth | 28.8 MB/day (6,400 rows × 4,721 B) |

CI does **not** need the full 1,325 MB corpus. It needs the identity slice for
deduplication plus the rows it has scraped but the laptop has not yet merged.

With `scripts/prune_exported_rows.py` running after each merge:

```
2.6 MB (ref) + 250 MB (jobs) + ~7 days of unmerged rows (~200 MB) ≈ 450 MB
```

That leaves real headroom under 1 GB. **Without pruning it would hit the cap
in about three weeks** (28.8 MB/day), which is why the prune step exists and
why it refuses to run when nothing has been merged.

---

## Why not the alternatives

Every free managed Postgres stops between 500 MB and 1 GB:

| Provider | Storage | Why not |
|---|---|---|
| **Neon Free (new project)** | **1 GB/project × 100** | **Chosen** — no card, quota is per project |
| Supabase Free | 500 MB, 2 projects | Goes **read-only at the cap**. Same wall as Neon, in ~8 days |
| Aiven Free | 1 GB, 1 service | Powers off when idle; single node |
| Render Free | 1 GB | Expires after 30 days |
| Koyeb Free | 1 GB | Sleeps after 5 minutes idle |
| Oracle Always Free | 200 GB VM | Best headroom by far, but **requires a credit card at signup** |

Oracle is the right answer on the numbers and the wrong answer on access, which
is why `scripts/provision_ci_database.sh` still exists but is not the default.
If a card ever becomes available, that path needs no code change either — it
prints the same DSN.

---

## What happens if it is not set

`CI_DATABASE_URL` unset is a supported state, not a failure:

- each job seeds a throwaway Postgres service container from the HF state
  snapshot, and discards it at the end;
- `scripts/merge_incoming_shards.py` folds those rows into the laptop on the
  next daily sync, so **nothing is lost**;
- the shards on Hugging Face are what CI actually publishes.

The cost of leaving it unset is only that CI keeps re-scraping the same boards,
because it has no persistent dedup state. The corpus still accumulates.

---

## Operating notes

- **Do not point it at the old project.** That is the endpoint whose quota is
  spent, and it will fail at the first write again.
- **Rotate before the quota is spent**, not after. 100 CU-hours is roughly
  400 hours of 0.25 CU compute; the daily scrapes use a small fraction, but a
  long-running backfill would not.
- **Seed it** from Hugging Face rather than from a dump of the laptop, so the
  schema always matches what CI is already proven to run against:

  ```bash
  uv run python scripts/restore_state_snapshot.py --source hf --dsn '<dsn>'
  ```

- **Prune after merging**, never before. A row whose shard is on HF but not yet
  merged is the only copy that exists; the prune script refuses to run when the
  merge ledger is empty for exactly that reason.