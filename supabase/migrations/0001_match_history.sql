-- NPA match history tables and RPC functions for /h2h and streaks.

create table if not exists players (
    id uuid primary key default gen_random_uuid(),
    normalized_name text not null unique,
    display_name text not null,
    created_at timestamptz not null default now()
);

create table if not exists matches (
    id uuid primary key default gen_random_uuid(),
    played_at timestamptz not null default now(),
    match_type text not null check (match_type in ('singles', 'doubles')),
    winner_score int not null,
    loser_score int not null
);

create table if not exists match_participants (
    id uuid primary key default gen_random_uuid(),
    match_id uuid not null references matches(id) on delete cascade,
    player_id uuid not null references players(id) on delete cascade,
    is_winner boolean not null,
    rank_before text,
    rank_after text,
    npr_before text,
    npr_after text
);

create index if not exists match_participants_player_id_idx
    on match_participants (player_id);
create index if not exists match_participants_match_id_idx
    on match_participants (match_id);

create or replace function record_match(
    p_match_type text,
    p_winner_score int,
    p_loser_score int,
    p_participants jsonb
) returns jsonb
language plpgsql
security definer
as $$
declare
    v_match_id uuid;
    v_participant jsonb;
    v_player_id uuid;
begin
    insert into matches (match_type, winner_score, loser_score)
    values (p_match_type, p_winner_score, p_loser_score)
    returning id into v_match_id;

    for v_participant in select * from jsonb_array_elements(p_participants) loop
        insert into players (normalized_name, display_name)
        values (
            lower(btrim(v_participant->>'player_name')),
            btrim(v_participant->>'player_name')
        )
        on conflict (normalized_name)
        do update set display_name = excluded.display_name
        returning id into v_player_id;

        insert into match_participants (
            match_id,
            player_id,
            is_winner,
            rank_before,
            rank_after,
            npr_before,
            npr_after
        ) values (
            v_match_id,
            v_player_id,
            (v_participant->>'is_winner')::boolean,
            v_participant->>'rank_before',
            v_participant->>'rank_after',
            v_participant->>'npr_before',
            v_participant->>'npr_after'
        );
    end loop;

    return jsonb_build_object('match_id', v_match_id);
end;
$$;

create or replace function player_streak(p_player_name text)
returns table (
    player_name text,
    streak int
)
language plpgsql
security definer
as $$
declare
    v_player_id uuid;
    v_last_result boolean;
    v_streak int := 0;
    v_row record;
begin
    select id into v_player_id
    from players
    where normalized_name = lower(btrim(p_player_name));

    if v_player_id is null then
        return;
    end if;

    select mp.is_winner
    into v_last_result
    from match_participants mp
    join matches m on m.id = mp.match_id
    where mp.player_id = v_player_id
    order by m.played_at desc, m.id desc
    limit 1;

    if v_last_result is null then
        return;
    end if;

    for v_row in
        select mp.is_winner
        from match_participants mp
        join matches m on m.id = mp.match_id
        where mp.player_id = v_player_id
        order by m.played_at desc, m.id desc
    loop
        if v_row.is_winner = v_last_result then
            v_streak := v_streak + 1;
        else
            exit;
        end if;
    end loop;

    if not v_last_result then
        v_streak := -v_streak;
    end if;

    return query
    select lower(btrim(p_player_name)) as player_name, v_streak as streak;
end;
$$;

create or replace function head_to_head(p_player_a text, p_player_b text)
returns table (
    player_a text,
    player_b text,
    matches_played int,
    player_a_wins int,
    player_b_wins int,
    winner_name text,
    loser_name text,
    winner_score int,
    loser_score int,
    played_at timestamptz
)
language plpgsql
security definer
as $$
declare
    v_player_a_id uuid;
    v_player_b_id uuid;
    v_matches_played int := 0;
    v_player_a_wins int := 0;
    v_player_b_wins int := 0;
    v_row record;
begin
    select id into v_player_a_id from players where normalized_name = lower(btrim(p_player_a));
    select id into v_player_b_id from players where normalized_name = lower(btrim(p_player_b));

    if v_player_a_id is null or v_player_b_id is null then
        return;
    end if;

    for v_row in
        select
            m.id as match_id,
            m.winner_score,
            m.loser_score,
            m.played_at,
            p_a.display_name as player_a_name,
            p_b.display_name as player_b_name,
            mp_a.is_winner as a_is_winner,
            mp_b.is_winner as b_is_winner,
            winner.display_name as winner_name,
            loser.display_name as loser_name
        from matches m
        join match_participants mp_a on mp_a.match_id = m.id and mp_a.player_id = v_player_a_id
        join match_participants mp_b on mp_b.match_id = m.id and mp_b.player_id = v_player_b_id
        join players p_a on p_a.id = v_player_a_id
        join players p_b on p_b.id = v_player_b_id
        join match_participants mp_winner on mp_winner.match_id = m.id and mp_winner.is_winner = true
        join players winner on winner.id = mp_winner.player_id
        join match_participants mp_loser on mp_loser.match_id = m.id and mp_loser.is_winner = false
        join players loser on loser.id = mp_loser.player_id
        where mp_a.is_winner != mp_b.is_winner
        order by m.played_at desc, m.id desc
    loop
        v_matches_played := v_matches_played + 1;
        if v_row.a_is_winner then
            v_player_a_wins := v_player_a_wins + 1;
        end if;
        if v_row.b_is_winner then
            v_player_b_wins := v_player_b_wins + 1;
        end if;
    end loop;

    return query
    select
        p_a.display_name,
        p_b.display_name,
        v_matches_played,
        v_player_a_wins,
        v_player_b_wins,
        w.display_name,
        l.display_name,
        m.winner_score,
        m.loser_score,
        m.played_at
    from matches m
    join match_participants mp_a on mp_a.match_id = m.id and mp_a.player_id = v_player_a_id
    join match_participants mp_b on mp_b.match_id = m.id and mp_b.player_id = v_player_b_id
    join players p_a on p_a.id = v_player_a_id
    join players p_b on p_b.id = v_player_b_id
    join match_participants mp_w on mp_w.match_id = m.id and mp_w.is_winner = true
    join players w on w.id = mp_w.player_id
    join match_participants mp_l on mp_l.match_id = m.id and mp_l.is_winner = false
    join players l on l.id = mp_l.player_id
    where mp_a.is_winner != mp_b.is_winner
    order by m.played_at desc, m.id desc
    limit 5;
end;
$$;

grant execute on function record_match(text, int, int, jsonb) to anon, authenticated, service_role;
grant execute on function player_streak(text) to anon, authenticated, service_role;
grant execute on function head_to_head(text, text) to anon, authenticated, service_role;