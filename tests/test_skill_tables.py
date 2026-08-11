"""Tests for `remote/skill_tables.py`: Agility and Thieving rates from wikitext.

Every fixture here is a trimmed copy of a real row, keeping the shapes that
actually caused trouble: a cell naming two NPCs, a template containing `|`, a
disambiguated page title with display text, and the `{{NA}}`/`0` experience
that means "this is not a training method".
"""

from __future__ import annotations

import pytest

from fray_claude.remote.skill_tables import (
    parse_hunter,
    parse_woodcutting,
    parse_courses,
    parse_mark_rate,
    parse_pickpockets,
    parse_shortcuts,
    parse_stalls,
)

_SHORTCUTS = """
{| class="wikitable sortable"
!Level(s)
!Icon
!Shortcut
!Location
!Notes
!XP
|-
|{{SCP|Agility|5}}
|[[File:Agility shortcut climb.png]]
|[[Climbing rocks (Yanille)|Climbing rocks]]
|[[Yanille]]
|One-way out of Yanille.
|25
|-
|{{SCP|Agility|8}}<br/>{{SCP|Strength|19}}<br/>{{SCP|Ranged|37}}
|{{NA}}
|[[Broken Raft]]
|Over the [[River Lum]]
|Goes both ways.
|{{NA}}
|-
|{{SCP|Agility|10}}
|{{NA}}
|[[Rocks (Corsair Cove)|Rocks]]
|[[Corsair Cove]]
|Access to [[Feldip Hills]].
|0
|}
"""

_COURSES = """
{| class="wikitable sortable"
!{{SCP|Agility}}
! colspan=2 |Course
!Category
!Experience per hour
!Reward item
!Notes
|-
|1||{{plinkt|Gnome Stronghold Agility Course|pic=Swamp toad (item)}}||Regular Course
|10,000||{{plinkp|Mark of grace}}||Impossible to fail.
|-
|50||{{plinkt|Falador Rooftop Course|pic=Mark of grace}}||Rooftop Agility Course
|35,000||{{plinkp|Mark of grace}}||
|}
"""

_STALLS = """
{| class="wikitable sortable"
! colspan=2 | Stall
!{{SCP|Thieving}}Level
!Exp.
!Items
!Location
!Respawn Time
! Max XP/Hr
!Leagues Region
|-
|{{plinkt|Vegetable stall|pic=Cabbage}}
|2
|10
|[[Onion]], [[cabbage]]
|[[Miscellania]]
|1.2 seconds
| 30,000
|{{leagueRegionIcon|Fremennik}}
|}
"""

_PICKPOCKETS = """
{| class="wikitable sortable"
!colspan="2"| Name
!{{SCP|Thieving}} Level
![[Experience|XP]]
!{{plinkp|Ardougne cloak 3}} 100% success lvl
![[Stun (status)|Stun]] damage
!Notes
|-
|{{plinkt|Man|pic=Thief Man}}/[[Woman]]
| 1 || 8 || 85 || 1
| Found all around [[Gielinor]].
|-
|{{plinkt|Warrior (Thieving)|pic=Thief Warrior|txt=Warrior}}
|25 || 26 || 93 || 2
|Commonly found in [[East Ardougne]].
|}
"""


def test_a_shortcut_carries_its_object_and_the_xp_one_use_pays() -> None:
    """**The link target, not the display text.** `[[Climbing rocks
    (Yanille)|Climbing rocks]]` renders as "Climbing rocks" and joins as
    nothing - the export names the disambiguated object."""
    (rock,) = parse_shortcuts(_SHORTCUTS)

    assert (rock.name, rock.level, rock.experience) == ("Climbing rocks (Yanille)", 5, 25.0)


def test_a_shortcut_paying_nothing_is_not_a_training_method() -> None:
    """`{{NA}}` and `0` both mean no experience. A zero would divide into an
    infinite rate; keeping the row would invent a training method out of a
    door."""
    names = {row.name for row in parse_shortcuts(_SHORTCUTS)}

    assert "Broken Raft" not in names
    assert "Rocks (Corsair Cove)" not in names


def test_a_shortcut_takes_its_agility_level_not_the_first_one_listed() -> None:
    """A grapple shortcut lists Agility, Strength and Ranged. Reading the first
    number on the row gets whichever the wiki happened to write first."""
    rows = parse_shortcuts(_SHORTCUTS)

    assert all(row.level in (5, 10) for row in rows)


