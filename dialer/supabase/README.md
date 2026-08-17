# Database

`schema.sql` is the whole backend. Run it once in Supabase: **SQL Editor → New query → paste → Run**. It is idempotent — re-running it after an edit is safe.

## What it creates

| Table | Holds |
|---|---|
| `leads` | one row per business, including status, follow-up date and deal value |
| `calls` | append-only call log, one row per dial |
| `scripts` | call scripts, per account |
| `profiles` | your name, company, offer line, theme |

Every table has `user_id` and row-level security: *you may touch a row only when `user_id = auth.uid()`*. That check runs inside Postgres, so a bug in the app cannot leak one account's data to another. `anon` (logged out) is granted nothing at all.

`calls` carries a second check — the lead being logged against must also be yours. Owning the call row is not enough. Without that check an account can attach call rows to another account's leads: it exposes no data, since reads still filter by `user_id`, but it should be impossible, and it is.

New accounts are stocked automatically — a trigger on `auth.users` creates a profile and a starter cold-call script the moment someone signs up.

## Verifying isolation

`rls_test.sql` proves the policies do what they claim. Against a stock Postgres with a stub `auth` schema it checks that a second account cannot read, update, or delete the first account's rows, cannot forge a row owned by someone else, and that logged-out access is refused outright. It also checks the per-account phone dedupe: two accounts may hold the same number, one account may not hold it twice.

Run it with `psql -f rls_test.sql`. Every step marked "must ERROR" is expected to fail — that is the test passing.

The same checks were run against the live Supabase project over HTTP with two real accounts. That run is what caught the missing `calls` check.

## Clearing bad call history

`reset-call-log.sql` removes call records without touching leads. Put your email in it, run the preview first, then pick the full wipe or the gentler version that keeps calls you wrote a note on. Every statement is scoped to one account by email, so a shared project stays safe.

After running it, tap sync in the app — the deletion pulls through to the device and the numbers drop to match.
