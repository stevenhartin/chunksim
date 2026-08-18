"""Tests for `costing/combat_xp.py` and `remote/combat.py`.

The arithmetic is small and the constants are the wiki's, so these mostly pin
the things that were easy to get wrong: Magic being 2 per damage rather than 4,
a default kill rate not being multiplied by real hitpoints, and an icon column
not being read as a spell name.
"""

from __future__ import annotations

import json

import pytest

from chunksim.costing.combat_xp import (
    MAGIC_XP_PER_DAMAGE,
    XP_PER_DAMAGE,
    slayer_credit,
    CAST_SECONDS,
    HITPOINTS_XP_PER_DAMAGE,
    MAGIC_XP_PER_DAMAGE,
    XP_PER_DAMAGE,
    best_spell,
    best_target,
    combat_rates,
    farmable_providers,
    hitpoints_credit,
    spawn_caps,
)
from chunksim.costing.heuristics import Heuristics, Rate
from chunksim.costing.heuristics import spell_materials
from chunksim.remote.combat import (
    SpellCost,
    parse_cost,
    parse_speed,
    parse_spell_costs,
    AttackSpell,
    MonsterStats,
    parse_attack_spells,
    parse_monster_stats,
)
from chunksim.derive.active_tasks import TaskClassification
from chunksim.derive.bis import BisResult
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.derive.challenges import ChallengeResult
from chunksim.derive.other_tasks import OtherTasks
from chunksim.derive.pipeline import Derived
from chunksim.derive.sources import SourceIndex


def _derived(monsters: tuple[str, ...]) -> Derived:
    return Derived(
        reachable_sections={},
        expanded_chunks={"100": True},
        source_index=SourceIndex(
            items={},
            objects={},
            monsters={name: {"100": True} for name in monsters},
            npcs={},
            shops={},
            drop_rates={},
        ),
        challenges=ChallengeResult(valid={}, unsupported=frozenset()),
        bis=BisResult(picks={}),
        task_classification=TaskClassification(),
        other_tasks=OtherTasks(),
    )


_STATS = {
    "Wolf": MonsterStats(name="Wolf", hitpoints=69.0),
    "Mithril dragon": MonsterStats(name="Mithril dragon", hitpoints=254.0, experience_bonus=5.0),
}


def test_damage_per_hour_is_kills_times_hitpoints() -> None:
    derived = _derived(("Wolf",))
    heuristics = Heuristics(monsters={"Wolf": Rate(1000.0, "test", "exact")})

    target = best_target(derived, heuristics, _STATS)

    assert target is not None
    assert target.damage_per_hour == pytest.approx(1000.0 * 69.0)


def test_an_xp_multiplier_is_a_percentage() -> None:
    """`experience_bonus` of 5 means 5% more, not 5x. Reading it as a factor
    would make a Mithril dragon five times the trainer it is."""
    derived = _derived(("Mithril dragon",))
    heuristics = Heuristics(monsters={"Mithril dragon": Rate(10.0, "test", "exact")})

    target = best_target(derived, heuristics, _STATS)

    assert target is not None
    assert target.xp_multiplier == pytest.approx(1.05)
    assert target.damage_per_hour == pytest.approx(10.0 * 254.0 * 1.05)


def test_a_monster_with_only_a_default_kill_rate_is_refused() -> None:
    """**A guessed rate must not be multiplied by real hitpoints.** The
    product looks like a measurement and is not one."""
    derived = _derived(("Wolf",))

    assert best_target(derived, Heuristics(), _STATS) is None


def test_magic_is_two_experience_per_damage_and_the_rest_are_four() -> None:
    """The mistake this exists to prevent: the wiki is explicit that Magic is
    2 per damage where melee and Ranged are 4, and it is a factor of two on
    the whole climb."""
    derived = _derived(("Wolf",))
    heuristics = Heuristics(monsters={"Wolf": Rate(100.0, "test", "exact")})
    damage = 100.0 * 69.0

    rates, _ = combat_rates(derived, heuristics, _STATS, (), {"Magic": 1})

    assert rates["Strength"].value == pytest.approx(damage * XP_PER_DAMAGE)
    assert rates["Ranged"].value == pytest.approx(damage * XP_PER_DAMAGE)
    assert rates["Magic"].value == pytest.approx(damage * MAGIC_XP_PER_DAMAGE)
    assert rates["Hitpoints"].value == pytest.approx(damage * HITPOINTS_XP_PER_DAMAGE)


