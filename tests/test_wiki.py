"""Tests for the wikitext parsing.

Fixtures are cut down from real pages rather than invented: the nested
`{{SCP|Quest}}`, the comment inside Gargoyle's `slayxp`, and the
`{{+=|weight|7|echo=2}}` weight call are all shapes the live wiki actually
serves, and each one breaks a naive parse in a different way.
"""

from __future__ import annotations

import pytest

from fray_claude.remote.wiki import (
    mmg_rates,
    monster_slayer_xp,
    parse_amount,
    parse_number,
    quest_difficulty,
    quest_length,
    slayer_assignments,
    strip_comments,
    strip_links,
    template_params,
)

#: Cut from the live `Dragon Slayer I`. The length is in `{{Quest details}}`
#: and *not* in `{{Infobox Quest}}` - both are here because a parser that
#: reads the wrong one returns `None` for every quest without erroring.
_QUEST = """
{{Infobox Quest
|name = Dragon Slayer I
|number = 17
|image = [[File:Dragon Slayer.png|300px]]
|members = No
|developer = [[Paul Gower]]
}}
'''Dragon Slayer I''' is a quest.

==Details==
{{Quest details
|start = Talk to the [[Guildmaster]].
|difficulty = Experienced
|length = Medium
|requirements = 32 {{SCP|Quest|link=yes}} points
|items = 10 [[Steel nails|nails]]
}}
"""

_MMG = """
{{Mmgtable
|Activity = [[Underwater Agility and Thieving]]
|Members = Yes
|Skill = {{SCP|Agility|60}}
|Experience1 = Thieving
|Experience1num = 422.8
|Experience2 = Agility
|Experience2num = 4.5
|kph = 200
|kph name = Mermaid's Tears per hour
}}
"""

_ASSIGNMENTS = """
{| class="wikitable sortable"
! Task !! Amount !! Requirements !! Weight
|-
|[[Slayer task/Aberrant spectres|Aberrant Spectres]]
|130-200
|{{SCP|Slayer|60}}
|{{+=|weight|7|echo=2}}
|-
|[[Slayer task/Metal dragons|Metal Dragons]]
|35-45
|
|{{+=|weight|14|echo=2}}
|-
! Total
!
!
!{{#var:weight}}
|}
"""


def test_strip_comments_removes_multi_line_spans() -> None:
    assert strip_comments("a<!--\nnote\n-->b") == "ab"


def test_parse_number_tolerates_separators_and_trailing_markup() -> None:
    assert parse_number("1,200") == 1200.0
    assert parse_number("422.8") == 422.8
    assert parse_number("27 kills<ref name=x/>") == 27.0
    assert parse_number("no number here") is None


def test_quest_length_reads_the_infobox() -> None:
    assert quest_length(_QUEST) == "Medium"


def test_length_is_not_read_from_the_infobox() -> None:
    # The tempting wrong template. It parses fine and has no length, so the
    # failure mode is a silent `None` for every quest in the game.
    assert "length" not in template_params(_QUEST, "Infobox Quest")


def test_quest_difficulty_reads_the_same_template() -> None:
    assert quest_difficulty(_QUEST) == "Experienced"


def test_a_nested_template_does_not_end_the_parameter() -> None:
    # `{{SCP|Quest|link=yes}}` contains two `|` and an `=`; splitting on
    # either without tracking depth loses every parameter after it.
    params = template_params(_QUEST, "Quest details")

    assert params["requirements"] == "32 {{SCP|Quest|link=yes}} points"
    assert params["difficulty"] == "Experienced"


def test_a_nested_link_does_not_end_the_parameter() -> None:
    assert template_params(_QUEST, "Quest details")["items"] == "10 [[Steel nails|nails]]"


def test_strip_links_keeps_the_visible_text() -> None:
    assert strip_links("Killing [[General Graardor]]") == "Killing General Graardor"
    assert strip_links("10 [[Steel nails|nails]]") == "10 nails"


def test_the_template_name_matches_loosely() -> None:
    # MediaWiki normalises case and underscores, and pages use either.
    assert template_params("{{quest_details|length = Long}}", "Quest details") == {"length": "Long"}


def test_a_missing_template_is_empty_rather_than_an_error() -> None:
    assert template_params("just prose", "Quest details") == {}
    assert quest_length("just prose") is None


def test_a_quest_without_a_length_reads_none() -> None:
    assert quest_length("{{Quest details|start = Talk to someone}}") is None


def test_a_comment_inside_a_value_is_not_part_of_it() -> None:
    # Gargoyle's real infobox, which is why comments are stripped first.
    text = "{{Infobox Monster|slaylvl = 75|slayxp = 105<!-- before changing this, read -->}}"

    assert monster_slayer_xp(text) == 105.0


