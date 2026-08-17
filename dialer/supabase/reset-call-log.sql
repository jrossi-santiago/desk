-- Clearing out bad call history
-- ------------------------------------------------------------------
-- Run these in Supabase: SQL Editor → New query.
--
-- Put YOUR email in the line below and leave it as the only thing you
-- change. Every statement here is scoped to that one account, so nobody
-- else's call history can be touched.
--
-- Leads, statuses, deal sizes and follow-up dates are NOT affected by
-- any of this. Only the call log.

-- ============ 1. LOOK FIRST. This changes nothing. ============

select date(c.called_at at time zone 'America/Phoenix') as day,   -- your timezone
       count(*)                                          as calls,
       count(*) filter (where coalesce(c.note,'') <> '') as with_a_note,
       count(*) filter (where coalesce(c.note,'') =  '') as blank
from public.calls c
join auth.users u on u.id = c.user_id
where u.email = 'you@example.com'                                  -- your email
group by 1
order by 1 desc;


-- ============ 2a. Wipe the call log for this account ============
-- Everything resets to zero. Use this if none of the history is worth
-- keeping. Leads stay exactly as they are.

delete from public.calls c
using auth.users u
where u.id = c.user_id
  and u.email = 'you@example.com';                                 -- your email


-- ============ 2b. Or: keep only the calls you wrote a note on ============
-- Gentler. Phantom entries never had a note, so this clears them while
-- keeping every call you actually took the time to write up.

delete from public.calls c
using auth.users u
where u.id = c.user_id
  and u.email = 'you@example.com'                                  -- your email
  and coalesce(c.note, '') = '';


-- ============ 3. Check what's left ============

select count(*) as calls_remaining
from public.calls c
join auth.users u on u.id = c.user_id
where u.email = 'you@example.com';                                 -- your email

-- Then open the dialer and tap the sync icon. The deletion pulls through
-- to the phone and the numbers drop to match.
