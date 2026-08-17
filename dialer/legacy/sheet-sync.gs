/**
 * Dial Sheet — Google Sheets sync
 * ------------------------------------------------------------------
 * Paste this into a spreadsheet's Apps Script editor and deploy it as
 * a Web App. The dialer then reads and writes that spreadsheet.
 *
 * SETUP
 *  1. Open your spreadsheet → Extensions → Apps Script.
 *  2. Delete whatever is in Code.gs, paste this file in, and Save.
 *  3. Change TOKEN below to a random string of your own. Save again.
 *  4. Run → select the function "setup" → Run. Approve the permission
 *     prompt (it is your own script asking for your own sheet). This
 *     creates the Leads and Call Log tabs with their headers.
 *  5. Deploy → New deployment → type: Web app.
 *       Execute as:        Me
 *       Who has access:    Anyone
 *     Deploy, then copy the /exec URL it gives you.
 *  6. In the dialer: Settings → Google Sheet → paste the URL and the
 *     same TOKEN → Connect.
 *
 * "Who has access: Anyone" means the URL is reachable without a Google
 * login — that is what lets the dialer call it from your phone. The
 * TOKEN is the only thing guarding it, so treat the URL and token
 * together like a password, and pick a long random token. Anyone
 * holding both can read and write this spreadsheet. Rotate by changing
 * TOKEN here and in the dialer.
 *
 * Redeploy after editing this file: Deploy → Manage deployments →
 * edit → Version: New version → Deploy. The URL stays the same.
 */

var TOKEN       = 'change-me-to-something-random';
var SHEET_LEADS = 'Leads';
var SHEET_LOG   = 'Call Log';

var LEAD_COLS = ['id','business','owner','phone','email','metro','location','website',
                 'deal_value','status','follow_up','last_call','calls','notes','updated'];
var LOG_COLS  = ['when','id','business','owner','phone','metro','outcome','deal_value','note'];

/* ---------------------------------------------------------------- setup */

function setup(){
  tab(SHEET_LEADS, LEAD_COLS);
  tab(SHEET_LOG, LOG_COLS);
  SpreadsheetApp.getActive().toast('Dial Sheet tabs are ready.');
}

function tab(name, cols){
  var ss = SpreadsheetApp.getActive();
  var sh = ss.getSheetByName(name) || ss.insertSheet(name);
  var head = sh.getRange(1, 1, 1, cols.length).getValues()[0];
  if (head.join('') !== cols.join('')) {
    sh.getRange(1, 1, 1, cols.length).setValues([cols]).setFontWeight('bold');
    sh.setFrozenRows(1);
  }
  return sh;
}

/* ---------------------------------------------------------------- web app */

function doGet(e){  return respond(handle(e, {})); }
function doPost(e){
  var body = {};
  try { body = JSON.parse((e && e.postData && e.postData.contents) || '{}'); } catch (err) {}
  return respond(handle(e, body));
}

function handle(e, body){
  var token = body.token || (e && e.parameter && e.parameter.token) || '';
  if (String(token) !== String(TOKEN)) return {ok:false, error:'bad_token'};

  var lock = LockService.getScriptLock();
  try { lock.waitLock(20000); } catch (err) { return {ok:false, error:'busy'}; }
  try {
    var wrote = 0, logged = 0, removed = 0;
    if (body.remove && body.remove.length) removed = removeLeads(body.remove);
    if (body.leads  && body.leads.length)  wrote   = upsertLeads(body.leads);
    if (body.log    && body.log.length)    logged  = appendLog(body.log);
    return {ok:true, leads:readLeads(), wrote:wrote, logged:logged, removed:removed,
            at:new Date().toISOString()};
  } catch (err) {
    return {ok:false, error:String(err && err.message || err)};
  } finally {
    lock.releaseLock();
  }
}