def test_mmg_rates_pairs_experience_with_its_amount() -> None:
    rates = mmg_rates(_MMG)

    assert rates is not None
    assert rates.activity == "Underwater Agility and Thieving"
    assert rates.kph == 200.0
    assert rates.experience == {"Thieving": 422.8, "Agility": 4.5}


def test_an_unpaired_experience_entry_is_dropped() -> None:
    rates = mmg_rates("{{Mmgtable|Activity = X|kph = 10|Experience1 = Thieving}}")

    assert rates is not None and rates.experience == {}


def test_a_guide_without_kph_still_parses() -> None:
    rates = mmg_rates("{{Mmgtable|Activity = Buying beer}}")

    assert rates is not None
    assert rates.kph is None
    assert rates.activity == "Buying beer"


def test_a_page_that_is_not_a_guide_reads_none() -> None:
    assert mmg_rates("{{Infobox Quest|length = Long}}") is None


def test_a_guide_without_a_kph_name_counts_kills() -> None:
    """The wiki's default column name is `Kills per hour`, so silence means kills."""
    rates = mmg_rates("{{Mmgtable|Activity = Killing [[General Graardor]]|kph = 27}}")

    assert rates is not None
    assert rates.kph_name == ""
    assert rates.counts_kills


def test_a_relabelled_kph_column_is_not_a_kill_rate() -> None:
    """`Mmgtable` counts whatever its guide is about.

    Reading these as kill rates put a `Unicorn` at 9,000 an hour, which is two
    and a half kills a second.
    """
    grinding = mmg_rates(
        "{{Mmgtable|Activity = Grinding [[unicorn horn]]s"
        "|kph = 9000|kph name = Horns per hour}}"
    )
    thieving = mmg_rates(
        "{{Mmgtable|Activity = Pickpocketing [[Knights of Ardougne]]"
        "|kph = 3000|kph name = Pickpockets per hour}}"
    )

    assert grinding is not None and not grinding.counts_kills
    assert thieving is not None and not thieving.counts_kills


def test_an_explicit_kills_per_hour_label_still_counts_kills() -> None:
    rates = mmg_rates("{{Mmgtable|Activity = X|kph = 30|kph name = Kills per hour}}")

    assert rates is not None and rates.counts_kills


def test_the_label_beats_the_title_verb() -> None:
    """Two real guides say `Killing`/`Looting` and count something else.

    `Killing cows and tanning cowhide` counts leather and `Looting ogre
    coffins` counts coffins, so a title test would admit both. The parameter
    is the wiki's own statement about the column and is what this reads.
    """
    cows = mmg_rates(
        "{{Mmgtable|Activity = Killing cows and tanning cowhide"
        "|kph = 1000|kph name = Leather made per hour}}"
    )

    assert cows is not None and not cows.counts_kills


def test_slayer_assignments_reads_task_amount_and_weight() -> None:
    rows = slayer_assignments(_ASSIGNMENTS)

    assert [(row.task, row.weight, row.low, row.high) for row in rows] == [
        ("Aberrant spectres", 7, 130, 200),
        ("Metal dragons", 14, 35, 45),
    ]
    assert rows[0].mean_count == 165.0


def test_assignment_rows_missing_any_of_the_three_are_skipped() -> None:
    # The header and total rows match none of the three patterns, and a row
    # with a task but no weight is a note rather than an assignment.
    rows = slayer_assignments(_ASSIGNMENTS + "\n|-\n|[[Slayer task/Nothing|Nothing]]\n|1-2\n|}")

    assert len(rows) == 2


def test_an_en_dash_range_parses_like_a_hyphen() -> None:
    row = "|-\n|[[Slayer task/Bloodvelds|Bloodvelds]]\n|120 – 185\n|{{+=|weight|8|echo=2}}"

    assert slayer_assignments(row)[0].mean_count == 152.5


_PLAIN_ASSIGNMENTS = """
{| class="wikitable sortable lighttable"
! Monster !! Amount !! Task weight
|-
| [[Abyssal demon]]s<ref group="n">Needs [[Priest in Peril]].</ref>
| 75-125
|200-250
| {{+=|weight|5|echo=2}}
|-
| [[Ankou]]
| 75-125
| {{+=|weight|6|echo=2}}
|}
"""


def test_a_row_linking_the_monster_directly_still_parses() -> None:
    # Six of the ten masters write `[[Abyssal demon]]s` rather than
    # `[[Slayer task/Abyssal demons|...]]`, and only the second shape was
    # handled - so those masters parsed to nothing and read downstream as
    # "unreachable" rather than "uncollected".
    rows = slayer_assignments(_PLAIN_ASSIGNMENTS)

    assert [(row.task, row.weight, row.low, row.high) for row in rows] == [
        ("Abyssal demons", 5, 75, 125),
        ("Ankou", 6, 75, 125),
    ]


