"""Reading one account's experience off the official hiscores."""

from __future__ import annotations

import pytest

from chunksim.remote import hiscores

_PAYLOAD = {
    "name": "canifischunk",
    "skills": [
        {"id": 0, "name": "Overall", "rank": 1, "level": 2004, "xp": 354133836},
        {"id": 1, "name": "Attack", "rank": 2, "level": 99, "xp": 13137106},
        {"id": 24, "name": "Sailing", "rank": -1, "level": 1, "xp": 0},
        {"id": 99, "name": "Nonsense"},
        "not a row",
    ],
}


class TestParsing:
    def test_the_experience_is_what_is_read(self) -> None:
        """Both are in the payload, and the level is derived from the
        experience by a curve this project already holds - so storing the
        level would be storing an answer where the question is cheaper."""
        assert hiscores.parse(_PAYLOAD)["Attack"] == 13137106

    def test_overall_is_dropped(self) -> None:
        """A sum, not a skill - and a 2,004-level pseudo-skill in a mapping
        every consumer iterates."""
        assert hiscores.OVERALL not in hiscores.parse(_PAYLOAD)

    def test_an_unranked_skill_reads_zero(self) -> None:
        """`rank: -1, level: 1, xp: 0` for a skill never trained, and zero
        experience is level one - which is what the floor would have said."""
        assert hiscores.parse(_PAYLOAD)["Sailing"] == 0

    def test_a_malformed_row_is_skipped_rather_than_raising(self) -> None:
        """Tolerant the way `model/` is: the shape of a live endpoint is not
        this project's to guarantee."""
        found = hiscores.parse(_PAYLOAD)
        assert "Nonsense" not in found
        assert set(found) == {"Attack", "Sailing"}

    def test_a_payload_with_no_skills_is_empty(self) -> None:
        assert hiscores.parse({}) == {}
        assert hiscores.parse({"skills": "no"}) == {}

    def test_the_account_name_comes_back(self) -> None:
        """The hiscores may re-case what was asked for."""
        assert hiscores.account_name(_PAYLOAD) == "canifischunk"
        assert hiscores.account_name({}) == ""


@pytest.mark.real_export
class TestTheJoinNeedsNoAliases:
    def test_every_hiscores_skill_is_a_skill_the_export_names(self) -> None:
        """**Why there is no alias table here.** The two vocabularies agree on
        all 24; the export's only extra is `Combat`, a derived pseudo-skill
        rather than a trainable one. A rename upstream fails this rather than
        silently dropping a skill."""
        from chunksim.store import cache

        info = cache.read_chunkinfo()
        named = set(info["challenges"])
        for skill in _REAL_SKILLS:
            assert skill in named, skill
        assert "Combat" in named


_REAL_SKILLS = (
    "Agility", "Attack", "Construction", "Cooking", "Crafting", "Defence",
    "Farming", "Firemaking", "Fishing", "Fletching", "Herblore", "Hitpoints",
    "Hunter", "Magic", "Mining", "Prayer", "Ranged", "Runecraft", "Sailing",
    "Slayer", "Smithing", "Strength", "Thieving", "Woodcutting",
)


class TestTheEndpoint:
    def test_the_url_quotes_the_name(self) -> None:
        from chunksim.remote import api

        assert "player=a%20b" in api.hiscores_url(" a b ")

    def test_an_empty_name_is_refused_before_the_socket(self) -> None:
        from chunksim.remote import api

        with pytest.raises(api.FetchError):
            api.fetch_hiscores("   ")
