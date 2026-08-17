# Database

`schema.sql` is the whole backend. Run it once in Supabase: **SQL Editor → New query → paste → Run**. It is idempotent — re-running it after an edit is safe.

## What it creates

| Table | Holds |
|---|---|
| `leads` | one row per business, including status, follow-up date and deal value |
| `calls` | append-only call log, one row per dial |
| `scripts` | call scripts, per account |
| `profiles` | your name, company, offer line, theme |

Every table has `user_id` and row-level security. The policies say the same thing four times: *you may touch a row only when `user_id = auth.uid()`*. That check runs inside Postgres, so a bug in the app cannot leak one account's data to another. `anon` (logged out) is granted nothing at all.

New accounts are stocked automatically — a trigger on `auth.users` creates a profile and a starter cold-call script the moment someone signs up.

## Verifying isolation

`rls_test.sql` proves the policies do what they claim. Against a stock Postgres with a stub `auth` schema it checks that a second account cannot read, update, or delete the first account's rows, cannot forge a row owned by someone else, and that logged-out access is refused outright. It also checks the per-account phone dedupe: two accounts may hold the same number, one account may not hold it twice.

Run it with `psql -f rls_test.sql`. Every step marked "must ERROR" is expected to fail — that is the test passing.
