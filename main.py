import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import asyncio
import inspect
import json
import re
import os
from collections.abc import Iterable
from urllib.parse import quote
from dotenv import load_dotenv

load_dotenv()



RANKS_ORDER = [
    "plastic", "iron", "bronze", "silver", "gold",
    "ruby", "platinum", "emerald", "diamond", "legendary", "mythic"
]
MAJOR_RANK_ROLE_NAMES = {rank.title() for rank in RANKS_ORDER}

RANK_MAPPING = {
    "Plastic": 1,
    "Iron": 2,
    "Bronze": 3,
    "Silver": 4,
    "Gold": 5,
    "Ruby": 6,
    "Platinum": 7,
    "Emerald": 8,
    "Diamond": 9,
    "Legendary": 10,
    "Mythic": 11,
}


def rank_to_int(rank_str):
    rank_name = str(rank_str).strip().split()[0].title() if str(rank_str).strip() else ""
    return RANK_MAPPING.get(rank_name, 1)


def parse_rank_parts(rank_str):
    rank_cleaned = str(rank_str).strip().lower()
    for rank_base in RANKS_ORDER:
        if rank_cleaned.startswith(rank_base):
            parts = rank_cleaned.split()
            tier = 1
            if len(parts) > 1 and parts[-1].isdigit():
                tier = int(parts[-1])
            return rank_base, tier
    return None, 1


def rank_progress_value(rank_str):
    rank_base, tier = parse_rank_parts(rank_str)
    if rank_base not in RANKS_ORDER:
        return None
    return (RANKS_ORDER.index(rank_base) * 3) + tier


def is_rank_up(old_rank, new_rank):
    old_value = rank_progress_value(old_rank)
    new_value = rank_progress_value(new_rank)
    return old_value is not None and new_value is not None and new_value > old_value


def major_rank_name(rank_str):
    rank_base, _tier = parse_rank_parts(rank_str)
    return rank_base.title() if rank_base else None


def major_rank_increased(old_rank, new_rank):
    old_major, _old_tier = parse_rank_parts(old_rank)
    new_major, _new_tier = parse_rank_parts(new_rank)
    if old_major not in RANKS_ORDER or new_major not in RANKS_ORDER:
        return False
    return RANKS_ORDER.index(new_major) > RANKS_ORDER.index(old_major)


def major_rank_changed(old_rank, new_rank):
    old_major, _old_tier = parse_rank_parts(old_rank)
    new_major, _new_tier = parse_rank_parts(new_rank)
    if old_major not in RANKS_ORDER or new_major not in RANKS_ORDER:
        return False
    return old_major != new_major


def format_rank_up_notice(player_name, old_rank, new_rank):
    if not is_rank_up(old_rank, new_rank):
        return ""
    return f" Rank Up: **{old_rank}** -> **{new_rank}**"


def format_rank_change_notice(player_name, old_rank, new_rank):
    old_value = rank_progress_value(old_rank)
    new_value = rank_progress_value(new_rank)
    if old_value is None or new_value is None or new_value == old_value:
        return ""
    if new_value > old_value:
        return f" Rank Up: **{old_rank}** -> **{new_rank}**"
    return f" Derank: **{old_rank}** -> **{new_rank}**"


def normalize_player_name(player_name):
    without_tags = re.sub(r"\s*\([^)]*\)", "", str(player_name).strip())
    return re.sub(r"\s+", " ", without_tags).casefold()


def member_name_matches(member, player_name):
    target_name = normalize_player_name(player_name)
    candidate_names = [
        getattr(member, "display_name", ""),
        getattr(member, "global_name", ""),
        getattr(member, "name", ""),
    ]
    return any(normalize_player_name(candidate) == target_name for candidate in candidate_names)


async def find_member_by_player_name(guild, player_name):
    if guild is None:
        return None

    for member in getattr(guild, "members", []):
        if member_name_matches(member, player_name):
            return member

    query_members = getattr(guild, "query_members", None)
    if not callable(query_members):
        return None

    try:
        query_result = query_members(query=str(player_name).strip(), limit=10)
        if inspect.isawaitable(query_result):
            queried_members = await query_result
        else:
            queried_members = query_result
        if not isinstance(queried_members, Iterable) or isinstance(queried_members, (str, bytes)):
            return None
    except Exception:
        return None

    for member in queried_members:
        if member_name_matches(member, player_name):
            return member
    return None


def find_role_by_name(guild, role_name):
    target_name = normalize_player_name(role_name)
    for role in getattr(guild, "roles", []):
        if normalize_player_name(getattr(role, "name", "")) == target_name:
            return role
    return None