def test_a_course_carries_a_published_rate_rather_than_a_per_action_xp() -> None:
    courses = {row.name: row for row in parse_courses(_COURSES)}

    assert courses["Falador Rooftop Course"].level == 50
    assert courses["Falador Rooftop Course"].xp_per_hour == 35_000.0
    assert courses["Gnome Stronghold Agility Course"].xp_per_hour == 10_000.0


def test_a_stall_takes_the_wikis_own_max_rate() -> None:
    """The last column is already `3600 / respawn * xp`, so the arithmetic is
    upstream's rather than a second copy of it."""
    (stall,) = parse_stalls(_STALLS)

    assert (stall.name, stall.level, stall.experience) == ("Vegetable stall", 2, 10.0)
    assert stall.xp_per_hour == 30_000.0


def test_one_row_naming_two_npcs_yields_both() -> None:
    """`{{plinkt|Man}}/[[Woman]]` is two NPCs sharing a rate, and taking either
    alone silently loses a level-1 training method."""
    rows = {row.name: row for row in parse_pickpockets(_PICKPOCKETS)}

    assert rows["Man"].experience == 8.0
    assert rows["Woman"].experience == 8.0
    assert rows["Man"].level == 1


def test_a_disambiguated_npc_offers_both_spellings() -> None:
    """The wiki page is `Warrior (Thieving)`; the export's NPC is `Warrior`.
    Both are emitted and only the one the export uses is ever looked up."""
    rows = {row.name for row in parse_pickpockets(_PICKPOCKETS)}

    assert {"Warrior (Thieving)", "Warrior"} <= rows


def test_a_template_containing_a_pipe_is_one_cell() -> None:
    """`{{Coins|{{GEP|Amylase crystal|10*13.8}}}}` is full of `|` that mean
    nothing of the sort. Splitting without tracking depth reads a level out of
    half a template."""
    table = """
{| class="wikitable"
!{{SCP|Agility}}
! colspan=2 |Course
!Category
!Experience per hour
!Reward item
!Notes
|-
|60||{{plinkt|Seers' Village Rooftop Course|pic=Mark of grace}}||Rooftop Agility Course
|46,800||{{Coins|{{GEP|Amylase crystal|10*13.8}}}}||Notes here.
|}
"""
    (course,) = parse_courses(table)

    assert (course.name, course.level, course.xp_per_hour) == (
        "Seers' Village Rooftop Course",
        60,
        46_800.0,
    )


def test_an_absent_page_parses_to_nothing_rather_than_raising() -> None:
    """A page the wiki did not return is a gap in coverage, not a crash."""
    assert parse_shortcuts("") == ()
    assert parse_courses("") == ()
    assert parse_stalls("") == ()
    assert parse_pickpockets("") == ()


def test_marks_of_grace_come_from_the_rooftop_table() -> None:
    """**The lap-time column is also a range**, two along, and the header spans
    two rows so the marks column cannot be found by index. `108-110t` has to be
    told apart from `16-18` by shape."""
    table = """
{| class="wikitable"
! rowspan="2" |{{SCP|Agility}}
! rowspan="2" |Course
! rowspan="2" |Exp. per lap
! rowspan="2" |Lap time
! colspan="2" |Hourly rates
|-
!Exp. per hour
!{{plink|Mark of grace|txt=Marks of grace}}
|-
|30
|[[Varrock Rooftop Course]]
|270
|108–110t
|14,000
|8–11.3
|-
|40
|[[Canifis Rooftop Course]]
|240
|73t (43.8s)
|19,700
|16–18
|}
"""
    assert parse_mark_rate(table) == pytest.approx(18.0)


def test_a_page_without_the_column_yields_nothing() -> None:
    assert parse_mark_rate("") is None


#: Four real rows of `Pay-to-play Woodcutting training`'s rates table: a plain
#: one, one whose rate is a range, one carrying footnote markers in both the
#: level and the rate cell, and one with no rate at all.
_WOODCUTTING = """
{| class="wikitable"
!Log
!Level
!Experience
!Experience per hour
!Price
!Members
|-
|{{plinkt|Willow logs|txt=Willow}}
|30
|67.5
|74,000
|{{Coins|1095}}
|{{Members|No}}
|-
|{{plinkt|Teak logs|txt=Teak}}
|35
|85
|90,000–255,000
|{{Coins|1118}}
|{{Members|Yes}}
|-
|{{plinkt|Maple logs|txt=Maple}}
|45
|100<ref group="n">Maple logs yield 110 with the medium Kandarin Diary.</ref>
|48,000–52,800<ref name=":0" group="n">At Seers' Village.</ref>
|{{Coins|480}}
|{{Members|No}}
|-
|{{plinkt|Juniper logs|txt=Juniper}}
|42
|35
|
|{{NA}}
|{{Members|Yes}}
|}
"""


