\set ON_ERROR_STOP off
\pset pager off
-- Two accounts. The auth.users insert fires the new-user trigger.
insert into auth.users (id, email) values
  ('11111111-1111-1111-1111-111111111111','jrossi@example.com'),
  ('22222222-2222-2222-2222-222222222222','brother@example.com')
on conflict do nothing;

\echo '=== 1. new-user trigger stocked both accounts ==='
select u.email, (select count(*) from public.profiles p where p.user_id=u.id) as profiles,
       (select count(*) from public.scripts s where s.user_id=u.id) as scripts
from auth.users u order by u.email;

-- Become a logged-in user, the way PostgREST does it.
set role authenticated;
set request.jwt.claims = '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}';

\echo '=== 2. account A inserts its own leads ==='
insert into public.leads (user_id, business, phone, metro, status)
values ('11111111-1111-1111-1111-111111111111','Ridgeline Heating & Air','+16025550142','Phoenix, AZ','new'),
       ('11111111-1111-1111-1111-111111111111','Copper State Roofing','+16025550178','Phoenix, AZ','callback');
select count(*) as a_sees_own from public.leads;

\echo '=== 3. account A cannot insert a row owned by B  (must ERROR) ==='
insert into public.leads (user_id, business, phone) values ('22222222-2222-2222-2222-222222222222','Stolen Row','+15555550000');

\echo '=== 4. switch to account B ==='
set request.jwt.claims = '{"sub":"22222222-2222-2222-2222-222222222222","role":"authenticated"}';
select count(*) as b_sees_total, count(*) filter (where business like 'Ridgeline%') as b_sees_a_lead from public.leads;

\echo '=== 5. B tries to read A rows by guessing the id  (0 rows) ==='
select count(*) as leaked from public.leads where user_id = '11111111-1111-1111-1111-111111111111';

\echo '=== 6. B tries to UPDATE A rows  (0 rows) ==='
update public.leads set business = 'HACKED' where user_id = '11111111-1111-1111-1111-111111111111';

\echo '=== 7. B tries to DELETE A rows  (0 rows) ==='
delete from public.leads where user_id = '11111111-1111-1111-1111-111111111111';

\echo '=== 8. B inserts the SAME phone number A already has  (allowed, separate accounts) ==='
insert into public.leads (user_id, business, phone) values ('22222222-2222-2222-2222-222222222222','His Own HVAC Co','+16025550142');
select count(*) as b_leads from public.leads;

\echo '=== 9. B inserts that same number twice  (must ERROR, dedupe within an account) ==='
insert into public.leads (user_id, business, phone) values ('22222222-2222-2222-2222-222222222222','Dupe','+16025550142');

\echo '=== 10. B logs a call against his own lead, then against A lead  (second must ERROR) ==='
insert into public.calls (user_id, lead_id, outcome, note)
  select '22222222-2222-2222-2222-222222222222', id, 'interested', 'his call' from public.leads limit 1;
insert into public.calls (user_id, lead_id, outcome, note)
  values ('11111111-1111-1111-1111-111111111111','00000000-0000-0000-0000-000000000000','x','forged');

\echo '=== 11. B cannot see A scripts or profile ==='
select count(*) as b_scripts from public.scripts;
select count(*) as b_profiles from public.profiles;

\echo '=== 12. back to A: data intact, untouched by B ==='
set request.jwt.claims = '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}';
select business, status from public.leads order by business;

\echo '=== 13. logged-out (anon) sees nothing  (must ERROR: permission denied) ==='
reset role;
set role anon;
select count(*) from public.leads;