async def assign_rank_role_for_rank_up(guild, player_name, old_rank, new_rank):
    if not major_rank_increased(old_rank, new_rank):
        return ""
    return await assign_rank_role_for_rank_change(guild, player_name, old_rank, new_rank)


async def assign_rank_role_for_rank_change(guild, player_name, old_rank, new_rank):
    if not major_rank_changed(old_rank, new_rank):
        return ""

    new_role_name = major_rank_name(new_rank)
    if not new_role_name:
        return f" Role Update: could not read the new rank role for **{player_name}**."

    member = await find_member_by_player_name(guild, player_name)
    if member is None:
        return f" Role Update: could not find Discord member **{player_name}**."

    new_role = find_role_by_name(guild, new_role_name)
    if new_role is None:
        return f" Role Update: missing **{new_role_name}** role."

    current_roles = list(getattr(member, "roles", []))
    rank_roles_to_remove = [
        role for role in current_roles
        if getattr(role, "name", "") in MAJOR_RANK_ROLE_NAMES and role != new_role
    ]

    try:
        if rank_roles_to_remove:
            await member.remove_roles(
                *rank_roles_to_remove,
                reason=f"{player_name} rank changed from {old_rank} to {new_rank}.",
            )
        if new_role not in getattr(member, "roles", []):
            await member.add_roles(
                new_role,
                reason=f"{player_name} rank changed from {old_rank} to {new_rank}.",
            )
    except (discord.Forbidden, discord.HTTPException) as exc:
        return f" Role Update: failed to assign **{new_role_name}** role ({exc})."

    return f" Role Update: assigned **{new_role_name}** role."


def calculate_bonus(winner_rank, loser_rank):
    # If a lower-ranked player wins, bonus happens.
    difference = loser_rank - winner_rank
    bonus = max(0, min(10, difference))
    return bonus


def calculate_rank_adjustment(winner_rank, loser_rank, winner_npr, loser_npr):
    """
    Adjust match NPR when a higher-ranked player/team beats a lower-ranked one.

    Returns positive NPR amounts for process_npr_update plus signed display
    adjustments: (winner_npr, loser_npr, winner_adjustment, loser_adjustment).
    """
    winner_gain = max(0, winner_npr)
    loser_loss = abs(loser_npr)
    rank_gap = winner_rank - loser_rank

    if rank_gap <= 0:
        return winner_gain, loser_loss, 0, 0

    adjustment = int((rank_gap / 2) + 0.5)
    if adjustment <= 0:
        return winner_gain, loser_loss, 0, 0

    return (
        max(0, winner_gain - adjustment),
        max(0, loser_loss - adjustment),
        -adjustment,
        adjustment,
    )


def format_npr_delta(value):
    return f"{value:+}"

