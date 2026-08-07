# Handoff

Cross-agent requests and interface changes. Fable maintains this file; Sol writes requests to
`.sol/requests/<task>.md` instead.

## Interface contract status

`app/contracts.py` is frozen as of Phase 0 unless a change is recorded here with a date and a
reason. Both agents code against it.

| Shape | Consumed by | Notes |
|---|---|---|
| `Memory` | seed generator, everos clients, assembler, ablation | Seed JSON must deserialize into it field-for-field. |
| `AssembledPrompt` / `ContentBlock` | assembler → cortex clients, prompt-inspector UI | `cache_control` present ⇒ this block ends a cacheable segment. |
| `Usage` | cortex clients → cost math → ledger | `cached_tokens` is always derived, never assigned. |
| `CallRecord` / `InjectionRecord` | telemetry → SQLite and Snowflake DDL | Column names in `sql/01_ddl.sql` must match these field names. |

## Changes to contracts

_None yet._

## Open requests

_None yet._
