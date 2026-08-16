# Dial Sheet

A one-file CRM + click-to-call sheet for solo outbound calling from a phone.

- **`index.html`** is the whole app — no build step, no server, no accounts, no dependencies.
- **`sheet-sync.gs`** is optional: paste it into a Google Sheet to use that spreadsheet as the lead list (see below).
- Without a sheet, all data (leads, notes, call history, scripts) is stored in **localStorage on the device that opened it**, and nothing is uploaded anywhere.

## Running it

Open `index.html` in a browser. On mobile the practical setup is:

1. Host the file somewhere you can reach from your phone (GitHub Pages, Netlify drop, any static host, or AirDrop/email the file to yourself).
2. Open the URL in Safari/Chrome on the phone.
3. **Share → Add to Home Screen.** It then launches full-screen like an app and keeps its own storage.

Dialing uses `tel:` links, so it hands off to the native phone dialer. That works in a real browser tab or a home-screen app; it can be blocked inside embedded previews/iframes, where the number is still shown with a Copy button.

## How a call goes

1. Tap the green circle on a lead → the phone starts dialing **and** the call sheet opens.
2. The call sheet shows the script with `{{tokens}}` already filled in from that lead, a live timer, and a notes box.
3. Tap an outcome (Interested / Meeting set / Callback / Voicemail / No answer / Not interested / Bad number / Do not call). Callback asks for a follow-up date; Interested and Meeting set ask for a quote/deal size.
4. **Next →** saves the call and opens the next lead in the queue.

The **Pipeline** figure in the header is the sum of deal sizes across leads sitting at Interested, Meeting set, or Callback.

Queue order: follow-ups due today → never called → interested → everything else. Closed statuses (not interested / bad number / do not call / meeting set) drop out of the queue.

## Importing

**Import CSV** takes a dropped file, a chosen file, or rows pasted straight out of a spreadsheet (tab- or comma-separated). The first row is treated as headers; you map each column to a field on the next screen. Common headers (`Company Name`, `First Name`, `Phone Number`, `Market`, …) are matched automatically. Leads whose phone number already exists are skipped.

Fields: business, owner (or first + last name), phone, email, metro area, city/location, website, quote/deal size, note.

## Scripts

Scripts live in the document icon in the header. Any number of them; pick one per call from the dropdown. Tokens filled per lead:

`{{business}}` `{{owner}}` `{{first}}` `{{metro}}` `{{location}}` `{{phone}}` `{{email}}` `{{me}}` `{{company}}` `{{offer}}`

The last three come from Settings. Scripts can be pasted in or imported from a `.txt`/`.md` file.

## Google Sheets sync (optional)

Manage the list in a spreadsheet, use the dialer as the calling interface. Outcomes, notes, deal sizes and follow-up dates write back; rows you add in the sheet appear on the phone.

Setup is in the comment block at the top of `sheet-sync.gs` — roughly: paste the script into your spreadsheet's Apps Script editor, set your own `TOKEN`, run `setup()` once, deploy as a Web App ("Execute as: Me", "Who has access: Anyone"), then paste the `/exec` URL and token into **Settings → Google Sheet**.

**Two tabs get created:**

- **Leads** — one row per lead. You own `business`, `owner`, `phone`, `email`, `metro`, `location`, `website`; the dialer writes `status`, `follow_up`, `deal_value`, `last_call`, `calls`, `notes`. Leave `id` blank on rows you add — it gets filled in on the next sync.
- **Call Log** — append-only, one row per call: when, who, outcome, deal size, note.

**How conflicts resolve:** whichever side changed a row most recently wins. The script's `onEdit` trigger stamps the `updated` column when you edit by hand, so a spreadsheet edit beats older data from the phone and vice versa. Call history is never overwritten by the sheet. Deleting a row in the sheet removes that lead from the phone on the next sync; deleting in the dialer removes the row.

**When it syncs:** on open, four seconds after each logged call, when you return to the app, and whenever you tap the sync icon in the header. The dot on that icon is green when everything is up to date, amber when changes are waiting, red when the last attempt failed. Changes queue offline and go up on the next successful sync — you can call all day with no signal and sync when you're back.

**Security, plainly:** the web app URL is reachable without a Google login — that is what lets the phone call it. The token you set is the only guard. Treat URL + token like a password, use something long and random, and rotate by changing `TOKEN` in the script and in Settings. Anyone holding both can read and write that spreadsheet.

## Backups

**Export** gives leads CSV, call-log CSV, or a full JSON backup — copy to clipboard or save as a file. Restore a JSON backup from Settings. Do this before clearing browser data or moving to a new phone.

The sample leads use fictional `555-01xx` numbers; **Settings → Remove sample leads** clears them.
