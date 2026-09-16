import unittest

from tests.fixtures import track_matching_fixture

from autodrome.services.track_matching import (
    clean_youtube_title,
    compare_track_titles,
    compare_tracklists,
    normalize_track_title,
)


def playlist_tracks(*titles):
    return [
        {"position": position, "title": title}
        for position, title in enumerate(titles, start=1)
    ]


def release_tracks(*titles):
    return [
        {"global_position": position, "title": title}
        for position, title in enumerate(titles, start=1)
    ]


class TestTrackTitleMatching(unittest.TestCase):
    def test_normalization_handles_unicode_case_quotes_and_punctuation(self):
        self.assertEqual(
            normalize_track_title("  CAFÉ—Don’t ‘Stop’!  "),
            normalize_track_title("cafe\u0301 dont stop"),
        )
        self.assertEqual(
            compare_track_titles("CAFÉ—Don’t ‘Stop’!", "cafe\u0301 dont stop")["status"],
            "exact",
        )

    def test_only_unambiguous_youtube_suffixes_are_cleaned(self):
        self.assertEqual(clean_youtube_title("Powertrip (Official Audio)"), "powertrip")
        self.assertEqual(
            compare_track_titles("Powertrip (Official Audio)", "Powertrip")["status"],
            "clean",
        )
        self.assertEqual(clean_youtube_title("Official Audio Powertrip"), "official audio powertrip")

    def test_close_titles_use_a_fixture_backed_threshold(self):
        comparison = compare_track_titles("The Colour of Sound", "The Color of Sound")

        self.assertEqual(comparison["status"], "close")
        self.assertGreaterEqual(comparison["score"], 0.82)

    def test_version_markers_are_not_cleaned_away(self):
        for marker in (
            "Live", "Demo", "Remix", "Acoustic", "Radio Edit", "Extended",
            "Instrumental", "Remastered", "Re-recorded", "Mono", "Stereo",
        ):
            with self.subTest(marker=marker):
                comparison = compare_track_titles(f"Tractor ({marker})", "Tractor")
                self.assertEqual(comparison["status"], "warning")
                self.assertTrue(any(reason.startswith("version_marker:") for reason in comparison["reasons"]))

    def test_unrelated_titles_remain_a_mismatch(self):
        comparison = compare_track_titles("Battery", "Nothing Else Matters")

        self.assertEqual(comparison["status"], "mismatch")

    def test_only_the_known_artist_prefix_is_removed(self):
        for separator in (" - ", ": ", " | ", " – ", " — "):
            with self.subTest(separator=separator):
                comparison = compare_track_titles(
                    f"Black Sabbath{separator}Fluff",
                    "Fluff",
                    artist="black sabbath",
                )
                self.assertEqual(comparison["status"], "clean")
                self.assertIn("artist_prefix", comparison["reasons"])

        other_artist = compare_track_titles(
            "Uploader Channel - Fluff",
            "Fluff",
            artist="Black Sabbath",
        )
        self.assertEqual(other_artist["status"], "mismatch")

    def test_artist_cleanup_preserves_version_markers(self):
        comparison = compare_track_titles(
            "Black Sabbath - Fluff (Live)",
            "Fluff",
            artist="Black Sabbath",
        )

        self.assertEqual(comparison["status"], "warning")
        self.assertIn("artist_prefix", comparison["reasons"])
        self.assertIn("version_marker:live", comparison["reasons"])

    def test_duration_only_rejects_clearly_incompatible_matches(self):
        close = compare_track_titles(
            "The Youth",
            "The Youth",
            youtube_duration_seconds=260,
            release_duration_seconds=240,
        )
        extreme = compare_track_titles(
            "The Youth",
            "The Youth",
            youtube_duration_seconds=3477,
            release_duration_seconds=240,
        )

        self.assertEqual(close["status"], "exact")
        self.assertEqual(extreme["status"], "mismatch")
        self.assertIn("duration_mismatch", extreme["reasons"])


class TestTracklistMatching(unittest.TestCase):
    def test_position_to_global_position_drives_the_comparison(self):
        result = compare_tracklists(
            list(reversed(playlist_tracks("One", "Two"))),
            list(reversed(release_tracks("One", "Two"))),
        )

        self.assertEqual(result["status"], "strong")
        self.assertEqual(
            [(track["position"], track["youtube_title"], track["release_title"])
             for track in result["tracks"]],
            [(1, "One", "One"), (2, "Two", "Two")],
        )

    def test_count_mismatch_is_a_hard_result_without_scoring(self):
        result = compare_tracklists(
            playlist_tracks("One", "Bonus"),
            release_tracks("One"),
        )

        self.assertEqual(result["status"], "mismatch")
        self.assertEqual(result["reason"], "track_count_mismatch")
        self.assertEqual(result["playlist_count"], 2)
        self.assertEqual(result["release_count"], 1)
        self.assertEqual(result["tracks"], [])
        self.assertTrue(all(count == 0 for count in result["summary"].values()))

    def test_global_rules_distinguish_local_review_from_global_mismatch(self):
        review = compare_tracklists(
            playlist_tracks("One", "Tractor (Live)", "Three"),
            release_tracks("One", "Tractor", "Three"),
        )
        mismatch = compare_tracklists(
            playlist_tracks("One", "Unrelated", "Three"),
            release_tracks("One", "Two", "Three"),
        )

        self.assertEqual(review["status"], "review")
        self.assertEqual(review["summary"]["warning"], 1)
        self.assertEqual(mismatch["status"], "review")
        self.assertEqual(mismatch["summary"]["mismatch"], 1)

    def test_duplicate_titles_stay_in_their_original_positions(self):
        result = compare_tracklists(
            playlist_tracks("Intro", "Intro", "Finale"),
            release_tracks("Intro", "Finale", "Intro"),
        )

        self.assertEqual(
            [(track["position"], track["status"]) for track in result["tracks"]],
            [(1, "exact"), (2, "mismatch"), (3, "mismatch")],
        )

    def test_black_sabbath_fixture_is_seven_clean_and_one_review(self):
        fixture = track_matching_fixture()["black_sabbath"]

        result = compare_tracklists(
            fixture["playlist_tracks"],
            fixture["release_tracks"],
            artist=fixture["artist"],
        )

        self.assertEqual(result["status"], "review")
        self.assertEqual(result["summary"]["clean"], 7)
        self.assertEqual(result["summary"]["mismatch"], 1)
        self.assertEqual(result["tracks"][5]["status"], "mismatch")

    def test_extreme_duration_fixture_is_a_strong_mismatch(self):
        fixture = track_matching_fixture()["extreme_duration"]

        result = compare_tracklists(
            fixture["playlist_tracks"],
            fixture["release_tracks"],
        )

        self.assertEqual(result["status"], "mismatch")
        self.assertEqual(result["summary"]["mismatch"], 1)
        self.assertIn("duration_mismatch", result["tracks"][0]["reasons"])

    def test_missing_artist_and_duration_keep_the_conservative_behavior(self):
        result = compare_tracklists(
            playlist_tracks("Black Sabbath - Fluff"),
            release_tracks("Fluff"),
        )

        self.assertEqual(result["status"], "mismatch")


if __name__ == "__main__":
    unittest.main()
