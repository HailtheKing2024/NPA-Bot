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


class FakeMember:
    display_name = "Abhinav B (Recorder)"
    global_name = ""
    name = "abhinav"


class NameMatchingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")
        install_module_stubs()
        cls.main = importlib.import_module("main")

    def test_member_name_matches_discord_parenthetical_suffix(self):
        self.assertTrue(self.main.member_name_matches(FakeMember(), "Abhinav B"))


if __name__ == "__main__":
    unittest.main()
