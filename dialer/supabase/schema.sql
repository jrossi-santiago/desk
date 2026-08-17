-- Dial Sheet — database schema
-- Run once in Supabase: SQL Editor → New query → paste → Run.
-- Safe to re-run; everything is idempotent.

create extension if not exists pgcrypto;

/* ------------------------------------------------------------------ leads */

create table if not exists public.leads (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users(id) on delete cascade,
  business    text not null default '',
  owner       text not null default '',
  phone       text not null default '',
  email       text not null default '',
  metro       text not null default '',
  location    text not null default '',
  website     text not null default '',
  deal_value  numeric not null default 0,
  status      text not null default 'new',
  follow_at   date,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create index if not exists leads_user_idx    on public.leads (user_id);
create index if not exists leads_queue_idx   on public.leads (user_id, status, follow_at);
create index if not exists leads_updated_idx on public.leads (user_id, updated_at desc);

-- One business can't be entered twice with the same number, per account.
create unique index if not exists leads_user_phone_idx
  on public.leads (user_id, phone) where phone <> '';

/* -------------------------------------------------------------- call log */

create table if not exists public.calls (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  lead_id    uuid not null references public.leads(id) on delete cascade,
  called_at  timestamptz not null default now(),
  outcome    text,
  note       text not null default '',
  created_at timestamptz not null default now()
);

create index if not exists calls_user_idx on public.calls (user_id, called_at desc);
create index if not exists calls_lead_idx on public.calls (lead_id, called_at desc);

/* --------------------------------------------------------------- scripts */

create table if not exists public.scripts (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  name       text not null default 'Untitled script',
  body       text not null default '',
  position   int  not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists scripts_user_idx on public.scripts (user_id, position);

/* -------------------------------------------------------------- profiles */

create table if not exists public.profiles (
  user_id     uuid primary key references auth.users(id) on delete cascade,
  display_name text not null default '',
  company     text not null default '',
  offer       text not null default '',
  theme       text not null default 'auto',
  script_size int  not null default 18,
  updated_at  timestamptz not null default now()
);

/* ------------------------------------------------- keep updated_at honest */

create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end $$;

drop trigger if exists leads_touch   on public.leads;
drop trigger if exists scripts_touch on public.scripts;
drop trigger if exists profiles_touch on public.profiles;
create trigger leads_touch    before update on public.leads    for each row execute function public.touch_updated_at();
create trigger scripts_touch  before update on public.scripts  for each row execute function public.touch_updated_at();
create trigger profiles_touch before update on public.profiles for each row execute function public.touch_updated_at();

/* ------------------------------------------------------------------- RLS
   Every table is locked by default. Each policy says the same thing:
   you may touch a row only when it is your own. Enforced by Postgres,
   not by application code, so a bug in the app cannot leak data.        */

alter table public.leads    enable row level security;
alter table public.calls    enable row level security;
alter table public.scripts  enable row level security;
alter table public.profiles enable row level security;

alter table public.leads    force row level security;
alter table public.calls    force row level security;
alter table public.scripts  force row level security;
alter table public.profiles force row level security;

do $$
declare t text;
begin
  foreach t in array array['leads','scripts'] loop
    execute format('drop policy if exists %I_own on public.%I', t, t);
    execute format($f$
      create policy %I_own on public.%I
        for all
        to authenticated
        using (user_id = auth.uid())
        with check (user_id = auth.uid())
    $f$, t, t);
  end loop;
end $$;

-- Calls carry a second check: the lead being logged against must also be
-- yours. Owning the call row is not enough, or one account could attach
-- rows to another account's leads.
drop policy if exists calls_own on public.calls;
create policy calls_own on public.calls
  for all
  to authenticated
  using (user_id = auth.uid())
  with check (
    user_id = auth.uid()
    and exists (
      select 1 from public.leads l
      where l.id = calls.lead_id and l.user_id = auth.uid()
    )
  );

drop policy if exists profiles_own on public.profiles;
create policy profiles_own on public.profiles
  for all
  to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

/* ------------------------------------------------------------- grants
   Logged-out visitors (the `anon` role) get nothing at all. Logged-in
   users get table access, and RLS above decides which rows.            */

revoke all on public.leads, public.calls, public.scripts, public.profiles from anon;
grant select, insert, update, delete on public.leads, public.calls, public.scripts, public.profiles to authenticated;

/* ------------------------------------------- new accounts start stocked */

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (user_id, offer)
  values (new.id, 'we help local businesses get more inbound calls without spending more on ads')
  on conflict (user_id) do nothing;

  insert into public.scripts (user_id, name, body, position)
  values (new.id, 'Cold call — local business', $script$Hi, is this {{owner}}?

Hey {{owner}}, this is {{me}} with {{company}} — I'll be quick. I'm calling local {{metro}} businesses, and {{business}} came up on my list.

The reason for the call: {{offer}}

[PAUSE — let them react]

Is that something you handle, or is there someone else there who does?

— IF INTERESTED —
Great. Two quick questions so I don't waste your time:
1. How are you getting new customers right now?
2. What would another 5–10 jobs a month actually be worth to you?

Sounds like it's worth 15 minutes. I've got Tuesday morning or Thursday afternoon — which is easier?

— IF "SEND ME SOMETHING" —
Happy to. What's the best email? … And so I send the right thing, what's the one part you'd want to see first?

— IF "NOT INTERESTED" —
Totally fair. Before I let you go — is it that you're covered right now, or just bad timing?

— IF GATEKEEPER —
No problem — when's {{owner}} usually around? I'll call back then rather than bug you.

CLOSE: Appreciate the time, {{owner}}. Talk soon.$script$, 0);

  return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();
