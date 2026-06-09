import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import asyncio
import re
import os
from dotenv import load_dotenv

load_dotenv()

RANKS_ORDER = [
    "plastic", "iron", "bronze", "silver", "gold",
    "ruby", "platinum", "emerald", "diamond", "legendary", "mythic"
]

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
        npr_val -= npr_change

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
                if "0/2" in shield_text or "No Shields Used" in shield_text or shield_text == "":
                    npr_val = 0 # Shield absorbs negative drop completely
                    current_shields_str = "Yes (1/2 Shields Used)"
                    break
                elif "1/2" in shield_text or "n/a" in shield_text:
                    # Second shield broken -> Demote to previous rank's highest tier (Tier 3)
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
    return round(rating_a), round(rating_b)



# 1. Setup intents
intents = discord.Intents.default()
intents.message_content = True

# FIX: Use commands.Bot instead of discord.Client
client = commands.Bot(command_prefix="$", intents=intents)
SHEETDB_URL = "https://sheetdb.io/api/v1/ra1bgaunuflkm"

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
            # Pull sheet database overview mapping arrays
            async with session.get(SHEETDB_URL) as response:
                if response.status != 200:
                    await interaction.followup.send("Error connecting to SheetDB.")
                    return
                data = await response.json()

            # Isolate targeted rows
            winner_row, loser_row = None, None
            for row in data:
                p_name = str(row.get('Player', '')).strip().lower()
                if p_name == winners_name.strip().lower():
                    winner_row = row
                if p_name == losers_name.strip().lower():
                    loser_row = row

            if not winner_row or not loser_row:
                await interaction.followup.send(
                    f"Profile matching failed. Double check that **{winners_name}** and **{losers_name}** exist on your sheet data."
                )
                return

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

            # Patch values down to individual row cell references via unique primary key names
            patch_winner_url = f"{SHEETDB_URL}/Player/{winner_row.get('Player')}"
            patch_loser_url = f"{SHEETDB_URL}/Player/{loser_row.get('Player')}"

            winner_payload = {"data": {"Rank": w_rank, "NPR (out of current ranking)": w_npr, "Rank Shield Used?": w_shield}}
            loser_payload = {"data": {"Rank": l_rank, "NPR (out of current ranking)": l_npr, "Rank Shield Used?": l_shield}}

            await session.patch(patch_winner_url, json=winner_payload)
            await session.patch(patch_loser_url, json=loser_payload)

            # Output single aggregated confirmation log string
            msg = (
                f"**Match Calculation Complete!**\n"
                f"Score: {winners_score} to {losers_score} in favor of **{winners_name}**\n"
                f"**{winners_name} (Winner):**\n"
                f" New Rank Status: **{w_rank}** ({w_npr}) (+{npr_winner} NPR). [Shields: {w_shield}]\n"
                f"**{losers_name} (Loser):**\n"
                f" New Rank Status: **{l_rank}** ({l_npr}) (-{npr_loser} NPR). [Shields: {l_shield}]"
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
            # Pull sheet database overview mapping arrays
            async with session.get(SHEETDB_URL) as response:
                if response.status != 200:
                    await interaction.followup.send("Error connecting to SheetDB.")
                    return
                data = await response.json()

            # Isolate targeted rows
            winner_row_1, loser_row_1 = None, None
            winner_row_2, loser_row_2 = None, None
            for row in data:
                p_name = str(row.get('Player', '')).strip().lower()
                if p_name == winners_name_1.strip().lower():
                    winner_row_1 = row
                if p_name == losers_name_1.strip().lower():
                    loser_row_1 = row
                if p_name == winners_name_2.strip().lower():
                    winner_row_2 = row
                if p_name == losers_name_2.strip().lower():
                    loser_row_2 = row

            if not winner_row_1 or not loser_row_1 or not winner_row_2 or not loser_row_2:
                await interaction.followup.send(
                    f"Profile matching failed. Double check that **{winners_name_1}**, **{winners_name_2}**, **{losers_name_1}** and **{losers_name_2}** exist on the NPA official document."
                )
                return

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

            # Patch values down to individual row cell references via unique primary key names
            patch_winner_url_1 = f"{SHEETDB_URL}/Player/{winner_row_1.get('Player')}"
            patch_winner_url_2 = f"{SHEETDB_URL}/Player/{winner_row_2.get('Player')}"
            patch_loser_url_1 = f"{SHEETDB_URL}/Player/{loser_row_1.get('Player')}"
            patch_loser_url_2 = f"{SHEETDB_URL}/Player/{loser_row_2.get('Player')}"

            winner_payload_1 = {"data": {"Rank": w_rank_1, "NPR (out of current ranking)": w_npr_1, "Rank Shield Used?": w_shield_1}}
            winner_payload_2 = {"data": {"Rank": w_rank_2, "NPR (out of current ranking)": w_npr_2, "Rank Shield Used?": w_shield_2}}
            loser_payload_1 = {"data": {"Rank": l_rank_1, "NPR (out of current ranking)": l_npr_1, "Rank Shield Used?": l_shield_1}}
            loser_payload_2 = {"data": {"Rank": l_rank_2, "NPR (out of current ranking)": l_npr_2, "Rank Shield Used?": l_shield_2}}

            await session.patch(patch_winner_url_1, json=winner_payload_1)
            await session.patch(patch_winner_url_2,json=winner_payload_2)
            await session.patch(patch_loser_url_1, json=loser_payload_1)
            await session.patch(patch_loser_url_2, json=loser_payload_2)
            # Output single aggregated confirmation log string
            msg = (
                f"**Match Calculation Complete!**\n"
                f"Score: {winners_score} to {losers_score} in favor of **{winners_name_1}** and **{winners_name_2}\n"
                f"**{winners_name_1} (Winner):**\n"
                f" New Rank Status: **{w_rank_1}** ({w_npr_1}) (+{npr_winner} NPR). [Shields: {w_shield_1}]\n"
                f"**{winners_name_2} (Winner):**\n"
                f" New Rank Status: **{w_rank_2}** ({w_npr_2}) (+{npr_winner} NPR). [Shields: {w_shield_2}]\n"
                f"**{losers_name_1} (Loser):**\n"
                f" New Rank Status: **{l_rank_1}** ({l_npr_1}) (-{npr_loser} NPR). [Shields: {l_shield_1}]\n"
                f"**{losers_name_2} (Loser):**\n"
                f" New Rank Status: **{l_rank_2}** ({l_npr_2}) (-{npr_loser} NPR). [Shields: {l_shield_2}]"
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
            async with session.get(SHEETDB_URL) as response:
                if response.status != 200:
                    await interaction.followup.send("❌ Failed to reach the data server.")
                    return

                # SheetDB automatically parses columns into a list of dictionaries
                data = await response.json()

                if not data:
                    await interaction.followup.send("⚠️ The spreadsheet appears to be empty.")
                    return

                # Look through the dictionary entries
                found_player = None
                for row in data:
                    # SheetDB uses your column headers as string keys!
                    player_cell = row.get('Player', '')
                    if str(player_cell).strip().lower() == name.strip().lower():
                        found_player = row
                        break

                if found_player is not None:
                    # Match keys directly with your spreadsheet column headers
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
            async with session.get(SHEETDB_URL) as response:
                if response.status != 200:
                    await interaction.followup.send("❌ Failed to reach the data server.")
                    return

                # SheetDB automatically parses columns into a list of dictionaries
                data = await response.json()

                if not data:
                    await interaction.followup.send("⚠️ The spreadsheet appears to be empty.")
                    return

                # Look through the dictionary entries
                top_five_rows = data[:5]

                columns = [
                    "Player",
                    "Rank",
                    "NPR (out of current ranking)",
                    "Rank Shield Used?",
                    "Peak Rank (all time)"
                ]

                msg = "**Leaderboard**\n" 

                for index,row in enumerate(top_five_rows , start=1):
                    col_a = row.get(columns[0], "N/A")   
                    col_b = row.get(columns[1], "N/A") 
                    col_c = row.get(columns[2], "N/A") 
                    col_d = row.get(columns[3], "N/A") 
                    col_e = row.get(columns[4], "N/A") 

                    msg += (
                        f"\n **#{index}**\n"
                        f"{columns[0]}: {col_a}\n"
                        f"{columns[1]}: {col_b}\n"
                        f"{columns[2]}: {col_c}\n"
                        f"{columns[3]}: {col_d}\n"
                        f"{columns[4]}: {col_e}"
                    )
                await interaction.followup.send(msg)

    except asyncio.TimeoutError:
        await interaction.followup.send(" Connection timed out. SheetDB took too long to respond.")
    except Exception as e:
        await interaction.followup.send(f" An unexpected error occurred: {str(e)}")

# 3. Ready event
@client.event
async def on_ready():
    print(f'We have logged in as {client.user}')

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
