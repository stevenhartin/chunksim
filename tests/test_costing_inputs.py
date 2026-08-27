"""That the two apps price one map the same way, asserted rather than hoped.

The GUI's estimate path was a copy of the CLI's that had lost `pinned_slayer`,
and the copy announced itself: `_heuristics_for`'s docstring said it "mirrors
`cli._load_heuristics`". A mirror is only correct until someone edits one side.

So this file exists to make the agreement checkable in 0.02s. `handle_request`
is pure - strings in, a `Response` out - so asking the GUI what it would answer
needs no socket, no thread and no server; the CLI's answer comes out of the same
`--export-json -` a user would pipe into `jq`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from chunksim.costing import inputs
from chunksim.costing import dps_bridge
from chunksim.costing import recipe_rates
from chunksim.store import cache
from chunksim.cli import main
from chunksim.gui.http import Context
from chunksim.gui.server import handle_request

LUMBRIDGE = "12850"

_PAYLOAD: dict[str, Any] = {
    "chunks": {"unlocked": {LUMBRIDGE: LUMBRIDGE}},
    "rules": {},
    "chunkinfo": {},
}

_CHUNKINFO: dict[str, Any] = {
    "chunks": {LUMBRIDGE: {"Monster": {"Cow": 4}}},
    "sections": {},
    "drops": {"Cow": {"Cowhide": {"1": "1/1"}}},
    "challenges": {
        "Extra": {"Obtain a ~|cowhide|~": {"Items": ["Cowhide"], "Chunk": LUMBRIDGE}}
    },
    "codeItems": {"bossMonsters": {}},
    "equipment": {},
}


@pytest.fixture
def both_apps(project: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """One cache root that `chunksim` and `chunksim-gui` both answer against.

    Takes `project` rather than building a throwaway checkout by hand: what
    `cache.checkout_root` accepts is knowledge one fixture should hold, and a
    near-miss here would not fail, it would quietly resolve to the developer's
    own data directory.
    """
    tmp_path = project
    monkeypatch.delenv("CHUNKSIM_CHUNKINFO", raising=False)
    monkeypatch.setattr(
        "chunksim.cli.io_commands.fetch_map", lambda map_id, timeout=30.0: _PAYLOAD
    )
    main(["fetch", "--map", "fray"])
    monkeypatch.setattr(
        "chunksim.cli.common.read_chunkinfo", lambda override=None, root=None: _CHUNKINFO
    )
    # The same five patches `test_gui_server._derived_ctx` makes: patch the
    # reader rather than write a 10MB export, and point everything that could
    # *write* at `tmp_path`, since these land on the shared `cache` module.
    monkeypatch.setattr(
        "chunksim.gui.derivation.cache.read_chunkinfo",
        lambda override=None, root=None: _CHUNKINFO,
    )
    monkeypatch.setattr(
        "chunksim.gui.derivation.cache.read_blob",
        lambda name, root=None, hint=None: {"data": {}},
    )
    monkeypatch.setattr(
        "chunksim.gui.derivation.cache.file_digest", lambda path: "digest"
    )
    monkeypatch.setattr(
        "chunksim.gui.derivation.cache.chunkinfo_source", lambda o, r: tmp_path / "x"
    )
    monkeypatch.setattr(
        "chunksim.gui.derivation.cache.blob_path", lambda n, r: tmp_path / f"{n}.json"
    )
    return tmp_path


def test_both_apps_price_one_map_identically(
    both_apps: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """**The regression guard for a divergence that was invisible.**

    The CLI applied the `slayer` pins from `heuristics/overrides.json` and the
    GUI did not, so the same map could price differently by app - and worse,
    `enrichment_key` hashes a digest of that *file* rather than of whether its
    pins were applied, so both wrote different values under one key in a shared
    `cache/derived/`. Last writer won, and the loser's number was plausible.
    """
    monkeypatch.setenv("CHUNKSIM_NO_WATERMARK", "1")
    assert main(["estimate", "--export-json", "-"]) == 0
    from_cli = json.loads(capsys.readouterr().out)

    response = handle_request(
        "GET", "/api/estimate", {"map": ["fray"]}, Context(root=both_apps)
    )
    from_gui = json.loads(response.body.decode("utf-8"))

    assert from_cli == from_gui


def test_estimate_answer_prices_a_skill_at_the_linked_account_not_the_floor(
    both_apps: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**The eighth call site `a3cd719` missed.** That commit turned seven
    `{**infer_levels(state), **blobs.levels}` writes into one
    `effective_levels`, because a dict merge *replaces* a floor where a
    linked account has to `max` it - the reference account it measured
    against read Attack 99 against a floor of 75. `estimate_answer` still
    handed `estimate()` `layers.levels`, which is `blobs.levels` alone: no
    `infer_levels` floor and no linked-account layer either, so a skill with
    no hand override at all read `current_level=1` regardless of what the
    account behind the map had actually done.
    """
    from chunksim.costing.estimate import estimate as real
    from chunksim.model.experience import xp_for_level
    from chunksim.store import cache

    cache.write_player(
        "fray", linked_experience={"Attack": xp_for_level(99)}, root=both_apps
    )

    calls: list[dict[str, Any]] = []

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr("chunksim.costing.inputs.estimate", spy)
    monkeypatch.setenv("CHUNKSIM_NO_WATERMARK", "1")

    assert main(["estimate", "--export-json", "-"]) == 0

    assert len(calls) == 1
    assert calls[0]["level_overrides"]["Attack"] == 99