def test_a_cast_pays_its_base_experience_on_top_of_the_damage() -> None:
    """Two thirds of a Magic rate is the casting, so leaving it out is not a
    rounding error."""
    derived = _derived(("Wolf",))
    heuristics = Heuristics(monsters={"Wolf": Rate(100.0, "test", "exact")})
    spells = (AttackSpell(name="Ice Barrage", level=94, experience=52.0),)

    rates, _ = combat_rates(derived, heuristics, _STATS, spells, {"Magic": 94})

    expected = 100.0 * 69.0 * MAGIC_XP_PER_DAMAGE + 52.0 * 3600.0 / CAST_SECONDS
    assert rates["Magic"].value == pytest.approx(expected)
    assert "Ice Barrage" in rates["Magic"].source


def test_the_best_spell_is_the_one_that_pays_most_not_the_highest_level() -> None:
    """Fire Surge is level 95 and 50.5 xp; Ice Barrage is 94 and 52. Taking
    the highest castable *level* quietly takes the worse one."""
    spells = (
        AttackSpell(name="Ice Barrage", level=94, experience=52.0),
        AttackSpell(name="Fire Surge", level=95, experience=50.5),
    )

    assert best_spell(spells, 99) is not None
    assert best_spell(spells, 99).name == "Ice Barrage"  # type: ignore[union-attr]
    assert best_spell(spells, 94).name == "Ice Barrage"  # type: ignore[union-attr]
    assert best_spell(spells, 50) is None


def test_a_monster_with_no_hitpoints_is_dropped_rather_than_zeroed() -> None:
    """A zero would make it free to kill and infinitely fast to train on."""
    parsed = parse_monster_stats(
        [
            {"name": "Ghost", "hitpoints": 0},
            {"name": "Nothing", "hitpoints": None},
            {"name": "Wolf", "hitpoints": 69, "experience_bonus": 0},
        ]
    )

    assert set(parsed) == {"Wolf"}


def test_the_first_version_of_a_monster_wins() -> None:
    """`TzHaar-Xil` has three rows. Whichever the iteration ends on is not a
    decision anyone made."""
    parsed = parse_monster_stats(
        [
            {"name": "TzHaar-Xil", "hitpoints": 120},
            {"name": "TzHaar-Xil", "hitpoints": 999},
        ]
    )

    assert parsed["TzHaar-Xil"].hitpoints == 120.0


def test_an_icon_column_is_not_a_spell_name() -> None:
    """Ancient Magicks leads with two image columns, and `[[File:Ice
    Barrage.png]]` is a perfectly good link target - it just names a picture."""
    page = """
{| class="wikitable"
!class="unsortable"|Icon
!class="unsortable" |Mobile icon
!Spell
!Level
!class="unsortable"|Runes
!Coins
!XP
!Base max hit
!Effect
|-
|[[File:Ice Barrage.png]]
|[[File:Ice Barrage (mobile).png]]
|[[Ice Barrage]]
|94
|{{RuneReq|Blood=2|Ice=6|Death=4}}
|1000
|52
|30
|Freezes.
|}
"""
    (spell,) = parse_attack_spells({"Ancient Magicks": page})

    assert (spell.name, spell.level, spell.experience) == ("Ice Barrage", 94, 52.0)


def test_a_table_with_no_max_hit_column_contributes_nothing() -> None:
    """**The filter that keeps Charge out.** `infobox_spell` cannot tell an
    attack spell from a utility one - Fire Surge, Charge and Vengeance have
    identical infoboxes - so the attack table is identified by its max-hit
    column, and a utility table has none."""
    page = """
{| class="wikitable"
!colspan=2|Spell
!Level
!class="unsortable"|Runes
!XP
!Members
|-
|{{plinkt|Charge}}
|80
|{{RuneReq|Air=3}}
|180
|{{members|yes}}
|}
"""
    assert parse_attack_spells({"Standard spellbook": page}) == ()


