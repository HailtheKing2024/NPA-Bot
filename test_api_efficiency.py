import importlib
import os
import sys
import types
import unittest


def install_module_stubs():
    discord = types.ModuleType("discord")

    class FakeIntents:
        message_content = False
        members = False

        @classmethod
        def default(cls):
            return cls()

    class FakeStatus:
        online = "online"

    class FakeCustomActivity:
        def __init__(self, name):
            self.name = name

    discord.Intents = FakeIntents
    discord.Status = FakeStatus
    discord.CustomActivity = FakeCustomActivity
    discord.Interaction = object
    discord.Forbidden = type("Forbidden", (Exception,), {})
    discord.HTTPException = type("HTTPException", (Exception,), {})

    app_commands = types.ModuleType("discord.app_commands")
    app_commands.describe = lambda **kwargs: lambda func: func
    discord.app_commands = app_commands

    commands = types.ModuleType("discord.ext.commands")

    class FakeCommandTree:
        def command(self, **kwargs):
            return lambda func: func

        async def sync(self):
            return []

    class FakeBot:
        def __init__(self, *args, **kwargs):
            self.tree = FakeCommandTree()
            self.user = None

        def command(self, *args, **kwargs):
            return lambda func: func

        def event(self, func):
            return func

        def run(self, token):
            return None

    commands.Bot = FakeBot
    commands.is_owner = lambda: lambda func: func

    ext = types.ModuleType("discord.ext")
    ext.commands = commands

    aiohttp = types.ModuleType("aiohttp")
    aiohttp.ClientTimeout = lambda total=None: None
    aiohttp.ClientSession = object

    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda: None

    sys.modules.setdefault("discord", discord)
    sys.modules.setdefault("discord.app_commands", app_commands)
    sys.modules.setdefault("discord.ext", ext)
    sys.modules.setdefault("discord.ext.commands", commands)
    sys.modules.setdefault("aiohttp", aiohttp)
    sys.modules.setdefault("dotenv", dotenv)


class FakeResponse:
    def __init__(self, status=200, body="", json_body=None):
        self.status = status
        self.body = body
        self.json_body = json_body or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self):
        return self.body

    async def json(self):
        return self.json_body


class FakeSession:
    def __init__(self, cell_data):
        self.cell_data = cell_data
        self.get_count = 0
        self.patch_count = 0
        self.patch_payloads = []

    def get(self, url):
        self.get_count += 1
        return FakeResponse(json_body=self.cell_data)

    def patch(self, url, json):
        self.patch_count += 1
        self.patch_payloads.append((url, json))
        return FakeResponse(body='{"updated": 1}')


def row_cells(row_number, player, rank, npr, shields="No", peak=""):
    return {
        f"A{row_number}": player,
        f"B{row_number}": rank,
        f"C{row_number}": npr,
        f"D{row_number}": shields,
        f"E{row_number}": peak,
        f"I{row_number}": player,
        f"J{row_number}": rank,
        f"K{row_number}": npr,
        f"L{row_number}": shields,
        f"M{row_number}": peak,
    }


class ApiEfficiencyTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")
        install_module_stubs()
        cls.main = importlib.import_module("main")

    def setUp(self):
        if hasattr(self.main, "clear_leaderboard_cache"):
            self.main.clear_leaderboard_cache()

    async def test_patch_player_rows_batches_verification_for_singles(self):
        cell_data = {}
        cell_data.update(row_cells(2, "Winner", "Ruby 1", "5/10 NPR", "N/A"))
        cell_data.update(row_cells(3, "Loser", "Gold 2", "0/10 NPR", "No"))
        session = FakeSession(cell_data)
        updates = [
            (
                {"Player": "Winner", "_sheetdb_update_selector": "Winner"},
                {"Rank": "Ruby 1", "NPR (out of current ranking)": "5/10 NPR", "Rank Shield Used?": "N/A"},
            ),
            (
                {"Player": "Loser", "_sheetdb_update_selector": "Loser"},
                {"Rank": "Gold 2", "NPR (out of current ranking)": "0/10 NPR", "Rank Shield Used?": "No"},
            ),
        ]

        await self.main.patch_player_rows(session, updates)

        self.assertEqual(session.patch_count, 2)
        self.assertEqual(session.get_count, 1)

    async def test_patch_player_rows_batches_verification_for_doubles(self):
        cell_data = {}
        for row_number, player in enumerate(["Winner 1", "Winner 2", "Loser 1", "Loser 2"], start=2):
            cell_data.update(row_cells(row_number, player, "Gold 1", "1/10 NPR", "No"))
        session = FakeSession(cell_data)
        updates = [
            (
                {"Player": player, "_sheetdb_update_selector": player},
                {"Rank": "Gold 1", "NPR (out of current ranking)": "1/10 NPR", "Rank Shield Used?": "No"},
            )
            for player in ["Winner 1", "Winner 2", "Loser 1", "Loser 2"]
        ]

        await self.main.patch_player_rows(session, updates)

        self.assertEqual(session.patch_count, 4)
        self.assertEqual(session.get_count, 1)

    async def test_leaderboard_reads_use_short_lived_cache(self):
        cell_data = row_cells(2, "Leader", "Mythic 1", "1/20 NPR", "No")
        session = FakeSession(cell_data)

        first = await self.main.fetch_leaderboard_data(session)
        second = await self.main.fetch_leaderboard_data(session)

        self.assertEqual(first, second)
        self.assertEqual(session.get_count, 1)

    async def test_successful_player_patch_clears_leaderboard_cache(self):
        cell_data = row_cells(2, "Leader", "Mythic 1", "1/20 NPR", "No")
        session = FakeSession(cell_data)
        await self.main.fetch_leaderboard_data(session)

        await self.main.patch_player_rows(
            session,
            [
                (
                    {"Player": "Leader", "_sheetdb_update_selector": "Leader"},
                    {"Rank": "Mythic 1", "NPR (out of current ranking)": "1/20 NPR", "Rank Shield Used?": "No"},
                )
            ],
        )
        await self.main.fetch_leaderboard_data(session)

        self.assertEqual(session.get_count, 3)

    async def test_sheetdb_request_counter_tracks_api_calls_and_warns_near_limit(self):
        self.main.reset_sheetdb_request_count()
        self.main.clear_leaderboard_cache()
        session = FakeSession(row_cells(2, "Leader", "Mythic 1", "1/20 NPR", "No"))

        await self.main.fetch_leaderboard_data(session)

        self.assertEqual(self.main.get_sheetdb_request_count(), 1)

        self.main.reset_sheetdb_request_count()
        for _index in range(self.main.SHEETDB_WARNING_THRESHOLD):
            self.main.record_sheetdb_request()

        warning = self.main.format_sheetdb_budget_warning()
        self.assertIn("SheetDB API usage warning", warning)
        self.assertIn("450/500", warning)


if __name__ == "__main__":
    unittest.main()
