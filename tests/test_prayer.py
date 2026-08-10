"""Tests for `remote/prayer.py` and `costing/prayer.py`.

The wikitext here is copied from the live pages - the oak altar's "normal"
base, the teak page's third percentage that is not a multiplier, the jogre
page's `<br>[[File:` name. Every one of them broke a simpler parser first.

No test touches the network; `fetch_wiki_transclusions` is `api.py`'s.
"""

from __future__ import annotations

from typing import Any

from fray_claude.costing.prayer import (
    CHAOS_ALTAR_CHUNK,
    CHAOS_ALTAR_OBJECT,
    offerings,
    prayer_methods,
)
from fray_claude.derive.active_tasks import TaskClassification
from fray_claude.derive.bis import BisResult
from fray_claude.derive.challenges import ChallengeResult
from fray_claude.derive.other_tasks import OtherTasks
from fray_claude.derive.pipeline import Derived
from fray_claude.derive.sources import SourceIndex
from fray_claude.model.chunkinfo import ChunkInfo
from fray_claude.remote.prayer import Altar, Bone, parse_altars, parse_bones

_BONES = """
{{Prayer info
|name = Bones
|level = 1
|shardQty = 4
|xp = 4.5
|type = bone
}}
"""

_SUPERIOR = """
{{Prayer info
|name = Superior dragon bones
|level = 70
|shardQty = 121
|xp = 150
|type = bone
}}
"""

#: Not a bone: ashes are scattered and no altar multiplies them.
_ASHES = """
{{Prayer info
|name = Infernal ashes
|level = 1
|xp = 110
|type = ashes
}}
"""

#: Seven pages name a cooked variant with markup trailing the name.
_JOGRE = """
{{Prayer info
|name = Marinated j&#39; bones<br>[[File:Marinated j' bones (burnt) detail.png|130x130px]]
|level = 1
|xp = 18
|type = bone
}}
"""

_GILDED = (
    "It gives 250% [[Prayer]] experience when a bone is used with it. "
    "With one [[incense burner]] lit, it gives 300% Prayer experience per bone. "
    "When both are lit, it gives 350% Prayer experience."
)

#: The oak altar states its base as a *word*, which is why an unstated base is
#: 100% rather than a parse failure.
_OAK = (
    "It gives normal [[Prayer]] experience when a set of "
    "[[Prayer#Burying bones|bones]] are offered at it. "
    "With one incense burner lit, it gives 150% Prayer experience. "
    "If two incense burners are lit it will give 200% Prayer experience."
)

#: The teak page carries a *third* percentage that is not a multiplier at all.
_TEAK = (
    "It gives 110% [[Prayer]] [[experience]] when [[bones]] are offered at it. "
    "With one incense burner lit, it gives 160% [[Prayer]] [[experience]], while "
    "two lit incense burners will give 210% [[experience]]. "
    "Since the lowest incense burner requires a Construction level of 61, and since "
    "a cloth covered mahogany altar can be built at level 60, the experience boost "
    "from a teak altar will seldom be more than the extra 10%."
)


def test_a_bone_carries_the_number_the_export_lacks() -> None:
    """Experience per bone - the whole reason this module exists. Everything
    else about a set of bones is already in the export's drop tables."""
    (bone,) = parse_bones({"Bones": _BONES})

    assert (bone.name, bone.experience, bone.level) == ("Bones", 4.5, 1)


def test_only_bones_are_read() -> None:
    """`type` separates the 41 bones from the 68 spectral, 31 bonemeal, 23
    reanimated and 5 ashes rows. Ashes are scattered, not buried, and no altar
    multiplies them - pricing them as bones would invent a method."""
    assert parse_bones({"Infernal ashes": _ASHES}) == ()


def test_a_bones_prayer_level_is_kept() -> None:
    """Superior dragon bones are the one set of remains with a level gate, and
    the band walk needs it or a level-70 method prices the climb from 1."""
    (bone,) = parse_bones({"Superior dragon bones": _SUPERIOR})

    assert bone.level == 70


def test_a_name_is_cut_at_its_markup_and_unescaped() -> None:
    """The export writes an apostrophe plainly, so `&#39;` has to be decoded
    or the join silently misses - and the trailing `[[File:…]]` is not part of
    any item's name."""
    (bone,) = parse_bones({"Pasty jogre bones": _JOGRE})

    assert bone.name == "Marinated j' bones"


def test_a_duplicated_name_keeps_the_higher_experience() -> None:
    """`Alan's bones` declares a second `Bones` at 3 xp where the `Bones` page
    itself says 4.5. Whichever page came last would otherwise win, and 3 is
    two thirds of the real climb."""
    low = _BONES.replace("|xp = 4.5", "|xp = 3")

    (bone,) = parse_bones({"Alan's bones": low, "Bones": _BONES})

    assert bone.experience == 4.5