def test_hitpoints_is_credited_with_what_the_other_climbs_earn() -> None:
    """**Hitpoints is not a climb you make.** Every point of damage paying 4 XP
    to Strength pays 1.33 to Hitpoints at the same instant, so charging for
    both in full bills the same hours twice."""
    hours = {"Strength": 10.0, "Ranged": 5.0}
    damage = {"Strength": 40_000.0, "Ranged": 30_000.0}

    credit = hitpoints_credit(hours, damage)

    assert credit == pytest.approx((10.0 * 40_000 + 5.0 * 30_000) * HITPOINTS_XP_PER_DAMAGE)


def test_the_hitpoints_climb_does_not_credit_itself() -> None:
    """Its own hours are the thing being reduced; counting them would be
    circular and would zero the skill outright."""
    credit = hitpoints_credit({"Hitpoints": 100.0}, {"Hitpoints": 50_000.0})

    assert credit == 0.0


def test_a_monster_you_can_only_meet_inside_a_raid_is_not_a_training_target() -> None:
    """**Reachable is not farmable.** The export places 21 monsters in
    `Chambers of Xeric` and the derivation rightly calls them reachable - you
    really can get their drops by doing the raid. What you cannot do is kill
    Muttadile over and over to train Strength."""
    derived = _derived(("Muttadile#Small", "Bloodveld"))
    object.__setattr__(
        derived.source_index,
        "monsters",
        {
            "Muttadile#Small": {"Chambers of Xeric": True},
            "Bloodveld": {"Chambers of Xeric": True, "Catacombs of Kourend": True},
        },
    )

    farmable = farmable_providers(derived)

    assert "Muttadile#Small" not in farmable
    # Reachable in a raid *and* somewhere you can stand: still farmable.
    assert "Bloodveld" in farmable


def test_a_spawn_cap_bounds_a_kill_rate_by_what_the_map_holds() -> None:
    """A chunk holding two of something cannot supply 900 kills an hour
    whatever the gear says."""
    info = ChunkInfo({"chunks": {"100": {"Monster": {"Wolf": 2}}}})
    derived = _derived(("Wolf",))

    caps = spawn_caps(info, derived, respawn=30.0)

    assert caps["Wolf"] == pytest.approx(2 * 3600 / 30)


def test_a_monster_with_no_counted_spawn_is_not_capped_at_zero() -> None:
    """`skillItems` activities and superiors are reachable providers with no
    square of their own; capping those at nothing would delete them."""
    info = ChunkInfo({"chunks": {"100": {}}})

    assert spawn_caps(info, _derived(("Wolf",))) == {}


# --- the Slayer credit -----------------------------------------------------
#
# **There is no oracle for any of this**, which is what the plan says about
# Phase 4: nothing upstream records what a shared climb ought to cost. So these
# are invariants - never more than the need, never more than the damage can
# pay, deterministic under reordering - rather than numbers someone chose.


def test_slayer_pays_hitpoints_alongside_everything_else() -> None:
    """Hitpoints is never in competition: every point of damage pays it 1.33
    whatever style dealt the damage."""
    credit = slayer_credit(1_000_000.0, {"Hitpoints": 10_000_000.0})

    assert credit["Hitpoints"] == pytest.approx(1_000_000.0 * 4 / 3)


def test_a_credit_never_exceeds_what_the_climb_still_needs() -> None:
    """The credit is XP taken off the front of a climb, so a climb that is
    nearly done cannot be credited past its goal and into another skill."""
    credit = slayer_credit(1_000_000.0, {"Hitpoints": 500.0, "Defence": 900.0})

    assert credit["Hitpoints"] == 500.0
    assert credit["Defence"] == 900.0


def test_the_attacking_skills_share_the_damage_not_the_experience() -> None:
    """**A kill is dealt in one style**, so two attacking skills cannot both
    be paid for the same damage. Sharing the *experience* would hand 4 XP per
    damage to each of them and pay for two climbs with one fight."""
    damage = 1_000.0
    credit = slayer_credit(damage, {"Attack": 800.0, "Defence": 10_000.0})

    # Attack is finished off first and the rest goes to Defence, but the two
    # together never spend more damage than was dealt.
    spent = sum(
        value / XP_PER_DAMAGE for skill, value in credit.items() if skill != "Hitpoints"
    )
    assert spent == pytest.approx(damage)
    assert credit["Attack"] == 800.0
    assert credit["Defence"] == pytest.approx((damage - 800.0 / XP_PER_DAMAGE) * XP_PER_DAMAGE)