def process_npr_update(current_rank_str, current_npr_str, current_shields_str, npr_change, is_winner=True):
    """
    Applies point systems tracking Tier 1 (lowest entry) -> Tier 2 -> Tier 3 (highest tier)
    """
    # 1. Isolate the base rank name string and integer tier number
    rank_cleaned = str(current_rank_str).strip().lower()
    rank_base = rank_cleaned
    tier = 1 # Default entry tier is 1

    for r in RANKS_ORDER:
        if rank_cleaned.startswith(r):
            rank_base = r
            parts = rank_cleaned.split()
            if len(parts) > 1 and parts[-1].isdigit():
                tier = int(parts[-1])
            break

    # 2. Extract current point values and the max denominator dynamically
    max_npr = 10 # Default fallback
    npr_val = 0
    match = re.search(r"(-?\d+)/(\d+)", str(current_npr_str))
    if match:
        npr_val = int(match.group(1))
        max_npr = int(match.group(2))
    if max_npr <= 0:
        raise ValueError(f"Invalid NPR maximum: {max_npr}")

    # 3. Apply the match calculations
    if is_winner:
        npr_val += npr_change

        # Promotion loop: Check if player exceeds the maximum cap of their cell structure
        while npr_val >= max_npr:
            npr_val -= max_npr
            if tier < 3:
                tier += 1 # Moves from Tier 1 -> Tier 2 -> Tier 3 (highest)
            else:
                tier = 1 # Reset back down to entry Tier 1 of the next major rank
                if rank_base in RANKS_ORDER:
                    current_idx = RANKS_ORDER.index(rank_base)
                    if current_idx < len(RANKS_ORDER) - 1:
                        rank_base = RANKS_ORDER[current_idx + 1]
                    else:
                        # Cap values at maximum rank tier threshold limits (Mythic 3)
                        tier = 3
                        npr_val = max_npr
                        break
    else:
        starting_npr = npr_val
        npr_val -= npr_change

        if starting_npr > 0 and npr_val < 0:
            npr_val = 0

        # Demotion / Protection path loop 
        while npr_val < 0:
                        
            # Check if this rank allows shields
            if rank_base in ["ruby", "diamond"]:
                is_shield_rank = False
                current_shields_str = "N/A"
            else:
                is_shield_rank = True

            # Shield logic only applies to Tier 1 for protected ranks
            if tier == 1 and is_shield_rank:
                shield_text = str(current_shields_str).strip().lower()
                if "0/2" in shield_text or "no shields used" in shield_text or shield_text in ("", "no", "false"):
                    npr_val = 0 # Shield absorbs negative drop completely
                    current_shields_str = "Yes (1/2 Shields Used)"
                    break

                # Any other value means protection is already used or malformed.
                # Demote instead of leaving npr_val unchanged and blocking the event loop.
                current_shields_str = "No Shields Used"
                npr_val = max_npr + npr_val # Carry over negative spillover
                if rank_base in RANKS_ORDER:
                    current_idx = RANKS_ORDER.index(rank_base)
                    if current_idx > 0:
                        rank_base = RANKS_ORDER[current_idx - 1]
                        tier = 3
                    else:
                        tier = 1
                        npr_val = 0
                else:
                    npr_val = 0
                break
            else:
                # Ruby/Diamond (any tier) or standard ranks at Tier 2 or 3 drop tiers naturally
                if tier > 1:
                    tier -= 1 # Drops from Tier 3 -> Tier 2 -> Tier 1
                    npr_val = max_npr + npr_val
                else:
                    # Tier 1 with NO shield (Ruby/Diamond) drops directly to the lower rank Tier 3
                    npr_val = max_npr + npr_val
                    if rank_base in RANKS_ORDER:
                        current_idx = RANKS_ORDER.index(rank_base)
                        if current_idx > 0:
                            rank_base = RANKS_ORDER[current_idx - 1]
                            tier = 3
                        else:
                            tier = 1
                            npr_val = 0
                            break

    # 4. Generate system string representations matching spreadsheet syntax
    new_rank = f"{rank_base.title()} {tier}"
    new_npr = f"{npr_val}/{max_npr} NPR"

    if rank_base in ["ruby", "diamond"]:
        current_shields_str = "N/A"

    return new_rank, new_npr, current_shields_str

def calculate_npr(score_a, score_b):
    diff = score_a - score_b
    rating_a = 2.5 + (diff / 11) * 5
    rating_b = 4 + (diff / 11) * 5

    rating_a = max(0, min(10, rating_a))
    rating_b = max(0, min(10, rating_b))
    return round(rating_a,), round(rating_b)


# 1. Setup intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# FIX: Use commands.Bot instead of discord.Client
client = commands.Bot(command_prefix="$", intents=intents)
SHEETDB_URL = "https://sheetdb.io/api/v1/ra1bgaunuflkm"
SOURCE_COLUMNS = {
    "Player": "A",
    "Rank": "B",
    "NPR (out of current ranking)": "C",
    "Rank Shield Used?": "D",
    "Peak Rank (all time)": "E",
}
LEADERBOARD_COLUMNS = {
    "Player": "I",
    "Rank": "J",
    "NPR (out of current ranking)": "K",
    "Rank Shield Used?": "L",
    "Peak Rank (all time)": "M",
}
SOURCE_START_ROW = 2
SOURCE_END_ROW = 100

async def fetch_table_data(session, columns):
    cells = [
        f"{column}{row}"
        for row in range(SOURCE_START_ROW, SOURCE_END_ROW + 1)
        for column in columns.values()
    ]
    async with session.get(f"{SHEETDB_URL}/cells/{','.join(cells)}") as response:
        if response.status != 200:
            body = await response.text()
            raise RuntimeError(f"SheetDB read failed: HTTP {response.status} {body[:200]}")
        cell_data = await response.json()

    rows = []
    for row_number in range(SOURCE_START_ROW, SOURCE_END_ROW + 1):
        row = {
            field: str(cell_data.get(f"{column}{row_number}", "")).strip()
            for field, column in columns.items()
        }
        if row["Player"]:
            row["_row_number"] = str(row_number)
            rows.append(row)

    return rows