def test_bones_come_back_best_first() -> None:
    """The caller reading the first entry it can reach is reading the best
    one, which is what makes `prayer_methods` a single pass."""
    bones = parse_bones({"Bones": _BONES, "Superior dragon bones": _SUPERIOR})

    assert [bone.name for bone in bones] == ["Superior dragon bones", "Bones"]


def test_an_altar_states_both_of_its_multipliers() -> None:
    (altar,) = parse_altars({"Gilded altar": _GILDED})

    assert (altar.name, altar.base, altar.lit) == ("gilded altar", 2.5, 3.5)


def test_one_lit_burner_is_neither_multiplier() -> None:
    """Three figures are stated and only two are wanted. Taking the maximum
    would be right by luck here and wrong on the teak page."""
    (altar,) = parse_altars({"Gilded altar": _GILDED})

    assert 3.0 not in (altar.base, altar.lit)


def test_an_unstated_base_is_normal_experience() -> None:
    """The oak altar says "normal" rather than "100%". A parse failure would
    drop the altar entirely and quietly cost a map its only house altar."""
    (altar,) = parse_altars({"Oak altar": _OAK})

    assert (altar.base, altar.lit) == (1.0, 2.0)


def test_a_percentage_that_is_not_a_multiplier_is_ignored() -> None:
    """The teak page compares itself to a mahogany altar and mentions "the
    extra 10%" in doing so. Read as a base that would make teak the worst
    altar in the game by a factor of ten."""
    (altar,) = parse_altars({"Teak altar": _TEAK})

    assert (altar.base, altar.lit) == (1.1, 2.1)


def test_each_burner_is_worth_fifty_percentage_points() -> None:
    """A regularity across all seven altars, asserted rather than computed
    from: `lit` is parsed off the page, so a page that stops saying so is a
    test failure and not a silently invented number."""
    altars = parse_altars({"Gilded altar": _GILDED, "Oak altar": _OAK, "Teak altar": _TEAK})

    assert all(round(altar.lit - altar.base, 6) == 1.0 for altar in altars)


def _derived(**overrides: Any) -> Derived:
    """A `Derived` carrying only what the Prayer model reads: which chunks are
    unlocked, which objects they hold, and which challenges are valid."""
    defaults: dict[str, Any] = {
        "reachable_sections": {},
        "expanded_chunks": {},
        "source_index": SourceIndex(
            items={}, objects={}, monsters={}, npcs={}, shops={}, drop_rates={}
        ),
        "challenges": ChallengeResult(valid={}, unsupported=frozenset()),
        "bis": BisResult(picks={}),
        "task_classification": TaskClassification(),
        "other_tasks": OtherTasks(),
    }
    defaults.update(overrides)
    return Derived(**defaults)


def _info(**construction: Any) -> ChunkInfo:
    return ChunkInfo({"challenges": {"Construction": construction}})


def _chaos() -> Derived:
    return _derived(
        expanded_chunks={CHAOS_ALTAR_CHUNK: True},
        source_index=SourceIndex(
            items={},
            objects={CHAOS_ALTAR_OBJECT: {CHAOS_ALTAR_CHUNK: True}},
            monsters={},
            npcs={},
            shops={},
            drop_rates={},
        ),
    )


def test_burying_needs_nothing_and_is_always_offered() -> None:
    """A bone can always be buried, so Prayer can never be unpriceable for
    want of an altar - only for want of a bone."""
    found = offerings(_info(), _derived(), (), {})

    assert [(o.name, o.multiplier, o.seconds) for o in found] == [("buried", 1.0, 1.2)]


def test_the_chaos_altar_is_seven_times_over_two_ticks() -> None:
    """3.5x an offering with a 50% chance not to consume the bone, so a bone
    collected is offered twice: 7x the experience for two ticks, not one."""
    found = offerings(_info(), _chaos(), (), {})
    chaos = next(o for o in found if o.name == "Chaos Altar")

    assert (chaos.multiplier, round(chaos.seconds, 6)) == (7.0, 1.2)


def test_a_chaos_altar_in_the_wrong_chunk_trains_nothing() -> None:
    """The export puts `Chaos altar (Prayer)` in five chunks and only the
    Wilderness one takes bones - the Varrock, Yanille and Underground Pass
    ones are prayer-point recharges. Keying on the object name alone handed
    a sevenfold rate to any map holding the Varrock altar."""
    varrock = _derived(
        expanded_chunks={"12853": True},
        source_index=SourceIndex(
            items={},
            objects={CHAOS_ALTAR_OBJECT: {"12853": True}},
            monsters={},
            npcs={},
            shops={},
            drop_rates={},
        ),
    )

    assert [o.name for o in offerings(_info(), varrock, (), {})] == ["buried"]


