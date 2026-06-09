# NPA-Scorer

A Discord bot that manages competitive rankings for ping-pong leagues using [SheetDB](https://sheetdb.io/) as a backend.

## Features

- **Match Logging**: Log match results with `/calculate-rank`
- **Rank Tracking**: Tiered rank system (Plastic -> Mythic, 3 tiers each)
- **Shield Mechanics**: Protection shields for Ruby and Diamond ranks
- **Player Lookup**: Check current rank and NPR status with `/rank`

## Setup

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Create a `.env` file** (copy from `.env.example`):
   ```bash
   cp .env.example .env
   ```
   Then edit `.env` and add your Discord bot token.

3. **Run the bot**:
   ```bash
   python main.py
   ```

## Deployment (Discloud)

1. Zip the following files together:
   - `main.py`
   - `requirements.txt`
   - `discloud.config`

2. Optionally include a `.env` file with your `DISCORD_BOT_TOKEN` if Discloud supports it, or set the environment variable via the Discloud dashboard.

3. Upload the zip to Discloud.

## Commands

| Command | Description |
|---------|-------------|
| `/calculate-rank` | Log a match result and update player ranks |
| `/rank` | Look up a player's current rank and NPR |
| `$sync` | Sync slash commands globally (owner only) |
| `$hello` | Simple ping command |

## Rank System

The bot uses a tiered ranking system. Each major rank has 3 tiers. Players gain NPR points from wins and lose them from losses. Reaching the max NPR promotes to the next tier; dropping below zero can trigger demotion or shield usage.

### Shield Ranks

- **Ruby** and **Diamond** do NOT have shields.
- All other ranks have a 2-shield protection system at Tier 1.