async def fetch_sheet_data(session):
    source_rows, selector_rows = await asyncio.gather(
        fetch_table_data(session, SOURCE_COLUMNS),
        fetch_table_data(session, LEADERBOARD_COLUMNS),
    )
    selectors_by_row = {
        row["_row_number"]: str(row.get("Player", "")).strip()
        for row in selector_rows
    }

    for row in source_rows:
        row["_sheetdb_update_selector"] = selectors_by_row.get(row["_row_number"], "")

    return source_rows

async def fetch_leaderboard_data(session):
    return await fetch_table_data(session, LEADERBOARD_COLUMNS)

def find_player_row(data, player_name):
    target_name = str(player_name).strip().lower()
    matches = [
        row for row in data
        if str(row.get('Player', '')).strip().lower() == target_name
    ]
    if len(matches) > 1:
        raise ValueError(f"Multiple sheet rows match player {player_name!r}.")
    return matches[0] if matches else None

async def patch_player_row(session, player_row, data):
    player_key = str(player_row.get('Player', ''))
    if not player_key.strip():
        raise ValueError("Cannot update a player row with an empty Player value.")

    # The sheet has duplicate headers in A:E and I:M. SheetDB matches Player
    # against the right autosorted table, while writes land in the left table.
    current_row = find_player_row(await fetch_sheet_data(session), player_key)
    if current_row is None:
        raise RuntimeError(f"SheetDB update failed for {player_key.strip()}: player row disappeared.")

    update_selector = str(current_row.get("_sheetdb_update_selector", "")).strip()
    if not update_selector:
        raise RuntimeError(
            f"SheetDB update failed for {player_key.strip()}: no right-table selector "
            f"on source row {current_row.get('_row_number', 'unknown')}."
        )

    payload = {"data": data, "sheet": "Sheet1", "mode": "USER_ENTERED"}
    patch_url = f"{SHEETDB_URL}/Player/{quote(update_selector, safe='')}"
    async with session.patch(patch_url, json=payload) as response:
        body = await response.text()
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"SheetDB update failed for {player_key.strip()}: HTTP {response.status} {body[:200]}")

    try:
        result = json.loads(body) if body else {}
    except json.JSONDecodeError:
        result = {}

    updated_count = result.get("updated")
    if updated_count is not None and int(updated_count) < 1:
        raise RuntimeError(f"SheetDB update matched 0 rows for {player_key.strip()}: {body[:200]}")

    await verify_player_update(session, player_key, data)

async def verify_player_update(session, player_key, expected_data):
    expected = {key: str(value) for key, value in expected_data.items()}
    last_seen = None

    for attempt in range(3):
        data = await fetch_table_data(session, SOURCE_COLUMNS)
        updated_row = find_player_row(data, player_key)
        if updated_row is not None:
            last_seen = {key: str(updated_row.get(key, "")) for key in expected}
            if last_seen == expected:
                return

        if attempt < 2:
            await asyncio.sleep(0.5)

    raise RuntimeError(
        f"SheetDB verification failed for {str(player_key).strip()}: "
        f"expected {expected}, found {last_seen}"
    )