function respond(obj){
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

/* ---------------------------------------------------------------- leads */

function readLeads(){
  var sh = tab(SHEET_LEADS, LEAD_COLS);
  var last = sh.getLastRow();
  if (last < 2) return [];
  var rows = sh.getRange(2, 1, last - 1, LEAD_COLS.length).getValues();
  var tz = SpreadsheetApp.getActive().getSpreadsheetTimeZone();
  var out = [];
  for (var i = 0; i < rows.length; i++) {
    var o = {}, empty = true;
    for (var c = 0; c < LEAD_COLS.length; c++) {
      var v = rows[i][c];
      if (v !== '' && v !== null) empty = false;
      o[LEAD_COLS[c]] = cell(LEAD_COLS[c], v, tz);
    }
    if (empty) continue;
    if (!o.business && !o.phone) continue;
    if (!o.id) { o.id = 'r' + (i + 2) + '-' + Date.now().toString(36); sh.getRange(i + 2, 1).setValue(o.id); }
    out.push(o);
  }
  return out;
}

function cell(name, v, tz){
  if (v instanceof Date) {
    return name === 'follow_up' ? Utilities.formatDate(v, tz, 'yyyy-MM-dd') : v.toISOString();
  }
  if (name === 'deal_value' || name === 'calls') return Number(v) || 0;
  return v === null || v === undefined ? '' : String(v).trim();
}

function upsertLeads(leads){
  var sh = tab(SHEET_LEADS, LEAD_COLS);
  var last = sh.getLastRow();
  var index = {};
  var stamps = {};
  if (last > 1) {
    var known = sh.getRange(2, 1, last - 1, LEAD_COLS.length).getValues();
    for (var i = 0; i < known.length; i++) {
      var id = String(known[i][0] || '');
      if (!id) continue;
      index[id] = i + 2;
      stamps[id] = ms(known[i][LEAD_COLS.indexOf('updated')]);
    }
  }
  var appended = [], wrote = 0;
  for (var j = 0; j < leads.length; j++) {
    var l = leads[j];
    if (!l || !l.id) continue;
    var row = LEAD_COLS.map(function(k){ return l[k] === undefined || l[k] === null ? '' : l[k]; });
    var at = index[l.id];
    if (at) {
      // Whoever edited most recently wins. Sheet edits are stamped by onEdit.
      if (ms(l.updated) >= (stamps[l.id] || 0)) { sh.getRange(at, 1, 1, LEAD_COLS.length).setValues([row]); wrote++; }
    } else {
      appended.push(row); wrote++;
    }
  }
  if (appended.length) sh.getRange(sh.getLastRow() + 1, 1, appended.length, LEAD_COLS.length).setValues(appended);
  return wrote;
}

function removeLeads(ids){
  var sh = tab(SHEET_LEADS, LEAD_COLS);
  var last = sh.getLastRow();
  if (last < 2) return 0;
  var col = sh.getRange(2, 1, last - 1, 1).getValues();
  var kill = {}, n = 0;
  for (var i = 0; i < ids.length; i++) kill[String(ids[i])] = true;
  for (var r = col.length - 1; r >= 0; r--) {
    if (kill[String(col[r][0] || '')]) { sh.deleteRow(r + 2); n++; }
  }
  return n;
}

/* ---------------------------------------------------------------- call log */

function appendLog(entries){
  var sh = tab(SHEET_LOG, LOG_COLS);
  var rows = [];
  for (var i = 0; i < entries.length; i++) {
    var e = entries[i];
    rows.push(LOG_COLS.map(function(k){ return e[k] === undefined || e[k] === null ? '' : e[k]; }));
  }
  if (rows.length) sh.getRange(sh.getLastRow() + 1, 1, rows.length, LOG_COLS.length).setValues(rows);
  return rows.length;
}

/* ---------------------------------------------------------------- edit stamp */

/**
 * Simple trigger: stamps `updated` whenever you edit a lead row by hand,
 * so your spreadsheet edits beat older data coming from the phone.
 * Runs automatically — no trigger setup needed.
 */
function onEdit(e){
  try {
    var sh = e.range.getSheet();
    if (sh.getName() !== SHEET_LEADS) return;
    var row = e.range.getRow();
    if (row < 2) return;
    var stampCol = LEAD_COLS.indexOf('updated') + 1;
    if (e.range.getColumn() === stampCol && e.range.getNumColumns() === 1) return;
    var idCell = sh.getRange(row, 1);
    if (!idCell.getValue()) idCell.setValue('r' + row + '-' + Date.now().toString(36));
    sh.getRange(row, stampCol).setValue(new Date().toISOString());
  } catch (err) {}
}

function ms(v){
  if (!v) return 0;
  if (v instanceof Date) return v.getTime();
  var t = Date.parse(v);
  return isNaN(t) ? 0 : t;
}