def test_magic_converts_at_its_own_rate(
) -> None:
    """Magic is 2 XP per damage where melee is 4 - the easy mistake and a
    factor of two on the whole climb. Sharing damage rather than experience is
    what keeps that honest instead of averaging the two."""
    credit = slayer_credit(1_000.0, {"Magic": 10_000.0})

    assert credit["Magic"] == pytest.approx(1_000.0 * MAGIC_XP_PER_DAMAGE)


def test_the_allocation_does_not_depend_on_the_input_order() -> None:
    """**`--jobs` must not move a total.** The allocation is greedy, so the
    order it considers goals in decides the answer when the damage runs out -
    which makes determinism a property to pin rather than assume."""
    import random

    needs = {"Attack": 5_000.0, "Defence": 900_000.0, "Magic": 40_000.0, "Ranged": 7_000.0}
    expected = slayer_credit(2_000.0, needs)
    for seed in range(50):
        items = list(needs.items())
        random.Random(seed).shuffle(items)
        assert slayer_credit(2_000.0, dict(items)) == expected


def test_more_slayer_never_credits_less() -> None:
    """Monotonic in the damage, which is the one thing a reader will assume
    without being told."""
    needs = {"Hitpoints": 9_000_000.0, "Attack": 300_000.0, "Defence": 12_000_000.0}
    totals = [sum(slayer_credit(float(d), needs).values()) for d in range(0, 3_000_000, 250_000)]

    assert totals == sorted(totals)


def test_no_damage_credits_nothing() -> None:
    """A map with no Slayer goal must be priced exactly as it was before this
    existed - the credit is an adjustment, never a floor."""
    assert slayer_credit(0.0, {"Hitpoints": 1_000.0, "Attack": 1_000.0}) == {}


def test_a_finished_skill_takes_none_of_the_pool() -> None:
    """`w_s = 1 while below goal, 0 after`. A skill already at its target must
    not consume damage that another skill could still spend."""
    credit = slayer_credit(1_000.0, {"Attack": 0.0, "Defence": 100_000.0})

    assert "Attack" not in credit
    assert credit["Defence"] == pytest.approx(1_000.0 * XP_PER_DAMAGE)


_ARDOUGNE_COST = (
    '<span style="white-space:nowrap">   <sup>2</sup>'
    "[[File:Water rune.png|Water|link=Water rune]]       <sup>2</sup>"
    "[[File:Law rune.png|Law|link=Law rune]]          </span>"
)


def test_a_spell_cost_reads_its_quantities_and_its_items() -> None:
    assert parse_cost(_ARDOUGNE_COST) == {"Water rune": 2, "Law rune": 2}


def test_a_cost_entry_with_no_superscript_is_one() -> None:
    """8 of the 201 spells write a single rune with no `<sup>` at all."""
    cost = '<span style="white-space:nowrap">[[File:Law rune.png|Law|link=Law rune]]</span>'

    assert parse_cost(cost) == {"Law rune": 1}


def test_only_the_consumed_span_is_read() -> None:
    """**The restriction that tells a material from a tool.** The wiki puts a
    spell's runes in a `white-space:nowrap` span and its required equipment in
    a `plinkp-template` span after it, so reading the whole field charges Iban
    Blast for a staff it never uses up.
    """
    cost = (
        '<span style="white-space:nowrap"><sup>5</sup>'
        "[[File:Fire rune.png|Fire|link=Fire rune]]</span>"
        '<span class="plinkp-template">[[File:Iban\'s staff.png|link=Iban\'s staff]]</span>'
    )

    assert parse_cost(cost) == {"Fire rune": 5}