# 2. Slash command (will work now that client has a tree)
@client.tree.command(name="calculate-singles", description="Logs match details, alters statistics, and parses system rank updates.")
@app_commands.describe(
    winners_name="The name of the winning player/team (e.g., Kyle C, Maximus L)",
    losers_name="The name of the losing player/team (e.g., Kyle C, Maximus L)",
    losers_score="The score of the losing team (0 to 9 for a normal game, > 11 for a deuce game)"
)
async def submit_match_singles(
    interaction: discord.Interaction,
    winners_name: str,
    losers_name: str,
    losers_score: int
):
    if losers_score < 0:
        await interaction.response.send_message("Bud, the losers can't have a score below 0.", ephemeral=True)
        return

    # Defer immediate response window to allow network execution breathing room
    await interaction.response.defer()

    try:
        # FIXED: Define base scoping parameters cleanly so UnboundLocalError are structurally impossible
        winners_score = 11
        npr_winner, npr_loser = calculate_npr(winners_score, losers_score)
        # Overtime rule branch modification checks
        if losers_score >= 10:
            npr_winner = 2
            npr_loser = 3
            winners_score = losers_score + 2

        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            data = await fetch_sheet_data(session)
            winner_row = find_player_row(data, winners_name)
            loser_row = find_player_row(data, losers_name)

            if not winner_row or not loser_row:
                await interaction.followup.send(
                    f"Profile matching failed. Double check that **{winners_name}** and **{losers_name}** exist on your sheet data."
                )
                return

            winner_old_rank = winner_row.get('Rank', 'Plastic 1')
            loser_old_rank = loser_row.get('Rank', 'Plastic 1')
            w_rank_int = rank_to_int(winner_old_rank)
            l_rank_int = rank_to_int(loser_old_rank)
            winner_adjustment = 0
            loser_adjustment = 0

            if w_rank_int < l_rank_int:
                npr_bonus = min(5, round(calculate_bonus(w_rank_int, l_rank_int)))
                npr_winner += npr_bonus
                npr_loser += npr_bonus
                winner_adjustment = npr_bonus
                loser_adjustment = -npr_bonus
            elif w_rank_int > l_rank_int:
                npr_winner, npr_loser, winner_adjustment, loser_adjustment = calculate_rank_adjustment(
                    winner_rank=w_rank_int,
                    loser_rank=l_rank_int,
                    winner_npr=npr_winner,
                    loser_npr=npr_loser,
                )

            # Run tier and point calculations
            w_rank, w_npr, w_shield = process_npr_update(
                winner_row.get('Rank', 'Plastic 1'),
                winner_row.get('NPR (out of current ranking)', '0/10 NPR'),
                winner_row.get('Rank Shield Used?', 'No'),
                npr_winner, is_winner=True
            )

            l_rank, l_npr, l_shield = process_npr_update(
                loser_row.get('Rank', 'Plastic 1'),
                loser_row.get('NPR (out of current ranking)', '0/10 NPR'),
                loser_row.get('Rank Shield Used?', 'No'),
                npr_loser, is_winner=False
            )
            

            winner_payload = {"Rank": w_rank, "NPR (out of current ranking)": w_npr, "Rank Shield Used?": w_shield}
            loser_payload = {"Rank": l_rank, "NPR (out of current ranking)": l_npr, "Rank Shield Used?": l_shield}

            await patch_player_row(session, winner_row, winner_payload)
            await patch_player_row(session, loser_row, loser_payload)

            winner_rank_change_notice = format_rank_change_notice(winners_name, winner_old_rank, w_rank)
            loser_rank_change_notice = format_rank_change_notice(losers_name, loser_old_rank, l_rank)
            winner_role_notice = await assign_rank_role_for_rank_change(
                interaction.guild, winners_name, winner_old_rank, w_rank
            )
            loser_role_notice = await assign_rank_role_for_rank_change(
                interaction.guild, losers_name, loser_old_rank, l_rank
            )

            # Output single aggregated confirmation log string
            msg = (
                f"**Match Calculation Complete!**\n"
                f"Score: {winners_score} to {losers_score} in favor of **{winners_name}**\n"
                f"**{winners_name} (Winner):**\n"
                f" New Rank Status: **{w_rank}** ({w_npr}) (+{npr_winner} NPR) (Rank Balancing: {format_npr_delta(winner_adjustment)} NPR). [Shields: {w_shield}]{winner_rank_change_notice}{winner_role_notice}\n"
                f"**{losers_name} (Loser):**\n"
                f" New Rank Status: **{l_rank}** ({l_npr}) (-{npr_loser} NPR) (Rank Balancing: {format_npr_delta(loser_adjustment)} NPR). [Shields: {l_shield}]{loser_rank_change_notice}{loser_role_notice}"
            )
            await interaction.followup.send(msg)
    except asyncio.TimeoutError:
        await interaction.followup.send("Connection timed out. SheetDB took too long to respond.")
    except Exception as e:
        await interaction.followup.send(f"An unexpected error occurred: {str(e)}")

