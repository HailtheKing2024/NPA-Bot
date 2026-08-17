# NPA Bot Agent Guide

## Workflow
- Use Python 3.14: `.python-version` and `uv.lock` require it (the broader `>=3.13` in `pyproject.toml` is not sufficient for the locked environment).
- Install/run the locked project with `uv sync` and `uv run python main.py`. Running the bot requires `DISCORD_BOT_TOKEN`; `main.py` loads it from `.env` and exits if it is absent.
- The configured test convention is unittest discovery: `uv run python -m unittest discover -v -s tests -p "*test.py"`. There is no lint/typecheck configuration.
- For a fast syntax-only check of the single module, run `uv run python -m py_compile main.py`.

## Structure And Runtime
- `main.py` is the entire application: ranking logic, Discord commands, and SheetDB integration live together. It is also the process entrypoint.
- Slash commands are not synced during `on_ready`; the bot owner must run the `$sync` prefix command to publish command changes globally.
- Keep `on_message` calling `client.process_commands(message)` or prefix commands such as `$sync` stop working.

## SheetDB Contract
- `SHEETDB_URL` is a production endpoint hardcoded in `main.py`; exercise write paths only with deliberate credentials and data.
- The sheet duplicates headers in source columns `A:E` and autosorted leaderboard columns `I:M`. Reads pair rows by row number, then writes select the right-table `Player` value while updating the left table. Preserve `_sheetdb_update_selector` and the fetch/patch/verify flow when changing sheet access.
- Writes are verified with retries because SheetDB can be eventually consistent; failures are warnings after a successful patch, not command-fatal errors.

## Supabase Contract
- `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` come from `.env`; they must never be committed. History features (`/h2h`, `/profile` streaks, match logging) stay disabled when they are absent.
- Match history is written after a successful SheetDB patch via the `record_match` RPC in `supabase/migrations/0001_match_history.sql`. Logging failures are warnings, never command-fatal; keep that contract.
- `player_streak` and `head_to_head` RPCs return a JSON array; `record_match` accepts participant names that are normalized the same way as SheetDB players.
