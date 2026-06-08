import discord
from discord.ext import commands
from discord import app_commands

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

# FIX: Use commands.Bot instead of discord.Client
client = commands.Bot(command_prefix="$", intents=intents)

# 2. Slash command (will work now that client has a tree)
@client.tree.command(name="rank-calculator", description="Calculates the raw NPR of a single match instantly. (MMR is not factored into this.)")
@app_commands.describe(
    winners_name="The name of the winning player/team",
    losers_name="The name of the losing player/team",
    losers_score="The score of the losing team (0 to 10)"
)
async def submit_match(
    interaction: discord.Interaction, 
    winners_name: str, 
    losers_name: str, 
    losers_score: int
):
    # Enforce score boundary constraints
    if not (0 <= losers_score <= 10):
        await interaction.response.send_message(
            "Bud the losers can't have a score above 10.", 
            ephemeral=True
        )
        return

    winners_score = 11
    npr_winner, npr_loser = calculate_npr(winners_score, losers_score)


    message = f"**{winners_name}** gains {npr_winner} npr and **{losers_name}** loses {npr_loser} npr"
    
    await interaction.response.send_message(message)

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

client.run('YOUR_BOT_TOKEN_HERE')