@client.tree.command(name="calculate-doubles", description="Logs match details, alters statistics, and parses system rank updates. (Doubles version)")
@app_commands.describe(
    winners_name_1="The name of the first player on the winning team (e.g., Kyle C, Maximus L)",
    winners_name_2="The name of the second player on the winning team (e.g., Kyle C, Maximus L)",
    losers_name_1="The name of the first player on the losing team (e.g., Kyle C, Maximus L)",
    losers_name_2="The name of the second player on the losing team (e.g., Kyle C, Maximus L)",
    losers_score="The score of the losing team (0 to 9 for a normal game, > 11 for a deuce game)"
)
async def submit_match_doubles(
    interaction: discord.Interaction,
    winners_name_1: str,
    winners_name_2:str,
    losers_name_1: str,
    losers_name_2:str,
    losers_score: int
):
    if losers_score < 0:
        await interaction.response.send_message("Bud, the losers can't have a score below 0.", ephemeral=True)
        return

    # Defer immediate response window to allow network execution breathing room
    await interaction.response.defer()

    try:
        # FIXED: Define base scoping parameters cleanly so UnboundLocalError are structurally impossible
        winners_score = 11
        npr_winner, npr_loser = calculate_npr(winners_score, losers_score)
        # Overtime rule branch modification checks
        if losers_score >= 10:
            npr_winner = 2
            npr_loser = 3
            winners_score = losers_score + 2

        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            data = await fetch_sheet_data(session)
            winner_row_1 = find_player_row(data, winners_name_1)
            winner_row_2 = find_player_row(data, winners_name_2)
            loser_row_1 = find_player_row(data, losers_name_1)
            loser_row_2 = find_player_row(data, losers_name_2)

            if not winner_row_1 or not loser_row_1 or not winner_row_2 or not loser_row_2:
                await interaction.followup.send(
                    f"Profile matching failed. Double check that **{winners_name_1}**, **{winners_name_2}**, **{losers_name_1}** and **{losers_name_2}** exist on the NPA official document."
                )
                return

            winner_old_rank_1 = winner_row_1.get('Rank', 'Plastic 1')
            winner_old_rank_2 = winner_row_2.get('Rank', 'Plastic 1')
            loser_old_rank_1 = loser_row_1.get('Rank', 'Plastic 1')
            loser_old_rank_2 = loser_row_2.get('Rank', 'Plastic 1')
            average_w_rank = (
                rank_to_int(winner_old_rank_1) +
                rank_to_int(winner_old_rank_2)
            ) / 2
            average_l_rank = (
                rank_to_int(loser_old_rank_1) +
                rank_to_int(loser_old_rank_2)
            ) / 2
            winner_adjustment = 0
            loser_adjustment = 0

            if average_w_rank < average_l_rank:
                npr_bonus = min(5, round(calculate_bonus(average_w_rank, average_l_rank)))
                npr_winner += npr_bonus
                npr_loser += npr_bonus
                winner_adjustment = npr_bonus
                loser_adjustment = -npr_bonus
            elif average_w_rank > average_l_rank:
                npr_winner, npr_loser, winner_adjustment, loser_adjustment = calculate_rank_adjustment(
                    winner_rank=average_w_rank,
                    loser_rank=average_l_rank,
                    winner_npr=npr_winner,
                    loser_npr=npr_loser,
                )

            # Run tier and point calculations
            w_rank_1, w_npr_1, w_shield_1 = process_npr_update(
                winner_row_1.get('Rank', 'Plastic 1'),
                winner_row_1.get('NPR (out of current ranking)', '0/10 NPR'),
                winner_row_1.get('Rank Shield Used?', 'No'),
                npr_winner, is_winner=True
            )
            w_rank_2, w_npr_2, w_shield_2 = process_npr_update(
                winner_row_2.get('Rank', 'Plastic 1'),
                winner_row_2.get('NPR (out of current ranking)', '0/10 NPR'),
                winner_row_2.get('Rank Shield Used?', 'No'),
                npr_winner, is_winner=True
            )

            l_rank_1, l_npr_1, l_shield_1 = process_npr_update(
                loser_row_1.get('Rank', 'Plastic 1'),
                loser_row_1.get('NPR (out of current ranking)', '0/10 NPR'),
                loser_row_1.get('Rank Shield Used?', 'No'),
                npr_loser, is_winner=False
            )
            l_rank_2, l_npr_2, l_shield_2 = process_npr_update(
                loser_row_2.get('Rank', 'Plastic 1'),
                loser_row_2.get('NPR (out of current ranking)', '0/10 NPR'),
                loser_row_2.get('Rank Shield Used?', 'No'),
                npr_loser, is_winner=False
            )

            winner_payload_1 = {"Rank": w_rank_1, "NPR (out of current ranking)": w_npr_1, "Rank Shield Used?": w_shield_1}
            winner_payload_2 = {"Rank": w_rank_2, "NPR (out of current ranking)": w_npr_2, "Rank Shield Used?": w_shield_2}
            loser_payload_1 = {"Rank": l_rank_1, "NPR (out of current ranking)": l_npr_1, "Rank Shield Used?": l_shield_1}
            loser_payload_2 = {"Rank": l_rank_2, "NPR (out of current ranking)": l_npr_2, "Rank Shield Used?": l_shield_2}

            await patch_player_row(session, winner_row_1, winner_payload_1)
            await patch_player_row(session, winner_row_2, winner_payload_2)
            await patch_player_row(session, loser_row_1, loser_payload_1)
            await patch_player_row(session, loser_row_2, loser_payload_2)

            winner_rank_change_notice_1 = format_rank_change_notice(winners_name_1, winner_old_rank_1, w_rank_1)
            winner_rank_change_notice_2 = format_rank_change_notice(winners_name_2, winner_old_rank_2, w_rank_2)
            loser_rank_change_notice_1 = format_rank_change_notice(losers_name_1, loser_old_rank_1, l_rank_1)
            loser_rank_change_notice_2 = format_rank_change_notice(losers_name_2, loser_old_rank_2, l_rank_2)
            winner_role_notice_1 = await assign_rank_role_for_rank_change(
                interaction.guild, winners_name_1, winner_old_rank_1, w_rank_1
            )
            winner_role_notice_2 = await assign_rank_role_for_rank_change(
                interaction.guild, winners_name_2, winner_old_rank_2, w_rank_2
            )
            loser_role_notice_1 = await assign_rank_role_for_rank_change(
                interaction.guild, losers_name_1, loser_old_rank_1, l_rank_1
            )
            loser_role_notice_2 = await assign_rank_role_for_rank_change(
                interaction.guild, losers_name_2, loser_old_rank_2, l_rank_2
            )

            # Output single aggregated confirmation log string
            msg = (
                f"**Match Calculation Complete!**\n"
                f"Score: {winners_score} to {losers_score} in favor of **{winners_name_1}** and **{winners_name_2}**\n"
                f"**{winners_name_1} (Winner):**\n"
                f" New Rank Status: **{w_rank_1}** ({w_npr_1}) (+{npr_winner} NPR) (Rank Balancing: {format_npr_delta(winner_adjustment)} NPR). [Shields: {w_shield_1}]{winner_rank_change_notice_1}{winner_role_notice_1}\n"
                f"**{winners_name_2} (Winner):**\n"
                f" New Rank Status: **{w_rank_2}** ({w_npr_2}) (+{npr_winner} NPR) (Rank Balancing: {format_npr_delta(winner_adjustment)} NPR). [Shields: {w_shield_2}]{winner_rank_change_notice_2}{winner_role_notice_2}\n"
                f"**{losers_name_1} (Loser):**\n"
                f" New Rank Status: **{l_rank_1}** ({l_npr_1}) (-{npr_loser} NPR) (Rank Balancing: {format_npr_delta(loser_adjustment)} NPR). [Shields: {l_shield_1}]{loser_rank_change_notice_1}{loser_role_notice_1}\n"
                f"**{losers_name_2} (Loser):**\n"
                f" New Rank Status: **{l_rank_2}** ({l_npr_2}) (-{npr_loser} NPR) (Rank Balancing: {format_npr_delta(loser_adjustment)} NPR). [Shields: {l_shield_2}]{loser_rank_change_notice_2}{loser_role_notice_2}"
            )
            await interaction.followup.send(msg)
    except asyncio.TimeoutError:
        await interaction.followup.send("Connection timed out. SheetDB took too long to respond.")
    except Exception as e:
        await interaction.followup.send(f"An unexpected error occurred: {str(e)}")