def test_a_log_carries_the_hourly_rate_the_guides_miss() -> None:
    """The money-making guides join 4 of Woodcutting's 53 methods. This table
    publishes an hourly figure for every log, keyed on the log itself."""
    rows = {row.name: row for row in parse_woodcutting(_WOODCUTTING)}

    assert (rows["Willow logs"].level, rows["Willow logs"].xp_per_hour) == (30, 74_000.0)


def test_a_range_is_read_at_its_bottom() -> None:
    """Teak reads `90,000-255,000` because the upper figure is 2-tick
    manipulation, which the page itself calls "difficult and click-intensive"
    and its own note prices without: "the experience is 90,000 per hour".
    Quoting the top would price every climb on a technique almost nobody
    sustains.
    """
    rows = {row.name: row for row in parse_woodcutting(_WOODCUTTING)}

    assert rows["Teak logs"].xp_per_hour == 90_000.0


def test_footnote_markers_do_not_reach_the_numbers() -> None:
    """Both the level and the rate cell carry `<ref>` blocks holding digits of
    their own - a diary name, a village. Read as part of the figure they are
    an order of magnitude."""
    rows = {row.name: row for row in parse_woodcutting(_WOODCUTTING)}

    assert (rows["Maple logs"].level, rows["Maple logs"].xp_per_hour) == (45, 48_000.0)


def test_a_log_with_no_published_rate_is_dropped() -> None:
    """Juniper logs have an empty rate cell. A zero would make them the
    slowest method on the map rather than an unknown one."""
    assert "Juniper logs" not in {row.name for row in parse_woodcutting(_WOODCUTTING)}


def test_the_display_label_is_not_the_join_key() -> None:
    """`{{plinkt|Willow logs|txt=Willow}}` shows "Willow" and means
    `Willow logs`, which is what the export's `Output` holds. Joining on the
    label would match nothing at all."""
    assert "Willow" not in {row.name for row in parse_woodcutting(_WOODCUTTING)}


def test_hunter_rates_are_read_off_the_section_headings() -> None:
    """**Hunter publishes per technique, not per creature**, and names the
    technique in the heading that owns the table rather than in a column.

    Four of the six headings name a creature the export also names; the two
    that do not are activities with no one creature (`Drift net fishing`,
    `Hunters' Rumours`), which is a correct miss and not a gap.
    """
    text = """
== Levels 60-99: Maniacal monkeys ==
{|class="wikitable"
! {{SCP|Hunter}} level
! XP/h
|-
|60
|51,000
|-
|75
|74,000
|}

== Levels 73-99: Black chinchompas ==
{|class="wikitable"
! rowspan="2" |{{SCP|Hunter}} level
! colspan="2" |Alt
! colspan="2" |Solo
|-
!XP/h
!GP/h
!XP/h
!GP/h
|-
|73
|157,000
|{{Coins|1}}
|145,000
|{{Coins|2}}
|}
"""
    rows = {row.name: row for row in parse_hunter(text)}
    assert set(rows) == {"Maniacal monkey", "Black chinchompa"}, "the heading is the key"

    # The lowest level the table quotes - the rate at the level it opens,
    # which is the conservative end of a rate that climbs with level.
    assert rows["Maniacal monkey"].level == 60
    assert rows["Maniacal monkey"].xp_per_hour == 51_000.0

    # And the *last* XP/h column: `Solo` after `Alt`, `No tick manip.` after
    # `Tick manip.` - the figure without a second account or 2-tick clicking.
    assert rows["Black chinchompa"].xp_per_hour == 145_000.0


def test_a_place_parenthetical_is_not_stripped_from_a_join_key() -> None:
    """**The export's skill suffix comes off; a place name must not.**

    `Black chinchompa (Hunter)` is the creature where the bare name is the
    item, so the wiki tabulates only one of them. But the wiki tabulates
    `Gem stall (Mor Ul Rek)` and `Counter (Gu'Tanoth)` *with* their
    parentheticals and at their own rates, so stripping those would fall back
    to a different row's number while still calling the join exact.
    """
    from fray_claude.costing.heuristics import _DISAMBIGUATOR

    assert _DISAMBIGUATOR.sub("", "black chinchompa (hunter)") == "black chinchompa"
    assert _DISAMBIGUATOR.sub("", "chaos altar (prayer)") == "chaos altar"
    for kept in ("gem stall (mor ul rek)", "counter (gu'tanoth)", "fish stall (port roberts)"):
        assert _DISAMBIGUATOR.sub("", kept) == kept, kept