def test_a_spell_needs_both_halves_to_be_stored() -> None:
    """Seconds per XP needs a cost *and* an experience figure; a spell missing
    either is dropped rather than stored as a zero that would price free."""
    rows = [
        {"page_name": "Ardougne Teleport", "json": '{"exp": "61", "cost": %s}'
         % json.dumps(_ARDOUGNE_COST)},
        {"page_name": "No cost", "json": '{"exp": "61", "cost": ""}'},
        {"page_name": "No xp", "json": '{"exp": "", "cost": %s}' % json.dumps(_ARDOUGNE_COST)},
        {"page_name": "Not json", "json": "{"},
    ]

    costs = parse_spell_costs(rows)

    assert set(costs) == {"Ardougne Teleport"}
    assert costs["Ardougne Teleport"].experience == 61.0
    assert costs["Ardougne Teleport"].items == {"Water rune": 2, "Law rune": 2}


def test_a_cast_task_joins_the_spell_page_by_its_own_words() -> None:
    info = ChunkInfo(
        {"challenges": {"Magic": {
            "Cast ~|ardougne teleport|~": {"Level": 51},
            "Cast ~|ardougne teleport|~ from a spell sack": {"Level": 51},
        }}}
    )
    costs = {"Ardougne Teleport": SpellCost("Ardougne Teleport", 61.0, {"Law rune": 2})}

    joined = spell_materials(info, costs)

    assert set(joined) == {"Cast ~|ardougne teleport|~"}
    assert joined["Cast ~|ardougne teleport|~"].items == {"Law rune": 2}


@pytest.mark.parametrize(
    ("task", "page"),
    [
        ("Cast ~|ape atoll teleport|~", "Ape Atoll Teleport (standard)"),
        ("Cast ~|fenkenstain's castle teleport|~", "Fenkenstrain's Castle Teleport"),
        ("Cast ~|teleport block|~", "Tele Block"),
    ],
)
def test_the_three_spellings_the_export_and_the_wiki_disagree_on(task: str, page: str) -> None:
    """One disambiguated page, one wiki abbreviation and one **export
    misspelling** - three unrelated causes, which is why it is a table."""
    info = ChunkInfo({"challenges": {"Magic": {task: {"Level": 1}}}})

    assert spell_materials(info, {page: SpellCost(page, 10.0, {"Law rune": 1})}) != {}


@pytest.mark.real_cache
def test_most_of_the_exports_cast_challenges_have_a_rune_cost(real_export: ChunkInfo) -> None:
    """Pins the join over the scrape that ships, read back through
    `heuristics.load` so the test exercises the shape rather than the parse.

    The misses are all `... from a spell sack` and `... from a rune pouch`,
    where the runes come out of a container rather than being supplied - so a
    miss is the right answer there, not a gap.
    """
    from chunksim.costing.heuristics import load
    from chunksim.store.cache import data_root, read_blob

    priced = load(read_blob("wiki_rates", data_root())["data"]).spell_costs
    casts = {n for n in real_export.challenges["Magic"] if n.startswith("Cast ")}

    # **"Most", which is what the name claims** - not 190 of 214, which is what
    # they happened to be on 2026-08-14. Both sides are live: upstream adds
    # `Cast` challenges and the wiki scrape follows, so an exact pair fails on
    # the next good day either of them has.
    # **Plus the ten upstream does not call a cast at all** - `Smelt a ~|steel
    # bar|~ with superheat item` is a Superheat Item cast filed under the bar,
    # because it pays Smithing as well. See `heuristics.SPELL_NAME_SUFFIXES`;
    # nothing else in the export names a spell by suffix.
    superheat = {n for n in real_export.challenges["Magic"] if n.endswith("with superheat item")}

    assert len(casts) > 150
    assert len(superheat) >= 10
    assert len(priced) > len(casts) * 0.8
    assert set(priced) <= casts | superheat
    assert superheat <= set(priced), "the Magic half of superheating is a method too"
    assert all("spell sack" in n or "rune pouch" in n for n in casts - set(priced))
    assert priced["Cast ~|varrock teleport|~"].items == {
        "Air rune": 3,
        "Fire rune": 1,
        "Law rune": 1,
    }


# --- the cast speed, which the Bucket does not carry ---------------------