def test_a_house_altar_needs_the_construction_level_to_build_it() -> None:
    """Reaching the challenge says the map contains a house; the level says
    you can put an altar in it. Without the second gate a level-3 account
    trains at a gilded altar."""
    info = _info(**{"Build a ~|gilded altar|~": {"Level": 75, "Primary": True}})
    derived = _derived(
        challenges=ChallengeResult(
            valid={"Construction": {"Build a ~|gilded altar|~": 75}}, unsupported=frozenset()
        )
    )
    altars = (Altar(name="gilded altar", base=2.5, lit=3.5),)

    short = offerings(info, derived, altars, {"Construction": 74})
    enough = offerings(info, derived, altars, {"Construction": 75})

    assert [o.name for o in short] == ["buried"]
    assert "gilded altar" in [o.name for o in enough]


def test_burners_are_their_own_challenges() -> None:
    """The incense burners are Construction 61-69 in their own right, so an
    altar reachable without them takes `base`. On a gilded altar that is the
    difference between 2.5x and 3.5x."""
    info = _info(
        **{
            "Build a ~|gilded altar|~": {"Level": 75, "Primary": True},
            "Build an ~|oak incense burners|~": {"Level": 61, "Primary": True},
        }
    )
    altars = (Altar(name="gilded altar", base=2.5, lit=3.5),)
    valid: dict[str, Any] = {"Build a ~|gilded altar|~": 75}

    unlit = offerings(
        info,
        _derived(challenges=ChallengeResult(valid={"Construction": valid}, unsupported=frozenset())),
        altars,
        {"Construction": 99},
    )
    lit = offerings(
        info,
        _derived(
            challenges=ChallengeResult(
                valid={"Construction": {**valid, "Build an ~|oak incense burners|~": 61}},
                unsupported=frozenset(),
            )
        ),
        altars,
        {"Construction": 99},
    )

    assert next(o for o in unlit if o.name == "gilded altar").multiplier == 2.5
    assert next(o for o in lit if o.name == "gilded altar").multiplier == 3.5


def test_a_bone_with_no_route_is_dropped_rather_than_free() -> None:
    """The same reading `recipe_rates.py` takes of an unpriceable material: a
    free bone would make the rarest remains in the game the fastest Prayer
    training on the map."""
    bones = (Bone(name="Ourg bones", experience=140.0, level=1),)

    found = prayer_methods(_info(), _derived(), bones, (), {}, lambda item, quantity: None)

    assert found == ()


def test_a_bone_is_priced_over_collection_plus_offering() -> None:
    """The whole model. 15 xp buried is 15 xp; the two ticks and the ten
    seconds of collecting are what decide the rate."""
    bones = (Bone(name="Big bones", experience=15.0, level=1),)

    (method,) = prayer_methods(
        _info(), _derived(), bones, (), {}, lambda item, quantity: 10.0
    )

    assert (method.offering, method.experience) == ("buried", 15.0)
    assert method.xp_per_hour == 15.0 * 3600.0 / 11.2


def test_the_offering_multiplies_the_bone() -> None:
    """A chaos altar is 7x, so the same bone over the same collection is seven
    times the experience for one extra tick."""
    bones = (Bone(name="Big bones", experience=15.0, level=1),)

    (method,) = prayer_methods(
        _info(), _chaos(), bones, (), {}, lambda item, quantity: 10.0
    )

    assert (method.offering, method.experience) == ("Chaos Altar", 105.0)


def test_a_bones_level_reaches_the_band_walk() -> None:
    """Superior dragon bones open at 70. Priced without that the whole climb
    from level 1 is walked at a rate nothing below 70 can use."""
    bones = (Bone(name="Superior dragon bones", experience=150.0, level=70),)

    (method,) = prayer_methods(
        _info(), _derived(), bones, (), {}, lambda item, quantity: 5.0
    )

    assert method.level == 70


def test_methods_come_back_best_first() -> None:
    """`training_options` sorts too, but a caller reading `[0]` for "what
    would this map actually do" is reading it here."""
    bones = (
        Bone(name="Big bones", experience=15.0, level=1),
        Bone(name="Bones", experience=4.5, level=1),
    )

    found = prayer_methods(
        _info(), _derived(), bones, (), {}, lambda item, quantity: 1.0
    )

    assert [method.bone for method in found] == ["Big bones", "Bones"]
