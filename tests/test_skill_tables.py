"""Tests for `remote/skill_tables.py`: Agility and Thieving rates from wikitext.

Every fixture here is a trimmed copy of a real row, keeping the shapes that
actually caused trouble: a cell naming two NPCs, a template containing `|`, a
disambiguated page title with display text, and the `{{NA}}`/`0` experience
that means "this is not a training method".
"""

from __future__ import annotations

import pytest

from chunksim.model.chunkinfo import ChunkInfo
from chunksim.remote.skill_tables import (
    parse_fishing,
    parse_herblore,
    parse_mining,
    parse_cooking,
    parse_darts,
    parse_gotr,
    parse_glassblowing,
    parse_hunter,
    parse_plunder,
    parse_sailing,
    parse_tithe,
    TITHE_SACK_MULTIPLIER,
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
    # **Both spellings, because a heading may already be singular.** Stripping
    # a trailing `s` from `Sapphire glacialis` gives `glaciali`, which joins
    # nothing while looking like it tried, and no rule tells the two apart.
    assert set(rows) == {
        "Maniacal monkey",
        "Maniacal monkeys",
        "Black chinchompa",
        "Black chinchompas",
    }

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
    from chunksim.costing.heuristics import _DISAMBIGUATOR

    assert _DISAMBIGUATOR.sub("", "black chinchompa (hunter)") == "black chinchompa"
    assert _DISAMBIGUATOR.sub("", "chaos altar (prayer)") == "chaos altar"
    for kept in ("gem stall (mor ul rek)", "counter (gu'tanoth)", "fish stall (port roberts)"):
        assert _DISAMBIGUATOR.sub("", kept) == kept, kept


def test_fishing_joins_only_the_headings_that_name_one_fish() -> None:
    """**A technique is not a fish**, and most of that page's headings are
    techniques: `Fly fishing` catches trout *and* salmon, `Barbarian Fishing`
    three more, where the export has one challenge per fish. Joining those
    would need a hand-built technique-to-fish table *and* one rate for a curve
    that doubles across the technique's range.

    Four headings name a single fish, and `FISHING_BY_FISH` maps each to the
    export's name for it - two of which carry a `Raw ` prefix and two of which
    do not, which is why it is a table and not a rule.
    """
    text = """
== Levels 20-47/58: Fly fishing ==
{|class="wikitable"
! {{SCP|Fishing}} level
! XP/h (AFK)
! XP/h (3-tick)
|-
|20
|13,000
|23,000
|}

== Levels 65-99: Karambwan ==
{|class="wikitable"
! {{SCP|Fishing}} level
! XP/h
|-
|65
|29,000
|}

== Levels 87-99: Sacred eel ==
{|class="wikitable"
! {{SCP|Fishing}} level
! XP/h
|-
|87
|20,000
|}
"""
    rows = {row.name: row.xp_per_hour for row in parse_fishing(text)}
    # Named after one fish, under the export's own name for it.
    assert rows == {"Raw karambwan": 29_000.0, "Sacred eel": 20_000.0}
    # And the technique is refused rather than guessed at.
    assert not any("fly" in name.lower() for name in rows)


def test_barbarian_fishing_is_three_methods_not_one_curve() -> None:
    """**The wiki's level breakpoints are the export's challenge levels.**

    48, 58 and 70 are exactly where leaping trout, salmon and sturgeon unlock,
    so what reads as one technique with a doubling curve is three challenges
    with a rate each - and the band walk then uses the right one at the right
    level with no curve support needed.

    The AFK column, and this skill's own share of it: `XP/h (AFK)` comes
    *before* `XP/h (3-tick)` here, so unlike Hunter's `Alt`/`Solo` the
    conservative group is the first. Within it the `Fishing` column and not
    the `Total`, which folds in Strength and Agility.
    """
    text = """
== Levels 58-71/99: Barbarian Fishing ==
{|class="wikitable"
! rowspan="2" | {{SCP|Fishing}} Level
! colspan="3" | XP/h (AFK)
! colspan="4" | XP/h (3-tick)
|-
! {{SCP|Fishing}}
! {{SCP|Strength}}/{{SCP|Agility}}
! {{SCP}} Total
! {{SCP|Fishing}}
! {{SCP|Strength}}/{{SCP|Agility}}
! {{SCP|Cooking}}
! {{SCP}} Total
|-
| 48
| 23,000
| 2,300
| 27,600
| 41,000
| 4,100
| 5,400
| 54,600
|-
| 70
| 48,000
| 4,400
| 56,800
| 90,000
| 8,200
| 13,800
| 120,200
|-
| 99
| 57,000
| 5,200
| 67,400
| 108,000
| 9,800
| 16,800
| 144,400
|}
"""
    rows = {row.name: row for row in parse_fishing(text)}
    assert set(rows) == {"Leaping trout", "Leaping sturgeon"}, "a row is a fish"
    # AFK Fishing, not 3-tick (41,000) and not the AFK total (27,600).
    assert rows["Leaping trout"].xp_per_hour == 23_000.0
    assert rows["Leaping trout"].level == 48
    assert rows["Leaping sturgeon"].xp_per_hour == 48_000.0
    # Level 99 has no challenge of its own and is dropped rather than
    # inflating sturgeon past the level it is actually used from.
    assert all(row.level != 99 for row in rows.values())


def test_mining_joins_the_headings_that_name_a_rock() -> None:
    """**An earlier pass refused this page and was wrong.** It read the ore
    table (experience per action) and the prose summary, and concluded from
    those two that nothing joined - stopping before the section headings, the
    one shape already proven on Hunter.

    The tick-manipulated column comes *first* here, as on the Hunter page, so
    the last-column rule picks the honest figure rather than the benchmark.
    """
    text = """
== Levels 45-99: Granite ==
{|class="wikitable"
! {{SCP|Mining}} level
! {{SCP|Mining}} XP/h
! {{SCP|Smithing}} XP/h
|-
| 45
| 87,000
| {{NA}}
|}

== Levels 40-99: Gem rocks ==
{|class="wikitable"
!{{SCP|Mining}} level
!XP/h (3-tick)
!XP/h (w/o 3-tick)
|-
|50
|93,000
|46,000
|}

== Levels 30-99: Motherlode Mine ==
{|class="wikitable"
! {{SCP|Mining}} level
! XP/h
|-
|30
|30,000
|}
"""
    rows = {row.name: row.xp_per_hour for row in parse_mining(text)}
    # Named after a rock the export names, under the export's own spelling.
    assert rows == {"Granite": 87_000.0, "Gem rocks": 46_000.0}
    # Not the 3-tick column, and not a heading naming a place rather than a rock.
    assert 93_000.0 not in rows.values()
    assert not any("motherlode" in name.lower() for name in rows)


def test_herblore_reads_the_potion_and_not_its_ingredients() -> None:
    """**The first `{{plinkt}}` in a row is the potion**; the two after it are
    its base and secondary, which are ingredients rather than methods.

    Both the name and its `pic=` are emitted, because the export keys by dose
    (`attack potion(3)`) where the wiki names the potion and puts the dosed
    form in `pic=`. Over the real page the bare name joins 45 challenges and
    the `pic=` form another 35.
    """
    text = """
{|class="wikitable"
! {{SCP|Herblore}} Level
! Potion
! Base
! Secondary
! XP
! XP/Hour
|-
|3
|{{plinkt|Attack potion|pic=Attack potion(3)}}
|{{plinkt|Guam potion (unf)}}
|{{plinkt|Eye of newt}}
|25
|62,500
|}
"""
    rows = {row.name: row for row in parse_herblore(text)}
    # The potion, under both spellings; never the base or the secondary.
    assert set(rows) == {"Attack potion", "Attack potion(3)"}
    assert rows["Attack potion"].xp_per_hour == 62_500.0
    assert rows["Attack potion"].level == 3
    assert rows["Attack potion(3)"].xp_per_hour == 62_500.0


def test_a_hunter_section_with_no_table_is_read_from_its_prose() -> None:
    """**Only six of the Hunter page's twenty-two sections hold a table**, so
    reading tables alone left 10 rated of its 88 methods. The rest state the
    rate in words, and the heading still supplies the name and the level.

    The lowest figure the section quotes wins - a section states a range, a
    better rate with more traps, and a better one still with an alt account
    feeding supplies, and the bottom of a published range is the end this
    project takes everywhere else.
    """
    text = """
== Levels 21-39: Red crabs ==
For initial setup bring a [[hammer]], a [[saw]], 2 [[plank]]s and 4 [[nails]].
Players can gain 31,000 experience per hour with two traps.

== Levels 29-43: Swamp lizards ==
Players can gain around 20,000-28,000 experience per hour at levels 29-37.
With three traps, the rates increase to around 40,000-45,000 experience per hour.
"""
    rows = {row.name: row for row in parse_hunter(text)}

    assert rows["Red crab"].level == 21, "the heading opens the method"
    assert rows["Red crab"].xp_per_hour == 31_000.0

    # The low end of the first range, not the high end and not the three-trap
    # figure the same section also states.
    assert rows["Swamp lizard"].xp_per_hour == 20_000.0

    # `500 coins` and `4 seconds` are prose too - the words must be adjacent.
    assert all(row.xp_per_hour != 2.0 for row in rows.values())


def test_a_tabled_hunter_section_keeps_its_table_rather_than_its_prose() -> None:
    """A table resolves a whole curve where the prose states one ceiling, so
    the two readers must never describe the same technique.

    Black chinchompas are the case: the section tabulates 145,000 at level 73
    and its prose quotes the level-99 cap of 300,000. Reading the prose there
    would price the whole climb at a rate reachable only at 99.
    """
    text = """
== Levels 73-99: Black chinchompas ==
At level 99, the maximum experience rate caps at around 300,000 experience per hour.
{|class="wikitable"
! {{SCP|Hunter}} level
! XP/h
|-
|73
|145,000
|}
"""
    rows = {row.name: row for row in parse_hunter(text)}
    assert rows["Black chinchompa"].xp_per_hour == 145_000.0
    assert rows["Black chinchompa"].level == 73


def test_falconry_is_three_creatures_in_one_section() -> None:
    """**The heading names a technique, so it joins nothing** - exactly like
    Fishing's `Fly fishing`. But each bullet links the kebbit it describes and
    carries its own level range and rate, and the export has a challenge per
    kebbit, so the bullet is the row and the link is the name.
    """
    text = """
== Levels 43-49: Falconry ==
The following rates can be expected while training here:
* [[Spotted kebbit]]s (43-57) give 60,000 up to 70,000.
* [[Dark kebbit]]s (57-60+) give 75,000 up to 80,000.
* [[Dashing kebbit]]s (69+) give 85,000 up to 95,000.
"""
    rows = {row.name: row for row in parse_hunter(text)}
    assert {"Spotted kebbit", "Dark kebbit", "Dashing kebbit"} <= set(rows)

    # The bottom of each published range, and the level the bullet opens at -
    # including `(69+)`, which states no upper bound.
    assert rows["Spotted kebbit"].level == 43
    assert rows["Spotted kebbit"].xp_per_hour == 60_000.0
    assert rows["Dashing kebbit"].level == 69
    assert rows["Dashing kebbit"].xp_per_hour == 85_000.0

    assert "Falconry" not in rows, "a technique names no creature"


def test_darts_are_read_as_experience_per_dart() -> None:
    """**Experience per dart, never per hour**, which is why this table can be
    read at all: dart fletching is one of the few actions the tick system does
    not gate, so no page publishes an hourly figure and none could. Turning it
    into a rate is `heuristics.DART_CYCLE_SECONDS`' decision, stated there.

    The column is found by scanning rather than by resolving `XP/dart` against
    the header, because the two genuinely disagree: `{{plinkt}}` expands to
    *two* rendered cells, which is what the `Dart` header's `colspan="2"`
    counts, where the wikitext splitter sees one. Resolving it landed on
    `XP/buy limit` - 23,400 instead of 1.8, and a bronze dart at 1.4 billion
    experience an hour.
    """
    text = """
{| class="wikitable sortable"
! rowspan="2" |{{SCP|Fletching}} Level
! rowspan="2" colspan="2" class="unsortable" |Dart
! rowspan="2" class="unsortable" |Materials
! rowspan="2" |XP/dart
! rowspan="2" |XP/<br>buy limit
! colspan="3" |GE Price
|-
!GP/dart
!Profit/dart
!GP/XP
|-
|10
|{{plinkt|Bronze dart|txt=Bronze}}
|{{plinkp|Feather}} {{plinkp|Bronze dart tip}}
|1.8
|23,400
|{{Coins|1}}
|{{Coins|2}}
|{{Coins|3}}
|-
|95
|{{plinkt|Dragon dart|txt=Dragon}}
|{{plinkp|Feather}} {{plinkp|Dragon dart tip}}
|25
|275,000
|{{Coins|1}}
|{{Coins|2}}
|{{Coins|3}}
|}
"""
    rows = {row.name: row for row in parse_darts(text)}
    assert set(rows) == {"Bronze dart", "Dragon dart"}, "the plinkt names the item"
    assert rows["Bronze dart"].level == 10
    assert rows["Bronze dart"].experience == pytest.approx(1.8)
    assert rows["Dragon dart"].experience == pytest.approx(25.0)

    # The parser states no rate at all - that separation is the point.
    assert all(row.xp_per_hour is None for row in rows.values())


def test_the_modelled_dart_pace_is_one_set_a_tick() -> None:
    """**A stated assumption, not a measurement**, like the shortcut and
    pickpocket cycles beside it - and the only one whose source explicitly
    declines to publish a number.

    Two clicks make a set of ten and nothing gates the next set, so the rate
    is however fast a person can click; `Fletching training` says 2-4 sets a
    tick is reachable on mobile and stops there. One set a tick is the fair
    intensive pace: 60,000 darts an hour, which puts rune darts at 1,128,000
    xp/hr and dragon at 1,500,000. Pinned because a silent edit here moves the
    top of a whole climb.
    """
    from chunksim.costing.heuristics import DART_CYCLE_SECONDS

    assert DART_CYCLE_SECONDS == pytest.approx(0.06), "ten darts per 0.6s tick"
    assert 3600.0 / DART_CYCLE_SECONDS == pytest.approx(60_000.0)
    assert 18.8 * 3600.0 / DART_CYCLE_SECONDS == pytest.approx(1_128_000.0), "rune"


def test_pyramid_plunder_resolves_into_three_of_its_eight_rooms() -> None:
    """**The wiki's band breakpoints are the export's challenge levels**, which
    is the same coincidence that made Barbarian Fishing tractable.

    The table is `Thieving levels -> XP/hour` over bands, which is the shape
    that makes Fishing's techniques unjoinable - a curve with no one thing to
    name. Here 71, 81 and 91 are exactly where the sixth, seventh and eighth
    rooms unlock, so it resolves into one rate per challenge with nothing
    invented. The five rooms below have no published rate: the guide says the
    rates before 91 are much lower and declines to quote one, so they keep
    nothing rather than inheriting the level-71 figure.
    """
    text = """
===Levels 91-99: Pyramid Plunder===
The experience rates below assume soloing and using the sceptre teleport.
{| class="wikitable"
! {{SCP|Thieving}} levels
! XP/hour
|-
| 71-80
| 125,000
|-
| 81-90
| 190,000
|-
| 91+
| 270,000
|}
"""
    rows = {row.name: row for row in parse_plunder(text)}
    assert set(rows) == {
        "Sixth room of Pyramid Plunder",
        "Seventh room of Pyramid Plunder",
        "Eighth room of Pyramid Plunder",
    }
    # The low end of each band, as everywhere else here.
    assert rows["Sixth room of Pyramid Plunder"].level == 71
    assert rows["Sixth room of Pyramid Plunder"].xp_per_hour == 125_000.0
    assert rows["Eighth room of Pyramid Plunder"].xp_per_hour == 270_000.0


def test_the_plunder_names_are_the_words_the_export_uses() -> None:
    """**The challenge names no object and no NPC, having none**, so the join
    runs through the task's own words - `_join_keys` strips `Access the ` and
    the markup, leaving `sixth room of Pyramid Plunder`. `PLUNDER_BY_LEVEL`
    therefore carries the export's phrasing, the same way `COURSE_ALIASES`
    carries the four course spellings upstream gets wrong.
    """
    from chunksim.costing.heuristics import _join_keys
    from chunksim.remote.skill_tables import COURSE_ALIASES, PLUNDER_BY_LEVEL

    keys = _join_keys(
        {"Level": 71, "Primary": True},
        "Access the sixth room of ~|Pyramid Plunder|~",
        COURSE_ALIASES,
    )
    assert PLUNDER_BY_LEVEL[71].lower() in keys


def test_the_rift_is_read_as_a_curve_over_levels() -> None:
    """**A minigame's rate depends on the player's level, not on which rune
    comes out of it**, so this table has nothing a challenge name joins to.
    The rows are bands named after the minigame; applying them is
    `heuristics._add_gotr`'s job.

    Only the Runecraft column is read. The same table publishes the passive
    Crafting and Mining the minigame also pays, which are real and belong to
    those climbs - a second, separate join rather than a free extra here.
    """
    text = """
==Levels 27-99: Guardians of the Rift==
The rates below assume using the best pouches available.
{| class="wikitable"
!{{SCP|Runecraft}} level
!{{SCP|Runecraft}} XP/h
!{{SCP|Crafting}} XP/h
!{{SCP|Mining}} XP/h
|-
|40-50
|25,000
|2,300
|1,200
|-
|75-85
|50,000
|4,700
|2,500
|}
"""
    rows = {row.level: row for row in parse_gotr(text)}
    assert set(rows) == {40, 75}
    assert all(row.name == "Guardians of the Rift" for row in rows.values())
    assert rows[40].xp_per_hour == 25_000.0
    assert rows[75].xp_per_hour == 50_000.0, "the Runecraft column, not Crafting's"


#: The Farming training guide's whole statement about the minigame.
_TITHE_GUIDE = """
===Tithe Farm===
At level 34, experience may be gained at the [[Tithe Farm]] minigame. In this
way, players can gain significant Farming experience between the time it takes
patches to grow. From level 74 onwards, players can get around 90,000-100,000
experience per hour.
"""

#: The two things `_tithe_tiers` reads off the minigame's own page.
_TITHE_PAGE = """
==Requirements==
*[[Golovanova seed]]s ({{SCP|Farming|34}})
*[[Bologano seed]]s ({{SCP|Farming|54}})
*[[Logavano seed]]s ({{SCP|Farming|74}})

==Rewards==
Players receive bonus experience of 250 times the harvest experience rate when
depositing the 75th fruit-1,500, 3,500, or 5,750 experience for [[Golovanova
fruit|Golovanova]], [[Bologano fruit|Bologano]], and [[Logavano
fruit|Logavano]] respectively.
"""


def test_tithe_farm_computes_the_tiers_the_guide_will_not_quote() -> None:
    """**One published figure, three seed tiers.** The guide quotes only the
    level-74 rate, which used to leave Golovanova (34) and Bologano (54)
    unrated - so Farming could not train at the minigame until 74, when the
    game allows it from 34.

    Lending them the 74 figure would invent a number, so the ratio is computed
    from the minigame's own stated mechanics and only the *scale* is the
    published rate: one sack's duration, fixed so the top tier reads 90,000.
    """
    rows = parse_tithe(_TITHE_GUIDE, _TITHE_PAGE)

    assert [row.level for row in rows] == [34, 54, 74], "one band per seed tier"
    assert all(row.name == "Tithe Farm" for row in rows)
    # The published figure is reproduced exactly, because it is the anchor.
    assert rows[2].xp_per_hour == 90_000.0
    # The other two follow from their own experience per sack, and land far
    # below it rather than borrowing it.
    assert round(rows[0].xp_per_hour or 0.0) == 23_478
    assert round(rows[1].xp_per_hour or 0.0) == 54_783


def test_a_tithe_sack_reproduces_the_wikis_published_totals() -> None:
    """**The multiplier is a derivation, so it has to land on the wiki's own
    numbers.** `TITHE_SACK_MULTIPLIER` comes from the Rewards section's stated
    mechanics - ten times harvest to deposit, the 75th paying a 250x bonus,
    the 75th to 100th doubled - and the wiki separately publishes what a full
    sack pays for each fruit. If the derivation is right the two agree to the
    experience point, for all three.
    """
    for harvest, published in ((6.0, 9_660.0), (14.0, 22_540.0), (23.0, 37_030.0)):
        assert TITHE_SACK_MULTIPLIER * harvest == published


def test_tithe_falls_back_to_the_published_row_without_the_minigame_page() -> None:
    """A cache fetched before the minigame page was read holds one row, which
    is what this returned before the tiers were computed. Degrading to that is
    right; computing a curve off half the mechanics is not."""
    rows = parse_tithe(_TITHE_GUIDE)

    assert len(rows) == 1
    assert (rows[0].level, rows[0].xp_per_hour) == (74, 90_000.0)

    assert parse_tithe("===Tithe Farm===\nNo figure here.", _TITHE_PAGE) == ()


def test_tithe_ignores_a_minigame_page_it_cannot_read_whole() -> None:
    """Both reads or neither. Half the mechanics would still produce three
    plausible-looking bands, and that is the failure worth refusing."""
    levels_only = "*[[Golovanova seed]]s ({{SCP|Farming|34}})"

    assert len(parse_tithe(_TITHE_GUIDE, levels_only)) == 1


def test_the_barracuda_trials_are_nine_rows_of_trial_against_rank() -> None:
    """**The fastest Sailing experience from level 30**, and the reason the
    skill stopped being refused outright.

    Regular enough to need no mapping table: the trial comes from the row's
    own wiki link and the rank from `BARRACUDA_RANKS`, giving `Complete
    <trial> at <rank> rank` - the export's challenge name exactly.
    """
    text = """
== Levels 30-99: Barracuda trials ==
{| class="wikitable"
|-
! rowspan="2" | {{SCP|Sailing}} Level
! rowspan="2" | Trial
! colspan="2" | Swordfish
! colspan="2" | Shark
! colspan="2" | Marlin
|-
!XP / Trial
!XP / Hour
!XP / Trial
!XP / Hour
!XP / Trial
!XP / Hour
|-
| 72
| [[The Gwenith Glide]]
| {{formatnum:{{#expr:(3050 + 1050) round 0}}}}
| {{formatnum:{{#expr:(3050 + 1050)*60*60/(120+10) round 0}}}}
| {{formatnum:{{#expr:(7250 + 2065) round 0}}}}
| {{formatnum:{{#expr:(7250 + 2065)*60*60/(222+10) round 0}}}}
| {{formatnum:{{#expr:(16050 + 3360) round 0}}}}
| {{formatnum:{{#expr:(16050 + 3360)*60*60/(369+10) round 0}}}}
{{formatnum:{{#expr:(16050 + 3360)*60*60/(369+10) + (250*55) round 0}}}} (with [[crystal extractor]])
|}
"""
    rows = {row.name: row for row in parse_sailing(text)}
    assert set(rows) == {
        "Complete The Gwenith Glide at Swordfish rank",
        "Complete The Gwenith Glide at Shark rank",
        "Complete The Gwenith Glide at Marlin rank",
    }
    assert all(row.level == 72 for row in rows.values())

    # Every cell is `{{formatnum:{{#expr:... round 0}}}}` and holds no bare
    # digits, so reading the first number would take a component of the sum.
    assert rows["Complete The Gwenith Glide at Swordfish rank"].xp_per_hour == pytest.approx(
        113_538, abs=1
    )

    # **The Marlin cell holds two figures**, the second with a crystal
    # extractor on a line of its own. The first is the conservative end - and
    # without picking it the cell reads as two templates, which
    # `wiki.parse_amount` correctly refuses, silently losing the best trial.
    assert rows["Complete The Gwenith Glide at Marlin rank"].xp_per_hour == pytest.approx(
        184_369, abs=1
    )


def test_cooking_reads_meat_and_fish_and_refuses_the_assembled_foods() -> None:
    """**The restriction is the whole of the judgement here.** A fish on a
    range is one raw item and the published experience *is* the action, so a
    per-item table plus one cycle constant describes it. A pie is several
    ingredients over several steps, where that action is the last and cheapest
    of them.

    Read whole, the page put `curry` at 365,596/hr with its ingredients free
    and it topped the climb - the documented material bias picking a method
    nobody would train on.
    """
    text = """
===Meat / fish===
{| class="wikitable"
!Level
! colspan="2" |Item
!XP
!Healing
|-
|1||{{plinkt|Shrimps}}||30||3
|-
|84||{{plinkt|Anglerfish}}||230||22
|}

===Pies===
{| class="wikitable"
!Level
! colspan="2" |Item
!XP
!Healing
|-
|60||{{plinkt|Curry}}||280||19
|}
"""
    rows = {row.name: row for row in parse_cooking(text)}
    assert set(rows) == {"Shrimps", "Anglerfish"}
    assert rows["Anglerfish"].level == 84
    assert rows["Anglerfish"].experience == pytest.approx(230.0)
    assert all(row.xp_per_hour is None for row in rows.values()), "a fact, not a pace"


def test_the_modelled_cooking_pace_is_an_inventory_plus_a_bank_trip() -> None:
    """**A range's pace is the same whatever is on it** - four ticks a cook -
    which is why the wiki publishes experience per food and no hourly figure
    per food. Stated, like the shortcut and dart cycles beside it.

    27 at 2.4s is 64.8s and a bank trip about 10s, so 28 items take 77.2s.
    Checkable against a figure it did not come from: anglerfish at 230 xp
    works out at 300,311/hr where the community quotes ~300,000.
    """
    from chunksim.costing.heuristics import COOK_CYCLE_SECONDS

    assert 3600.0 / COOK_CYCLE_SECONDS == pytest.approx(1305.7, abs=0.1)
    assert 230.0 * 3600.0 / COOK_CYCLE_SECONDS == pytest.approx(300_311, abs=1)


def test_glassblowing_is_craftings_one_table_of_plain_figures() -> None:
    """**Crafting's rates are `{{#var:}}` and `{{#expr:}}` expressions wikitext
    cannot yield**, which is why the skill has no table here - except this
    section, whose `XP` and `XP/h` columns are literal, the hourly one stated
    in a footnote as 1,750 items blown an hour.

    The plinkt names the blown item, which is the export's `Output`.
    """
    text = """
===Levels 1-83/99: Molten glass===
{| class="wikitable sortable"
! rowspan="2" |{{SCP|Crafting}} Level
! colspan="2" rowspan="2" | Item
! rowspan="2" |XP
! rowspan="2" |XP/h
! colspan="3" |GE Price
|-
!Buy
!Sell
!Diff
|-
|46
|{{plinkt|Unpowered orb}}
|52.5||91,875
|{{Coins|{{GEP|Molten glass}}}}
|{{Coins|{{GEPT|Unpowered orb}}}}
|{{Coins|1}}
|}
"""
    rows = {row.name: row for row in parse_glassblowing(text)}
    assert set(rows) == {"Unpowered orb"}
    assert rows["Unpowered orb"].level == 46
    assert rows["Unpowered orb"].xp_per_hour == 91_875.0


class TestTheShortcutListHasTwoTables:
    """`Shortcuts` ends with a second list under the same `Level(s)`/`XP`
    headers, headed `Obstacle` rather than `Shortcut` - twenty rows of things
    the world map does not mark with the icon. `table_with` returns the first
    match, so all twenty went unfetched and a dozen Agility challenges had no
    page in the index to reach - see `TestAFetchedPageStillHasToBeReachedByName`
    for why five of them needed an alias on top."""

    _PAGE = """
{| class="wikitable"
!Level(s)
!Icon
!Shortcut
!Notes
!XP
|-
|1
|x
|[[Stepping stone (Lumbridge Swamp Caves)|stone]]
|n
|3
|}

Some prose.

{| class="wikitable"
!Level(s)
!Icon
!Obstacle
!Notes
!XP
|-
|15
|x
|[[Monkey bars (Edgeville Dungeon)|bars]]
|n
|20
|}
"""

    def test_both_tables_are_read(self) -> None:
        from chunksim.remote.skill_tables import shortcut_pages

        found = shortcut_pages(self._PAGE)

        assert "Stepping stone (Lumbridge Swamp Caves)" in found
        assert "Monkey bars (Edgeville Dungeon)" in found

    def test_table_with_still_returns_only_the_first(self) -> None:
        """The singular is unchanged - callers that really do want one table
        keep it, and only `shortcut_pages` asked for the plural."""
        from chunksim.remote.wikitable import table_with, tables_with

        assert "!Shortcut" in table_with(self._PAGE, "!Level(s)", "!XP")
        assert len(list(tables_with(self._PAGE, "!Level(s)", "!XP"))) == 2

    def test_the_hand_listed_pages_are_appended(self) -> None:
        """Eight obstacles are on neither list - see `EXTRA_SHORTCUT_PAGES`."""
        from chunksim.remote.skill_tables import EXTRA_SHORTCUT_PAGES, shortcut_pages

        found = shortcut_pages(self._PAGE)

        assert set(EXTRA_SHORTCUT_PAGES) <= set(found)

    def test_nothing_is_listed_twice(self) -> None:
        from chunksim.remote.skill_tables import shortcut_pages

        found = shortcut_pages(self._PAGE + self._PAGE)

        assert len(found) == len(set(found))


class TestAFetchedPageStillHasToBeReachedByName:
    """**Fetching a page is necessary and not sufficient**, which was got
    wrong here once. Reading the `Shortcuts` page's second table put
    `Monkey bars (Edgeville Dungeon)` and the two Brimhaven entrance pages
    into the index, and all five challenges that want them still read
    `unpriced` - because upstream states no `Objects` for any of them, so the
    only key on offer is the challenge's own words with the verb stripped."""

    _WANT = {
        "brimhaven dungeon pipe to moss giants shortcut": (
            "Pipe (Brimhaven Dungeon Entrance)"
        ),
        "reverse brimhaven dungeon pipe to moss giants shortcut": (
            "Pipe (Brimhaven Dungeon Entrance)"
        ),
        "beginner stepping stones in brimhaven dungeon shortcut": (
            "Stepping stones (Western Brimhaven Dungeon)"
        ),
        "reverse beginner stepping stones in brimhaven dungeon shortcut": (
            "Stepping stones (Western Brimhaven Dungeon)"
        ),
        "monkey bars under edgeville shortcut": "Monkey bars (Edgeville Dungeon)",
    }

    def test_each_is_aliased(self) -> None:
        from chunksim.remote.skill_tables import SHORTCUT_ALIASES

        for key, page in self._WANT.items():
            assert SHORTCUT_ALIASES.get(key) == page, key

    def test_the_targets_are_the_titles_the_list_links(self) -> None:
        """**The alias must say the *linked* title, not the canonical one.**
        The wiki files these under `Pipe (Brimhaven Dungeon entrance)`,
        `Stepping stone (western Brimhaven Dungeon)` and `Monkeybars
        (Edgeville Dungeon)`; `fetch_wiki_pages` follows the redirect and
        keys the result by what was asked for, so `ShortcutInfo.name` carries
        the list's spelling and an alias written from the address bar joins
        nothing."""
        from chunksim.remote.skill_tables import shortcut_pages

        found = set(shortcut_pages(TestTheShortcutListHasTwoTables._PAGE))

        assert {"Monkey bars (Edgeville Dungeon)"} <= found

    @pytest.mark.real_export
    def test_none_of_them_states_an_objects_to_join_on(
        self, real_export: ChunkInfo
    ) -> None:
        """The reason an alias is needed at all. If upstream ever names the
        scenery, `shortcut_keys` reaches the page unaided and these five
        entries become dead weight rather than load-bearing."""
        agility = real_export.challenges["Agility"]
        wanted = {key for key in self._WANT}
        seen = set()
        for task, entry in agility.items():
            if not isinstance(entry, dict) or entry.get("Primary") is not True:
                continue
            key = task.removeprefix("Access the ").replace("~|", "").replace("|~", "")
            if key.lower() in wanted:
                seen.add(key.lower())
                assert not entry.get("Objects"), task
        assert seen == wanted


class TestAnUnversionedFieldCoversEveryVersion:
    """`Pipe (Brimhaven Dungeon)` is `level1 = 34`, `level2 = 1` and a single
    `xp = 10`. Asking only for `xp1`/`xp2` found neither and dropped the whole
    page - the forward shortcut with it. `failxp` already fell back this way."""

    _BOX = """{{Agility info
|version1 = To the demons
|version2 = To the dragons
|name = Pipe
|level1 = 34
|level2 = 1
|xp = 10
|type = Shortcut
}}"""

    def test_both_versions_take_the_shared_experience(self) -> None:
        from chunksim.remote.skill_tables import parse_agility_info

        found = parse_agility_info(self._BOX, "Pipe (Brimhaven Dungeon)")

        assert [(info.level, info.experience) for info in found] == [(34, 10.0), (1, 10.0)]

    def test_a_versioned_experience_still_wins(self) -> None:
        """The fallback fills, it does not overwrite - a page stating `xp1`
        means that version pays it."""
        from chunksim.remote.skill_tables import parse_agility_info

        found = parse_agility_info(
            self._BOX.replace("|xp = 10", "|xp1 = 25\n|xp = 10"),
            "Pipe (Brimhaven Dungeon)",
        )

        assert [info.experience for info in found] == [25.0, 10.0]
