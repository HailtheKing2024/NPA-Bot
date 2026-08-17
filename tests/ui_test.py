import unittest

import main


class UiHelperTests(unittest.TestCase):
    def test_format_npr_progress_uses_solid_blocks(self):
        self.assertEqual(
            main.format_npr_progress("6/10 NPR"),
            "▰▰▰▰▰▰▱▱▱▱ 6/10 NPR",
        )

    def test_format_npr_progress_preserves_unparseable_values(self):
        self.assertEqual(main.format_npr_progress("N/A"), "N/A")

    def test_rank_theme_uses_rank_name_and_fallback(self):
        self.assertEqual(main.get_rank_theme("Diamond 2"), main.RANK_THEMES["diamond"])
        self.assertEqual(main.get_rank_theme("Unranked"), main.DEFAULT_RANK_THEME)

    def test_leaderboard_embed_uses_requested_page(self):
        rows = [
            {"Player": "A", "Rank": "Gold 1", "NPR (out of current ranking)": "1/10 NPR"},
            {"Player": "B", "Rank": "Gold 2", "NPR (out of current ranking)": "2/10 NPR"},
            {"Player": "C", "Rank": "Gold 3", "NPR (out of current ranking)": "3/10 NPR"},
        ]

        embed = main.leaderboard_embed(rows, page=1, page_size=2)

        self.assertIn("C", embed.description)
        self.assertNotIn("A", embed.description)
        self.assertEqual(embed.footer.text, "Page 2 of 2 | 3 players | 2 per page")


class SupabaseHistoryTests(unittest.TestCase):
    def test_build_match_history_payload_structure(self):
        payload = main.build_match_history_payload(
            "singles",
            11,
            5,
            [
                {
                    "player_name": "Kyle C",
                    "is_winner": True,
                    "rank_before": "Gold 1",
                    "rank_after": "Gold 2",
                    "npr_before": "5/10 NPR",
                    "npr_after": "1/10 NPR",
                },
                {
                    "player_name": "Max L",
                    "is_winner": False,
                    "rank_before": "Silver 3",
                    "rank_after": "Silver 2",
                    "npr_before": "2/10 NPR",
                    "npr_after": "9/10 NPR",
                },
            ],
        )

        self.assertEqual(payload["p_match_type"], "singles")
        self.assertEqual(payload["p_winner_score"], 11)
        self.assertEqual(payload["p_loser_score"], 5)
        self.assertEqual(len(payload["p_participants"]), 2)
        self.assertEqual(payload["p_participants"][0]["player_name"], "Kyle C")
        self.assertTrue(payload["p_participants"][0]["is_winner"])


class AutocompleteTests(unittest.IsolatedAsyncioTestCase):
    async def test_autocomplete_uses_cached_rows_only(self):
        original_rows = main._leaderboard_cache_rows
        try:
            main._leaderboard_cache_rows = [{"Player": "Alex"}, {"Player": "Sam"}]
            choices = await main.player_name_autocomplete(None, "al")
        finally:
            main._leaderboard_cache_rows = original_rows

        self.assertEqual([(choice.name, choice.value) for choice in choices], [("Alex", "Alex")])