@pytest.mark.parametrize(
    "line,ticks",
    [
        ("|speed = 5 ticks", 5.0),
        ("| speed = 3 ticks (7 on autocast)", 3.0),
        ("|speed = 1 ticks (3 on autocast)", 1.0),
        ("|speed = 3 [[RuneScape clock|ticks]] (6 on autocast)", 3.0),
        ("|speed = 3 ticks (5 ticks in the Alchemist's Playground)", 3.0),
        ("|speed = 0 ticks", 0.0),
    ],
)
def test_the_leading_figure_is_the_manual_cast(line: str, ticks: float) -> None:
    """**The field is prose as often as not**, and in every one of those the
    first number is the manual cast - which is the one a player training the
    spell is making. An autocast is a combat cadence and belongs to
    `costing/combat_xp.py`."""
    assert parse_speed(line) == ticks


@pytest.mark.parametrize("line", ["|quest = None", "|speed = 1", "", "|cooldown = 9 ticks"])
def test_a_page_stating_no_speed_is_untimed_rather_than_instant(line: str) -> None:
    """`None`, never a default: an unknown duration priced at zero is the
    fastest method in the game. Measured, 200 of the export's 201 spell pages
    state a speed, and `Shadow Veil` is the one whose value carries no unit."""
    assert parse_speed(line) is None


def test_the_kind_and_the_speed_travel_with_the_cost() -> None:
    """`type` is upstream's own classification of what a cast is aimed at, and
    it is what `costing/spells.py` reads to tell a spell-on-item loop from a
    teleport's animation."""
    rows = [
        {
            "page_name": "High Level Alchemy",
            "json": json.dumps(
                {
                    "exp": "65",
                    "type": "Utility",
                    "cost": '<span style="white-space:nowrap"><sup>1</sup>'
                    "[[File:Nature rune.png|Nature|link=Nature rune]]</span>",
                }
            ),
        }
    ]

    found = parse_spell_costs(rows, {"High Level Alchemy": "|speed = 5 ticks"})

    assert found["High Level Alchemy"].kind == "Utility"
    assert found["High Level Alchemy"].ticks == 5.0


def test_no_pages_leaves_every_cost_untimed() -> None:
    """A supported way to run: the rune costs are what this fed before a rate
    needed the duration, and `costing/spells.py` refuses an untimed spell."""
    rows = [
        {
            "page_name": "High Level Alchemy",
            "json": json.dumps(
                {
                    "exp": "65",
                    "type": "Utility",
                    "cost": '<span style="white-space:nowrap"><sup>1</sup>'
                    "[[File:Nature rune.png|Nature|link=Nature rune]]</span>",
                }
            ),
        }
    ]

    assert parse_spell_costs(rows)["High Level Alchemy"].ticks is None


class TestACooldownIsACastSpeed:
    """The two differ in *when* the wait falls - a speed blocks before the
    spell lands, a cooldown is an instant cast followed by a wait before the
    next one - and for experience an hour that is the same cycle either way."""

    def test_a_cooldown_answers_where_the_speed_is_blank(self) -> None:
        """Eleven of the seventeen spells with a blank `speed` state one: the
        Arceuus offerings, corruptions, wards and charges."""
        from chunksim.remote.combat import parse_cadence, parse_cooldown

        page = "|speed =\n|cooldown = 50 ticks\n"

        assert parse_cooldown(page) == 50.0
        assert parse_cadence(page) == 50.0

    def test_a_speed_wins_where_there_is_no_cooldown(self) -> None:
        from chunksim.remote.combat import parse_cadence

        assert parse_cadence("|speed = 5 ticks\n") == 5.0

    def test_stating_both_takes_the_larger(self) -> None:
        """**The correction this found.** `Mark of Darkness` is `speed = 0
        ticks` with `cooldown = 10`, and the nine resurrections `speed = 4`
        with `cooldown = 16` - so the speed alone priced an instant cast as
        free and the resurrections four times too fast."""
        from chunksim.remote.combat import parse_cadence

        assert parse_cadence("|speed = 0 ticks\n|cooldown = 10 ticks\n") == 10.0
        assert parse_cadence("|speed = 4 ticks\n|cooldown = 16 ticks\n") == 16.0

    def test_neither_stays_unknown(self) -> None:
        """The four reanimations, `Monster Examine` and `Resurrect Crops`
        state a blank `speed` and no cooldown at all - and a duration priced
        at zero is the fastest method in the game."""
        from chunksim.remote.combat import parse_cadence

        assert parse_cadence("|speed =\n|quest = None\n") is None