@client.tree.command(name="rank", description="Fetches your current rank in this season")
@app_commands.describe(name='What is your name? (e.g., Kyle C, Maximus L)')
async def fetch_rank(interaction: discord.Interaction, name: str):
    # Hold the interaction to prevent Discord's 3-second timeout
    await interaction.response.defer()

    # Safety timeout so the bot doesn't get stuck infinitely if the API lags
    timeout = aiohttp.ClientTimeout(total=10)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            data = await fetch_leaderboard_data(session)

            if not data:
                await interaction.followup.send("⚠️ The spreadsheet appears to be empty.")
                return

            found_player = find_player_row(data, name)

            if found_player is not None:
                player_name = found_player.get('Player', 'Unknown')
                current_rank = found_player.get('Rank', 'N/A')
                npr_rating = found_player.get('NPR (out of current ranking)', 'N/A')

                msg = (
                    f" **Profile found for {player_name}**\n"
                    f" **Rank:** {current_rank}\n"
                    f" **NPR Status:** {npr_rating}"
                )
                await interaction.followup.send(msg)
            else:
                await interaction.followup.send(f" Could not find any records for the name '{name}'. Check spelling and try again!")

    except asyncio.TimeoutError:
        await interaction.followup.send(" Connection timed out. SheetDB took too long to respond.")
    except Exception as e:
        await interaction.followup.send(f" An unexpected error occurred: {str(e)}")

