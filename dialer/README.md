# Dial Sheet

A click-to-call CRM for outbound calling from a phone. Sign in, import a CSV, tap a lead, talk. Your list, call history, notes and scripts live on your account, so the same data is there on any phone or computer.

## Layout

| Path | What it is |
|---|---|
| `index.html` | the whole app — one file, no build step, no framework, nothing loaded from a CDN |
| `supabase/schema.sql` | the database: tables, row-level security, new-account trigger |
| `legacy/` | the retired Google Sheets backend |

Your Supabase project URL and anon key sit in a marked block near the top of `index.html`. Both are public by design — the anon key is meant to ship in web pages, and row-level security is what protects the data. Never put the `service_role` key there.

Everything is inlined deliberately. A page served without a trailing slash (Vercel's default: `/dialer`, not `/dialer/`) resolves relative paths like `vendor/supabase.js` against the site root instead, and they 404. One file cannot have that problem, on any host, at any path.

## Deploying

It's a static site with no assets to lose. On Vercel: import the repo, framework preset **Other**, no build command, output directory `.` — the app lands at `yourdomain.com/dialer`. Any static host works the same way.

Then on the phone: open the URL, **Share → Add to Home Screen**. It runs full-screen and keeps you signed in. Dialing uses `tel:` links, so it hands off to the native dialer.

## Accounts

Anyone who opens the link can create an account with an email and a password, and they see only their own leads. Nobody needs Supabase access, an invite, or any setup.

Signup is instant because **Confirm email** is off in Supabase (Authentication → Sign In / Providers → Email). If you ever open this up beyond people you know, turn confirmation back on and attach real SMTP — Supabase's built-in mailer is rate-limited to a handful of messages an hour.

Isolation is enforced by Postgres, not by app code — see `supabase/README.md`.

## How a call goes

1. Tap the green circle → the phone dials **and** the call sheet opens.
2. The script shows with `{{tokens}}` filled in from that lead, next to a live timer and a notes box.
3. Tap an outcome. **Callback** asks for a date; **Interested** and **Meeting set** ask for a deal size.
4. **Next →** saves and opens the next lead in the queue.

Queue order: follow-ups due today → never called → interested → the rest. Not interested, bad number, do not call and meeting set drop out.

## Importing

**Import CSV** takes a dropped file, a chosen file, or rows pasted from a spreadsheet. First row is headers; you map columns on the next screen, and common names (`Company Name`, `First Name`, `Phone Number`, `Market`, `Deal Value`) are matched for you. Leads whose phone number you already have are skipped.

## The four numbers at the top

They're buttons. **Dialed** and **Picked up** open the calls behind the number — who, at what time, what happened — and tapping a row opens that lead. **Due** opens the calendar. **Pipeline** filters the list to interested leads.

A call is logged when you dial. Opening a lead to look at it does not count as a call; a note you type without dialing does get logged.

## Follow-ups and the calendar

Every call sheet offers a follow-up date, whatever the outcome — not only callbacks. The calendar icon in the header shows them on a month grid: upcoming days read green with a count, overdue days read clay and are also listed above the grid. Tap a day to see who's due, tap a lead to open it.

## Your numbers

The chart icon shows total dials, average per day, average per day you actually called, and a bar chart of dials per day over the last 30 days. Tap a bar for that day's count. The total comes from the server, so it counts every dial ever, not just what this device has cached.

## The table view

**Table** opens every lead in a grid: sort by any column, search, tap a cell to edit it in place, select rows to bulk-change status or delete. This is the spreadsheet replacement — Enter saves and drops to the row below, Escape cancels.

## Scripts

Any number of them, picked per call. Tokens filled per lead:

`{{business}}` `{{owner}}` `{{first}}` `{{metro}}` `{{location}}` `{{phone}}` `{{email}}` `{{me}}` `{{company}}` `{{offer}}`

The last three come from Settings. New accounts start with a cold-call script to edit.

## Offline

The device keeps a local copy, so the app works with no signal — calls, notes and outcomes queue up and go to your account when you're back. The icon in the header is green when everything is saved, amber when changes are waiting, red when the last attempt failed; tap it to sync now.

Signing out clears that account's local copy from the device, so nothing is left behind on a shared computer. If changes are still waiting, it warns you first.
