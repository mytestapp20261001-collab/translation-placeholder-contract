# Maintenance notes

## 2026-10-22 — aggregate diagnostic budget

Current behavior adds a **10,000-finding limit per complete audit**, shared by
all locales and all four finding categories. Each emitted diagnostic counts;
one empty translation can also produce a placeholder mismatch and count twice.
Exactly 10,000 findings remain a normal complete report (CLI exit 1). A potential
10,001st finding raises `BadInput` in the API; the CLI emits only an error object
with `finding budget exceeded (10000)` and exits 2. No truncated or partial
findings report is returned. Reduce the input to smaller key/locale batches when
this limit is reached. A budget error is not a completed contract check.

Why: entry limits alone do not bound key/locale coverage diagnostics. In a
bounded synthetic local reproduction on the original release, 1,000 source keys
and 100 empty locale maps fit in 20,730 input bytes but produced 100,000 findings
and 13,490,169 output bytes. This is measured output amplification, not a claim
of a production outage or a tested million-finding failure.

`--help` also identifies the new report limit. Below the limit, report schema,
finding content/order, privacy behavior and existing input limits are unchanged.
No dependency, network action or environment integration is added.

The original README and migration receipt remain byte-for-byte historical
artifacts. This maintenance note adds the current diagnostic limit to the
README's original input limits. [The maintenance receipt](docs/MAINTENANCE_2026-10-22.json)
records only the reviewed `tool.py` and `test_tool.py` hash deltas;
[the original receipt](docs/MIGRATION.json), SKILL metadata, invitation text and
experiment allocation are not rewritten. The release validator rejects changes
to protected files and unlisted maintenance paths.