# leaderboard command
@client.tree.command(name="leaderboard", description="View the top 5 players in the leaderboard for this season")
async def get_leaderboard(interaction: discord.Interaction):
    # Hold the interaction to prevent Discord's 3-second timeout
    await interaction.response.defer()

    # Safety timeout so the bot doesn't get stuck infinitely if the API lags
    timeout = aiohttp.ClientTimeout(total=10)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            data = await fetch_leaderboard_data(session)

            if not data:
                await interaction.followup.send("⚠️ The spreadsheet appears to be empty.")
                return

            top_five_rows = data[:5]

            columns = [
                "Player",
                "Rank",
                "NPR (out of current ranking)",
                "Rank Shield Used?",
                "Peak Rank (all time)"
            ]

            msg = "**Leaderboard**" 

            for index,row in enumerate(top_five_rows , start=1):
                col_a = row.get(columns[0], "N/A")   
                col_b = row.get(columns[1], "N/A") 
                col_c = row.get(columns[2], "N/A") 
                col_d = row.get(columns[3], "N/A") 
                col_e = row.get(columns[4], "N/A") 

                msg += (
                    f"\n **#{index}**\n"
                    f"**{columns[0]}:** {col_a}\n"
                    f"**{columns[1]}:** {col_b}\n"
                    f"**{columns[2]}:** {col_c}\n"
                    f"**{columns[3]}:** {col_d}\n"
                    f"**{columns[4]}:** {col_e}"
                )
            await interaction.followup.send(msg)

    except asyncio.TimeoutError:
        await interaction.followup.send(" Connection timed out. SheetDB took too long to respond.")
    except Exception as e:
        await interaction.followup.send(f" An unexpected error occurred: {str(e)}")


@client.tree.command(name="help", description="Need help? Start by using this command!")
async def help_command(interaction: discord.Interaction):
    # Hold the interaction to prevent Discord's 3-second timeout
    await interaction.response.defer()
    await interaction.followup.send("Hello and welcome to picklebot! This command will give you an overview of all the different commands you can observe in picklebot. Here are the commands: \n"
    "/rank: Fetch your current rank in the NPA.\n"
    "/leaderboard: Fetch the current top 5 in the leaderboard.\n"
    "/events: Fetch the current events ongoing in the NPA.\n"
    "/calculate-singles and /calculate-doubles are commands that are only used by recorders and the host to log match results and update the spreadsheet. If you are not a recorder or host, you will not be able to use this command, but will be able to see the results of a recorder or host using this command.\n"
    "**Live updates to this bot will be posted in #picklebot-updates. If we missed anything here please let us know in #suggestions!**")

@client.tree.command(name="events", description="Displays the current events that are active right now, and upcoming events.")
async def current_event(interaction: discord.Interaction):
    # Hold the interaction to prevent Discord's 3-second timeout
    await interaction.response.defer()
    await interaction.followup.send("**2 Active Events Found**\n"
                                    "**Event 1:** End of Season 3 Tournament Duo Pick'Ems\n"
                                    "**Description:** Pick your duo teammate for the end of season tournament! Get started in #tournament-info and #team.\n"
                                    "**Event 2:** PROVE YOURSELF: BLOWOUT\n"
                                    """**Description:** PROVE YOURSELF: BLOWOUT EVENT. Do you think you are deserving of a higher rank? This limited time event will put your skills and move you to a more deserving rank. Here are the details:
CHALLENGE YOUR RANK: If you think you deserve a higher rank, challenge 3 different players that are a higher rank than you to a limited time event match. To prove your skill, you must beat the higher ranked player with a score of AT MOST 6-11. If you complete all 3 games with that score, you will INSTANTLY MOVE 2 RANKS UP YOUR CURRENT RANK. If the challenging player loses even ONCE match, they do not deserve the rank and will not be placed any ranks higher. The games played in this event are NOT RANKED and will have @Recorder put in a special tag indicating that it is a event match. There are no penalties for the challenging or higher ranked players. YOU MAY ONLY CHALLENGE 3 HIGHER RANKED PLAYERS. If you fail even one game, the event and trial is over for you. Good luck and HAVE FUN!!!""")

# 3. Ready event
@client.event
async def on_ready():
    print(f'We have logged in as {client.user}')
    await client.change_presence(
        status=discord.Status.online,
        activity=discord.CustomActivity(
            name="🏓 | Calculating pickleball scores..." 
        )
    )

# 4. Message event
@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.content.startswith('$hello'):
        await message.channel.send('Hello!')

    # IMPORTANT: Allows prefix commands like $sync to work alongside on_message
    await client.process_commands(message)

# 5. Sync command (Prefix: $sync)
@client.command()
@commands.is_owner()
async def sync(ctx):
    # This syncs your slash commands globally
    synced = await client.tree.sync()
    await ctx.send(f"Synced {len(synced)} command(s) globally.")

client.run(os.environ["DISCORD_BOT_TOKEN"])
#geometry dash