def test_the_plural_outside_the_link_is_kept() -> None:
    # The export keys on the plural, so the trailing `s` is part of the name.
    assert slayer_assignments(_PLAIN_ASSIGNMENTS)[0].task == "Abyssal demons"


def test_a_leading_dot_decimal_is_not_a_whole_number() -> None:
    """**A ten-thousand-fold error, and it reached an estimate.**
    `Experience1num = .5273*20 + .4727*30` matched `5273` against a pattern
    demanding a leading digit, and Fishing came out at 2,604,862 xp/hr."""
    assert parse_number(".5273") == pytest.approx(0.5273)
    assert parse_number(".47") == pytest.approx(0.47)
    assert parse_number("-.5") == pytest.approx(-0.5)


def test_an_experience_field_can_be_arithmetic() -> None:
    """`Catching sardines & herring` is 53% of catches at 20 xp and 47% at 30,
    written as a sum. Reading the first number gets 0.5273 of a catch."""
    assert parse_amount(".5273*20 + .4727*30") == pytest.approx(24.727)
    assert parse_amount("2*3+4") == pytest.approx(10.0)
    assert parse_amount("143.5") == pytest.approx(143.5)


def test_prose_around_a_number_still_falls_back_to_the_first_figure() -> None:
    """Only a value that is *entirely* arithmetic is evaluated; **prose** with
    a letter in it keeps the tolerant reading.

    A *template* does not, and this test used to assert that it did -
    `{{#switch:x|a=66*10.5}}` was read as 66 on the grounds that a leading
    figure is better than nothing. The blood rune guide showed it is not: its
    `Experience1num` really is a `{{#switch:}}`, and the 66 taken out of it
    reached the estimate as 4,620 Runecraft xp an hour.
    """
    assert parse_amount("27 (30 with cape)") == pytest.approx(27.0)
    assert parse_amount("{{#switch:x|a=66*10.5}}") is None
    assert parse_amount("no numbers here") is None


def test_an_expression_is_evaluated_without_eval() -> None:
    """Reference data from a wiki anyone can edit. A name, a call or an
    attribute is refused rather than executed."""
    assert parse_amount("__import__('os')") is None
    # Entirely arithmetic but unevaluable: refused, not silently read as 1.
    assert parse_amount("1/0") is None


def test_experience_already_per_hour_is_not_multiplied_again() -> None:
    """`Subduing Tempoross` states 62,000 Fishing xp an hour and 60 permits an
    hour. Multiplying the two gave 3,720,000."""
    rates = mmg_rates(
        "{{Mmgtable|Activity=Subduing Tempoross|kph=60|kph name=Permits per hour"
        "|Experience1=Fishing|Experience1num=62000|Experience1isph=y}}"
    )

    assert rates is not None
    assert rates.experience["Fishing"] == pytest.approx(62_000)
    assert "Fishing" in rates.per_hour


def test_experience_per_kill_is_the_default() -> None:
    rates = mmg_rates(
        "{{Mmgtable|Activity=Cutting camphor logs|kph=575"
        "|Experience1=Woodcutting|Experience1num=143.5}}"
    )

    assert rates is not None and rates.per_hour == frozenset()


def test_a_wrapped_sum_is_unwrapped_before_it_is_evaluated() -> None:
    """**A guide writes its arithmetic either bare or wrapped**, and reading
    the wrapped form as prose takes its first number instead of its sum.

    `Money making guide/Crafting law runes through the Abyss` says `54*9.5`
    and the death rune one says `{{#expr:67*10}}`. The second was read as 67,
    so 50 laps an hour came out as 3,350 Runecraft xp where the guide states
    33,500 - a factor of ten, arriving as a plausible-looking rate.
    """
    assert parse_amount("{{#expr:67*10}}") == pytest.approx(670.0)
    assert parse_amount("54*9.5") == pytest.approx(513.0)
    assert parse_amount("{{#expr: 2 + 3 }}") == pytest.approx(5.0)


def test_a_value_that_is_still_a_template_is_refused() -> None:
    """**`{{#switch:}}`, `{{#var:}}` and `{{GEP|...}}` are evaluated against
    page state and a live price, neither of which is here**, so the first
    digit inside one is whatever branch the editor happened to write first.

    The blood rune guide is the case that forced this: its `Experience1num`
    is a five-line `{{#switch:}}` over the current price of blood essence, and
    taking the leading number read 66 - which reached the estimate as 4,620
    Runecraft xp an hour, quoted with the same confidence as a real figure.
    Refusing it is the same choice `parse_amount` already makes for arithmetic
    that will not evaluate: "the guide does not say" is the honest answer.
    """
    assert parse_amount("{{#switch:{{#var:essence}}|0=66|#default=77}}") is None
    assert parse_amount("{{#expr:{{GEP|Blood essence}}}}") is None, "a live price"
    assert parse_amount("{{GEP|Nature rune}}") is None