def test_both_apps_hand_the_pricer_the_same_pins(
    both_apps: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """**The assertion that would actually have caught the original bug.**

    Comparing the two apps' *totals* does not: the divergence only moves a
    number when the map has a slayer task the pins touch, so a small fixture
    agrees either way and the test passes for the wrong reason. What drifted
    was the arguments, so those are what this compares - and it pins that
    `pinned_slayer` is non-empty, or the comparison would be two empty dicts
    agreeing about nothing.

    `cached_enrich` is stubbed out to call straight through: otherwise the
    second app of the two reads the first one's cached answer and the pricer
    is only ever called once.
    """
    if not dps_bridge.DPS_AVAILABLE:
        pytest.skip("the dps extra is not installed")

    # The corrections ship with the code, so a throwaway checkout carries its
    # own copy where `cache.overrides_path` looks for one.
    (both_apps / "src" / "chunksim" / "heuristics").mkdir(parents=True, exist_ok=True)
    (both_apps / "src" / "chunksim" / "heuristics" / "overrides.json").write_text(
        json.dumps({"slayer": {"Duradel": {"Abyssal demon": {"kills_per_hour": 90}}},
                    "monsters": {"Cow": {"kills_per_hour": 300}}})
    )

    calls: list[dict[str, Any]] = []
    real = dps_bridge.enrich

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr("chunksim.costing.dps_bridge.enrich", spy)
    monkeypatch.setattr(
        "chunksim.costing.inputs.cached_enrich",
        lambda compute, *a, **k: compute(),
    )
    monkeypatch.setenv("CHUNKSIM_NO_WATERMARK", "1")

    main(["estimate", "--export-json", "-"])
    capsys.readouterr()
    handle_request("GET", "/api/estimate", {"map": ["fray"]}, Context(root=both_apps))

    assert len(calls) == 2, "one of the two apps never reached the pricer"
    assert calls[0]["pinned_slayer"], "the fixture's slayer pin never arrived"
    assert calls[0]["pinned_slayer"] == calls[1]["pinned_slayer"]
    assert calls[0]["pinned_monsters"] == calls[1]["pinned_monsters"]


class TestRaidRunSeconds:
    """`_raid_run_seconds` is what wires `costing/raids.py`'s own per-account
    models into `Heuristics.run_seconds` - see the function's own docstring
    on why a computed answer is a ceiling rather than a promise, and
    `costing/theatre.py`'s on why the guide it floors against describes an
    established raider rather than a chunk map."""

    def test_prices_all_three_raids(self) -> None:
        if not dps_bridge.DPS_AVAILABLE:
            pytest.skip("the dps extra is not installed")
        from chunksim.costing import raids
        from chunksim.model.chunkinfo import ChunkInfo

        chunk_info = ChunkInfo({"equipment": {"Abyssal whip": {
            "attack_slash": 82, "melee_strength": 82, "attack_speed": 4, "slot": "weapon",
        }}})
        levels = {"Attack": 60, "Strength": 60, "Hitpoints": 60}
        index = dps_bridge.load_monster_index()

        found = inputs._raid_run_seconds(
            chunk_info, {"Melee-weapon": "Abyssal whip"}, levels, index=index,
        )

        # **A subset, not all four.** `encounter.build` refuses a raid
        # outright if bare melee at level 60 cannot kill even one of its
        # rooms - Chambers' Vanguards want a style switch this fixture's
        # single weapon cannot make - so what a weak loadout actually prices
        # is not every key, only the ones its gear can clear.
        assert found
        assert set(found) <= {
            raids.CHAMBERS, f"{raids.CHAMBERS} (challenge)", raids.THEATRE, raids.TOMBS,
        }
        for key, seconds in found.items():
            assert seconds >= raids.PUBLISHED_RAID_SECONDS[key]

    def test_chambers_normal_and_challenge_are_kept_apart(self) -> None:
        """**The bug this pins.** An earlier version asked `raids.compare`
        for "whichever Chambers mode is fastest overall" and used that one
        number for both the Normal-mode uniques and the Challenge-mode cape
        - on a real map that picked Challenge Mode and priced `Sinhaza
        shroud tier 5` off the Theatre's own figure reused wholesale, and
        separately would have priced Chambers' own uniques off a Challenge
        Mode pace paired with Normal Mode drop chances. The two keys must be
        free to disagree, and on real gear they do: Challenge Mode fights
        every room at 1.5x health, so it is never faster."""
        if not dps_bridge.DPS_AVAILABLE:
            pytest.skip("the dps extra is not installed")
        from chunksim.costing import raids
        from chunksim.model.chunkinfo import ChunkInfo

        chunk_info = ChunkInfo({"equipment": {
            "Abyssal whip": {"attack_slash": 82, "melee_strength": 82, "attack_speed": 4, "slot": "weapon"},
            "Rune crossbow": {"attack_ranged": 90, "ranged_strength": 90, "attack_speed": 5, "slot": "2h"},
            "Rune arrow": {"ranged_strength": 0, "slot": "ammo"},
        }})
        picks = {"Melee-weapon": "Abyssal whip", "Ranged-weapon": "Rune crossbow", "Ranged-ammo": "Rune arrow"}
        levels = {"Attack": 80, "Strength": 80, "Ranged": 80, "Magic": 80, "Hitpoints": 90}
        index = dps_bridge.load_monster_index()

        found = inputs._raid_run_seconds(chunk_info, picks, levels, index=index)

        challenge_key = f"{raids.CHAMBERS} (challenge)"
        if raids.CHAMBERS in found and challenge_key in found:
            assert found[challenge_key] > found[raids.CHAMBERS]

    def test_never_faster_than_the_published_guide(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unrealistically fast computed answer - the shape a generous
        `UPTIME` guess could produce - never beats the guide's own published
        pace once this has floored it, at every one of the four keys."""
        if not dps_bridge.DPS_AVAILABLE:
            pytest.skip("the dps extra is not installed")
        from chunksim.costing import raids
        from chunksim.model.chunkinfo import ChunkInfo

        monkeypatch.setattr(
            "chunksim.costing.inputs.dps_bridge.theatre_kill_seconds",
            lambda *a, **k: (lambda name: 1.0),
        )
        monkeypatch.setattr(
            "chunksim.costing.inputs.dps_bridge.chambers_kill_seconds_for",
            lambda *a, **k: (lambda mode: (lambda name: 1.0)),
        )
        monkeypatch.setattr(
            "chunksim.costing.inputs.dps_bridge.tombs_stats_for",
            lambda *a, **k: (lambda level: (lambda name: (1.0, 1.0))),
        )

        found = inputs._raid_run_seconds(
            ChunkInfo({}), {}, {}, index=dps_bridge.load_monster_index(),
        )

        assert set(found) == {
            raids.THEATRE, raids.CHAMBERS, f"{raids.CHAMBERS} (challenge)", raids.TOMBS,
        }
        for key, seconds in found.items():
            assert seconds == raids.PUBLISHED_RAID_SECONDS[key]


class TestTzhaarRunSeconds:
    """`_tzhaar_run_seconds` is `_raid_run_seconds`'s own twin for the wave
    minigames - see `costing/tzhaar.py`'s corrected module docstring on the
    claim about this wiring that stood unchecked until now."""

    def test_prices_what_bare_melee_can_clear(self) -> None:
        """**Fight Caves only, not the Inferno, with this fixture's gear.**
        `Jal-MejJak` (Zuk's own healer, level-100 defence with no defensive
        bonuses) refuses a bare-melee kill entirely - see
        `TestTzhaarKillSeconds`'s own note on it - and `encounter.build`'s
        "all or nothing" rule drops the whole Inferno run rather than a
        raid-shaped subset of it. This is what a chunk map missing a ranged
        or magic weapon should see: one variant priced, the other silent
        rather than guessed."""
        if not dps_bridge.DPS_AVAILABLE:
            pytest.skip("the dps extra is not installed")
        from chunksim.costing import tzhaar
        from chunksim.model.chunkinfo import ChunkInfo

        chunk_info = ChunkInfo({"equipment": {"Abyssal whip": {
            "attack_slash": 82, "melee_strength": 82, "attack_speed": 4, "slot": "weapon",
        }}})
        levels = {"Attack": 75, "Strength": 70, "Hitpoints": 99}
        index = dps_bridge.load_monster_index()

        found = inputs._tzhaar_run_seconds(
            chunk_info, {"Melee-weapon": "Abyssal whip"}, levels, index=index,
        )

        assert set(found) == {tzhaar.FIGHT_CAVES}
        assert found[tzhaar.FIGHT_CAVES] >= tzhaar.RUN_SECONDS[tzhaar.FIGHT_CAVES]

    def test_never_faster_than_the_maintainers_own_figure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The same floor `TestRaidRunSeconds` pins, one module over: an
        unrealistically fast sequencer answer never beats `RUN_SECONDS`."""
        if not dps_bridge.DPS_AVAILABLE:
            pytest.skip("the dps extra is not installed")
        from chunksim.costing import encounter, tzhaar
        from chunksim.model.chunkinfo import ChunkInfo

        fast = encounter.Encounter(
            "Fight Caves", (encounter.Stage("fast", 1.0, 0.0),)
        )
        monkeypatch.setattr(
            "chunksim.costing.inputs.tzhaar.run",
            lambda variant, kill_seconds: fast if variant == tzhaar.FIGHT_CAVES else None,
        )

        found = inputs._tzhaar_run_seconds(
            ChunkInfo({}), {}, {}, index=dps_bridge.load_monster_index(),
        )

        assert found == {tzhaar.FIGHT_CAVES: tzhaar.RUN_SECONDS[tzhaar.FIGHT_CAVES]}


def test_neither_app_reaches_past_the_shared_module() -> None:
    """A structural guard, in the spirit of the one asserting no tile route
    exists: the way this drifted was two call sites, so there is now one.

    A second `dps_bridge.enrich(` anywhere in either app is the bug coming
    back, and it would be invisible again until someone wrote a slayer
    override.
    """
    from chunksim.gui import server

    for module in (main.__module__, server.__name__):
        source = Path(__import__(module, fromlist=["__file__"]).__file__ or "").read_text()
        assert "dps_bridge.enrich(" not in source, f"{module} prices its own"


def test_a_true_level_override_is_not_read_as_level_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`True` is an `int` in Python, so a stray `"Attack": true` would become
    level 1 - a silently *worse* answer than no override at all."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "heuristics").mkdir()
    (tmp_path / "heuristics" / "overrides.json").write_text(
        json.dumps({"levels": {"Attack": 70, "Defence": True, "Magic": "99"}})
    )

    assert inputs.level_overrides(tmp_path) == {"Attack": 70}


def test_the_pins_are_read_together(tmp_path: Path) -> None:
    """Both pin sets come from one file and go to one call. They are returned
    together because splitting them is exactly how the GUI came to pass the
    first and forget the second."""
    (tmp_path / "heuristics").mkdir()
    (tmp_path / "heuristics" / "overrides.json").write_text(
        json.dumps(
            {
                "monsters": {"Cow": {"kills_per_hour": 300}},
                "slayer": {"Duradel": {"Abyssal demon": {"kills_per_hour": 90}}},
                "levels": {"Attack": 70},
            }
        )
    )

    monsters, slayer = inputs.pinned_keys(tmp_path)

    assert monsters == frozenset({"Cow"})
    assert slayer == {"Duradel": frozenset({"Abyssal demon"})}


def test_a_hand_stated_material_is_charged_per_xp() -> None:
    """**The one way to charge a method the recipes cannot describe.**

    `material_seconds_per_xp` otherwise comes only from `computed_rates`,
    because that is the only place per-action experience and per-action
    quantity exist together - the export carries neither. So a method with a
    scraped or hand-entered rate and no recipe row was ranked as though its
    inputs were free, which is what let the Giants' Foundry spend 276,000/hr
    with its 28 bars costing nothing.
    """
    asked: list[tuple[str, float]] = []

    def collect(item: str, quantity: float) -> float | None:
        asked.append((item, quantity))
        return {"Runite bar": 14.0, "Coal": 2.0}[item] * quantity

    costs = inputs.hand_material_costs(
        {
            "materials": {
                "Forge something": {
                    "experience": 23_000,
                    "items": {"Runite bar": 28, "Coal": 1},
                }
            }
        },
        collect,
    )

    assert asked == [("Runite bar", 28.0), ("Coal", 1.0)]
    assert costs == {"Forge something": (28 * 14.0 + 2.0) / 23_000}


def test_an_unpriceable_hand_material_leaves_the_method_uncharged() -> None:
    """`None` from the walk means *no route*, and the choice here is the same
    one `recipe_rates` makes with an unpriceable material and wrong in the same
    direction: the method keeps its rate with nothing charged.

    Dropping it instead would silently remove a method a person deliberately
    rated, which is the worse of the two failures. It cannot bite on either
    cached map - all six foundry bars price - so this pins the behaviour rather
    than a number.
    """
    costs = inputs.hand_material_costs(
        {"materials": {"Forge something": {"experience": 100, "items": {"Ghost bar": 1}}}},
        lambda item, quantity: None,
    )

    assert costs == {}


@pytest.mark.parametrize(
    "entry",
    [
        {"items": {"Runite bar": 28}},
        {"experience": 0, "items": {"Runite bar": 28}},
        {"experience": 100},
        {"experience": 100, "items": {"Runite bar": 0}},
        "not an object",
    ],
)
def test_an_incomplete_hand_material_entry_is_ignored(entry: Any) -> None:
    """Both numbers are needed and neither can be guessed: seconds per XP is
    seconds per action over XP per action. A half-written entry contributes
    nothing rather than a fraction of a cost.
    """
    costs = inputs.hand_material_costs(
        {"materials": {"Forge something": entry}}, lambda item, quantity: 1.0
    )

    assert costs == {}


class TestLoadAliasesMergesTheHandTable:
    """`recipe_rates.HAND_ALIASES` covers vocabulary drift the wiki's own
    redirect machinery cannot see - no page exists under upstream's name for
    a redirect to point from - so it has to be merged in regardless of
    whether `chunksim recipes` has ever run."""

    def test_present_even_with_no_fetch_at_all(self, tmp_path: Path) -> None:
        assert inputs.load_aliases(root=tmp_path) == recipe_rates.HAND_ALIASES

    def test_a_fetched_alias_wins_a_collision(self, tmp_path: Path) -> None:
        """None is expected in practice - the fetch is what the wiki says
        today and the hand table exists only where the wiki has nothing to
        say - but a real collision should still resolve in the fetch's
        favour."""
        alias = next(iter(recipe_rates.HAND_ALIASES))
        cache.write_blob(
            cache.ALIASES_BLOB_NAME, {alias: "Something else entirely"}, "test",
            root=tmp_path,
        )

        merged = inputs.load_aliases(root=tmp_path)

        assert merged[alias] == "Something else entirely"

    def test_a_fetched_alias_beside_the_hand_table_keeps_both(
        self, tmp_path: Path
    ) -> None:
        cache.write_blob(
            cache.ALIASES_BLOB_NAME, {"Bronze javelin heads": "Bronze javelin tips"},
            "test", root=tmp_path,
        )

        merged = inputs.load_aliases(root=tmp_path)

        assert merged["Bronze javelin heads"] == "Bronze javelin tips"
        assert merged["Wooden dining table"] == recipe_rates.HAND_ALIASES[
            "Wooden dining table"
        ]
