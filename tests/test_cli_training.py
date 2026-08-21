"""`chunksim training`: what can train each skill, and what priced it."""

from __future__ import annotations

import argparse

import pytest

from chunksim.cli import training
from chunksim.cli.common import MapAmbiguityError
from chunksim.costing import coverage
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.store import cache


def test_the_statuses_are_ordered_least_actionable_first() -> None:
    """The table prints them reversed, so this order is what makes it read
    best-to-worst and end on the three that are not the model's fault.

    `one-off` sits with the two absent statuses rather than near `unpriced`
    because it is a statement about the challenge, not about how well this
    project priced it - see `costing/oneoff.py`. `refused` sits between them
    for the same reason from the other side: it is an absence somebody chose.
    """
    assert coverage.STATUSES[0] == coverage.UNCOMPLETABLE
    assert coverage.STATUSES[1] == coverage.UNREACHABLE
    assert coverage.STATUSES[2] == coverage.ONE_OFF
    assert coverage.STATUSES[3] == coverage.REFUSED
    assert coverage.STATUSES[4] == "unpriced"
    assert coverage.STATUSES[-1] == "modelled"
    assert set(coverage.STATUSES) == set(training.STATUS_LABELS)


def test_a_method_no_map_can_do_is_not_a_modelling_gap() -> None:
    """**The distinction the report was getting wrong.** Every computed layer
    walks the derivation's `valid` set, so a challenge outside it is never
    offered to any of them and keeps whatever the raw scrape left behind.
    Reported as `published` that says "somebody's guide decides this method",
    where the truth is "upstream's own gates put it out of reach and nothing
    here was ever asked" - and measured against the ceiling, *all 47* of the
    export's remaining published rows were this.

    Reachability is checked before everything, including a pin: a leftover is
    a leftover whoever wrote it."""
    assert coverage.status_of("exact", reachable=False) == "unreachable"
    assert coverage.status_of("exact", pinned=True, reachable=False) == "unreachable"
    assert coverage.status_of("modelled", reachable=False) == "unreachable"
    assert coverage.status_of("exact", reachable=True) == "published"


def test_an_unreachable_rate_is_not_printed_as_a_rate() -> None:
    """Its number is a scrape nothing was asked to spend, and `unpriced`'s is
    the 1,000/hr floor - printing either under a heading that says "rate" is
    how a placeholder gets read as a measurement."""
    assert training.QUIET_STATUSES == frozenset(
        {
            "unpriced",
            coverage.UNREACHABLE,
            coverage.UNCOMPLETABLE,
            coverage.ONE_OFF,
            coverage.REFUSED,
        }
    )


def test_a_guess_is_not_counted_as_modelled() -> None:
    """It is the one that should shrink and the one a reader most needs
    warning about: it looks exactly like a rate and is an admission."""
    assert coverage.status_of("guess") == "guess"
    assert coverage.status_of("modelled") == "modelled"
    assert coverage.status_of("computed") == "modelled"
    assert coverage.status_of("confirmed") == "modelled"


def test_a_pin_outranks_whatever_it_looks_like() -> None:
    """An override lands in `training` looking exactly like the guide row it
    replaced, so `Heuristics.pinned` is the only way to tell."""
    assert coverage.status_of("exact", pinned=True) == "pinned"
    assert coverage.status_of("exact") == "published"
    assert coverage.status_of("contained") == "published"


def test_the_floor_is_unpriced_rather_than_a_rate() -> None:
    assert coverage.status_of("default") == "unpriced"
    assert coverage.status_of("") == "unpriced"


def test_categories_that_are_not_skills_are_left_out() -> None:
    """The export files `Quest`, `Diary`, `Extra` and `Nonskill` alongside the
    real skills, and `Combat` is a category rather than a skill - a training
    report listing those would be listing five things nobody levels."""
    assert "Agility" in coverage.SKILLS
    assert not {"Quest", "Diary", "Extra", "Nonskill", "Combat"} & set(coverage.SKILLS)
    assert len(coverage.SKILLS) == 24


def test_omitting_the_map_is_a_different_question_not_a_default() -> None:
    """`cli/app.main` infers the sole cached map for every other family; this
    one opts out, because without `--map` it reports on the export."""
    import argparse

    parser = argparse.ArgumentParser()
    training.add_arguments(parser.add_subparsers(dest="command", required=True))

    assert parser.parse_args(["training"]).infer_map is False
    assert parser.parse_args(["training"]).map_id is None
    assert parser.parse_args(["training", "--map", "fray"]).map_id == "fray"
    assert parser.parse_args(["training", "Agility"]).skill == "Agility"


@pytest.mark.real_cache
def test_the_map_report_names_a_method_for_every_trainable_skill(
    real_state: tuple[object, dict[str, bool]], real_derived: object
) -> None:
    """**The point of the overview**: a skill with no reachable method reads as
    one, and every other names the method the estimate would actually spend."""
    from chunksim.costing import inputs
    from chunksim.store.derived_cache import Digests

    state, unlocked = real_state
    answer = inputs.training_answer(
        state,  # type: ignore[arg-type]
        unlocked,
        real_derived,  # type: ignore[arg-type]
        Digests(chunkinfo="test"),
        map_id="fray",
    )

    assert set(answer.best) == set(coverage.SKILLS)
    named = {skill for skill, option in answer.best.items() if option is not None}
    assert len(named) > 12, "the reference map trains most skills"
    for skill in named:
        option = answer.best[skill]
        assert option is not None
        # **Gated on the level the map is at.** "Best" for somebody at 40 is
        # not the level-90 method.
        assert option.level is None or option.level <= answer.levels[skill]
        assert option.effective_xp_per_hour > 0


def test_the_export_report_caches_its_derivation_and_keys_it_honestly() -> None:
    """**The ceiling state is the biggest derivation there is, and the first
    version of this command was the one place that never cached it** - every
    invocation paid ~4.3s of `pipeline.derive` again, which is what made a
    coverage report read as a slow command. It must go through
    `derive_cached` like every other subcommand, and its digests must be the
    real file hashes: the placeholder `Digests(chunkinfo="training")` it
    shipped with served a stale pricing straight across an export refetch,
    because nothing in the key moved when the export did.
    """
    import inspect

    from chunksim.cli import training as module

    source = inspect.getsource(module._report_export)
    assert "derive_cached(" in source, "the ceiling derivation must be cached"
    assert "digests(args)" in source, "and keyed by the real file digests"
    assert "pipeline.derive(" not in source
    assert 'Digests(chunkinfo="training")' not in inspect.getsource(module)


def test_the_ceiling_calls_it_uncompletable_rather_than_unreachable() -> None:
    """**The same test asked of different worlds, and only one is news.** A
    method one map cannot do is the ordinary condition of a chunk map; one the
    every-rollable-chunk ceiling cannot do says no player could ever perform
    it, which is either a fact about the game or a defect here."""
    assert coverage.status_of("exact", reachable=False) == coverage.UNREACHABLE
    assert (
        coverage.status_of("exact", reachable=False, absent=coverage.UNCOMPLETABLE)
        == coverage.UNCOMPLETABLE
    )
    assert {coverage.UNREACHABLE, coverage.UNCOMPLETABLE} <= set(coverage.STATUSES)
    assert set(coverage.BLOCKERS) <= set(training.BLOCKER_LABELS)


class TestWhatBlockedIt:
    """`blocker_for` names the requirement a world lacks, so "307
    uncompletable" is a list of causes rather than a number to worry about.

    **The order is most decisive first**, which is what stops the report
    naming symptoms: a quest-gated challenge lists the items that quest hands
    over, and a rule-gated family's items are beside the point entirely.
    """

    REACH = coverage.Reachability(
        items=frozenset({"Rune axe"}),
        objects=frozenset({"Anvil"}),
        tasks=frozenset({"Catch a ~|ruby harvest|~"}),
        npcs=frozenset({"Ruby harvest"}),
        chunks=frozenset({"1111"}),
        rules_off=frozenset({"Secondary Primary"}),
    )

    def test_a_rule_the_player_turned_off_wins_over_its_items(self) -> None:
        """`Make a ~|rune felling axe|~ (alt)` is behind `Secondary Primary`,
        not behind its anvil - reporting the anvil would send somebody to
        model a thing that is switched off."""
        assert coverage.blocker_for(
            {
                "Category": ["ForestryXp", "Secondary Primary"],
                "Items": ["Felling axe handle*", "Rune axe*"],
                "Objects": ["Anvil[+]"],
            },
            self.REACH,
        ) == ("rule", "Secondary Primary")

    def test_upstreams_own_fallback_form_is_not_a_gap(self) -> None:
        """A barehanded butterfly catch names the netted one as its
        `BackupParent`; where the parent is valid upstream drops the backup,
        so it is the same catch counted once."""
        assert coverage.blocker_for(
            {"BackupParent": "Catch a ~|ruby harvest|~", "NPCs": ["Ruby harvest"]},
            self.REACH,
        ) == ("superseded", "Catch a ~|ruby harvest|~")

    def test_a_quest_gate_wins_over_the_items_that_quest_hands_over(self) -> None:
        assert coverage.blocker_for(
            {"Tasks": {"~|Shilo Village|~ Complete the quest": "Quest"}, "Items": ["Nihil dust"]},
            self.REACH,
        ) == ("task", "~|Shilo Village|~ Complete the quest")

    def test_the_markers_are_stripped_before_the_lookup(self) -> None:
        """`Items` carries `*` for "consumed" and `[+]` for "or equivalent",
        and neither is part of the name a source index is keyed by."""
        assert coverage.blocker_for({"Items": ["Rune axe*"]}, self.REACH) == ("unstated", "")
        assert coverage.blocker_for({"Items": ["Nihil dust*"]}, self.REACH)[0] == "item"

    def test_a_walked_into_area_is_not_a_location_block(self) -> None:
        """`Reachability.chunks` is the expanded set, not the unlocked one -
        a named area is walked into rather than rolled, and calling that a
        blocker would report the derivation's own answer back as a defect."""
        assert coverage.blocker_for({"Chunks": ["1111"]}, self.REACH) == ("unstated", "")
        assert coverage.blocker_for({"Chunks": ["9999"]}, self.REACH) == ("location", "9999")


class TestWhyTheCeilingHasNoRules:
    """"No rules" has two causes and they read completely differently: a
    checkout with nothing fetched has none to borrow, one with several has
    plenty and no way to choose. Both used to report "none cached", which
    contradicted the note printed directly above it in the ambiguous case."""

    def _args(self, **overrides: object) -> argparse.Namespace:
        defaults: dict[str, object] = {"rules_from": None, "map_id": None, "chunkinfo": None}
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def _info(self) -> ChunkInfo:
        return ChunkInfo({"chunkinfo": {"sections": {"100": True}}})

    def test_an_explicit_map_needs_no_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            cache, "read_cache", lambda name: {"data": {"rules": {"Boss": True}}}
        )

        base, payload, why = training._ceiling_payload(self._info(), self._args(rules_from="fray"))

        assert (base, why) == ("fray", "")
        assert payload["rules"] == {"Boss": True}

    def test_several_cached_says_which_flag_to_pass(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def ambiguous(_: str | None) -> str:
            raise MapAmbiguityError("several")

        monkeypatch.setattr(training, "resolve_map", ambiguous)
        monkeypatch.setattr(
            cache,
            "list_maps",
            lambda: [type("E", (), {"kind": cache.FETCHED})()],
        )

        _, _, why = training._ceiling_payload(self._info(), self._args())

        assert why == "ambiguous"

    def test_an_empty_cache_is_the_opposite_advice(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`resolve_map` raises the *same* error for an empty cache, so the
        count has to be read rather than inferred from the exception."""

        def ambiguous(_: str | None) -> str:
            raise MapAmbiguityError("none")

        monkeypatch.setattr(training, "resolve_map", ambiguous)
        monkeypatch.setattr(cache, "list_maps", lambda: [])

        _, _, why = training._ceiling_payload(self._info(), self._args())

        assert why == "missing"


class TestTheCeilingDropsWhatAPlayerSealed:
    """`manualSections`/`manualAreas` override reachability in *either*
    direction, and the ceiling borrows the base map's progress - so a section
    one player shut by hand printed as `uncompletable`, the one status this
    report promises means "no player could ever do this". Dropping the `false`
    entries moves 29 rows off that column on the real export."""

    def _args(self) -> argparse.Namespace:
        return argparse.Namespace(rules_from="fray", map_id=None, chunkinfo=None)

    def _info(self) -> ChunkInfo:
        return ChunkInfo({"chunkinfo": {"sections": {"100": True}}})

    def _payload(self, monkeypatch: pytest.MonkeyPatch, chunkinfo: object) -> dict[str, object]:
        monkeypatch.setattr(cache, "read_cache", lambda name: {"data": {"chunkinfo": chunkinfo}})
        _, payload, _ = training._ceiling_payload(self._info(), self._args())
        branch = payload["chunkinfo"]
        assert isinstance(branch, dict)
        return branch

    def test_a_sealed_section_is_dropped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        branch = self._payload(
            monkeypatch, {"manualSections": {"13878": {"1": True, "2": False, "3": False}}}
        )

        assert branch["manualSections"] == {"13878": {"1": True}}

    def test_an_opened_section_is_kept(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """**Load-bearing, not symmetry.** A `true` entry opens a section
        nothing else reaches - dropping the whole branch costs the real
        reference map 22 reachable sections and takes `uncompletable` to 340,
        *worse* than leaving the seals in."""
        branch = self._payload(monkeypatch, {"manualSections": {"6705": {"1": True}}})

        assert branch["manualSections"] == {"6705": {"1": True}}

    def test_a_sealed_area_is_dropped_too(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`expand_chunk_areas` pops on `False`, so an area is the same claim
        one level up."""
        branch = self._payload(
            monkeypatch, {"manualAreas": {"Lithkren Vault": False, "Yama's Domain": True}}
        )

        assert branch["manualAreas"] == {"Yama's Domain": True}

    def test_the_rest_of_the_progress_is_untouched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only reachability overrides are two-directional. `manualMonsters`
        and the rest only ever *add*, so borrowing them is what makes the
        ceiling a ceiling."""
        branch = self._payload(
            monkeypatch,
            {"manualMonsters": {"Monsters": {"Artio": True}}, "maxSkill": {"Mining": 70}},
        )

        assert branch == {
            "manualMonsters": {"Monsters": {"Artio": True}},
            "maxSkill": {"Mining": 70},
        }

    def test_a_map_with_no_progress_branch_is_fine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert self._payload(monkeypatch, None) == {}


class TestShowCategory:
    """`--show-category unpriced` answers "what is still unpriced" - the
    question the status table's counts provoke and could not previously be
    followed up on without `--export-json` and a JSON tool."""

    def _rows(self) -> dict[str, tuple[coverage.MethodStatus, ...]]:
        def row(task: str, status: str, skill: str) -> coverage.MethodStatus:
            return coverage.MethodStatus(
                task=task, skill=skill, level=1, xp_per_hour=1000.0,
                effective_xp_per_hour=1000.0, match="default", source="",
                status=status, knob="", blocker="", blocked_by="",
            )

        return {
            "Construction": (
                row("Build a ~|thing|~", "unpriced", "Construction"),
                row("Build a ~|fence|~", "modelled", "Construction"),
            ),
            "Cooking": (row("Cook a ~|fish|~", "unpriced", "Cooking"),),
            "Mining": (row("Mine ~|ore|~", "modelled", "Mining"),),
        }

    def test_one_skill_is_filtered_to_the_status(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        training._print_skill_statuses(
            self._rows()["Construction"], "Construction", None, "unpriced"
        )

        out = capsys.readouterr().out
        assert "1 unpriced primary methods" in out
        assert "Build a thing" in out
        assert "fence" not in out

    def test_without_a_skill_every_skill_is_grouped(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        training._print_category(self._rows(), "unpriced", None)

        out = capsys.readouterr().out
        assert "unpriced — 2 across 2 skill(s)" in out
        assert "Construction (1)" in out and "Cooking (1)" in out
        # A skill with none of the status is left out rather than printed
        # empty - the point of asking is the list.
        assert "Mining" not in out

    def test_the_limit_says_what_it_hid(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A truncated list that does not say so reads as the whole answer."""
        rows = self._rows()["Construction"]

        training._print_skill_statuses(rows, "Construction", 1)

        assert "1 more" in capsys.readouterr().out


class TestResolvingNames:
    """Both names are matched case-insensitively and a miss is an error -
    they used to be `.get` lookups, so a typo printed an empty section and
    exited 0, which is a real answer this report gives for other reasons."""

    def test_a_skill_is_case_insensitive(self) -> None:
        assert training._resolve("construction", coverage.SKILLS, "skill") == "Construction"

    def test_a_category_accepts_the_label_the_table_prints(self) -> None:
        """The table's column says `guessed` where the status is `guess`, and
        a flag that rejects the word printed above the number it filters is a
        trap."""
        assert training._resolve("guessed", training._CATEGORIES, "category") == "guess"
        assert training._resolve("guess", training._CATEGORIES, "category") == "guess"
        assert (
            training._resolve("hand-pinned", training._CATEGORIES, "category") == "pinned"
        )

    def test_nothing_given_stays_nothing(self) -> None:
        assert training._resolve(None, coverage.SKILLS, "skill") is None

    def test_a_miss_names_the_valid_values(self) -> None:
        with pytest.raises(ValueError, match="unknown skill 'construcion'"):
            training._resolve("construcion", coverage.SKILLS, "skill")


class TestAnUnpricedMethodSaysWhatItWanted:
    """`blocker`/`blocked_by` were only ever filled for a method the world
    cannot reach. A reachable one that joined a recipe and lost an input is
    the other half of "why is there no number here"."""

    def _statuses(
        self, unroutable: dict[str, str]
    ) -> tuple[coverage.MethodStatus, ...]:
        from chunksim.costing.heuristics import Heuristics

        info = ChunkInfo(
            {
                "challenges": {
                    "Construction": {
                        "Build a ~|volcanic theme|~": {"Primary": True, "Level": 85},
                        "Fill holes on ~|Fishing Trawler|~": {"Primary": True, "Level": 1},
                    }
                }
            }
        )
        return coverage.statuses_for(
            info,
            Heuristics(unroutable=unroutable),
            "Construction",
            {"Build a ~|volcanic theme|~": True, "Fill holes on ~|Fishing Trawler|~": True},
        )

    def test_the_material_is_named(self) -> None:
        rows = {row.task: row for row in self._statuses({"Build a ~|volcanic theme|~": "Granite (5kg)"})}

        row = rows["Build a ~|volcanic theme|~"]
        assert row.status == "unpriced"
        assert (row.blocker, row.blocked_by) == (coverage.INPUT, "Granite (5kg)")

    def test_a_method_no_recipe_joined_names_nothing(self) -> None:
        """Blank stays blank: nothing joined, so there is no ingredient to
        name and inventing one would be worse than silence."""
        rows = {row.task: row for row in self._statuses({})}

        assert rows["Fill holes on ~|Fishing Trawler|~"].blocked_by == ""

    def test_a_recipe_refused_for_want_of_a_duration_names_nothing(self) -> None:
        """`recipe_rates.unroutable` returns `""` there, and rendering it as
        an ingredient would claim a material that routes fine."""
        rows = {row.task: row for row in self._statuses({"Build a ~|volcanic theme|~": ""})}

        assert rows["Build a ~|volcanic theme|~"].blocked_by == ""

    def test_it_is_not_in_the_uncompletable_breakdown(self) -> None:
        """`BLOCKERS` is what the *world* lacks, printed for uncompletable
        rows only - this is a statement about a method the world plainly has."""
        assert coverage.INPUT not in coverage.BLOCKERS


class TestARefusalIsNotAGap:
    """**`unpriced` and `refused` are opposite claims.** Several models decline
    a method by name - Woodcutting's swaying tree, an impling, a page that
    disclaims itself - precisely so that no number is quoted for it, and every
    one of those decisions then read as `unpriced`, the one word that means
    "somebody should go and close this". See `coverage.REFUSED`."""

    def test_it_renames_only_an_otherwise_unpriced_row(self) -> None:
        assert coverage.status_of("default", refused=True) == coverage.REFUSED
        assert coverage.status_of("", refused=True) == coverage.REFUSED

    def test_a_model_that_later_prices_it_wins_without_an_edit(self) -> None:
        """The difference from `one-off`, and what `costing/disclaimed.py`
        promises about its own entry: a refusal says nothing about a rate
        somebody else computed, so it is checked *after* every priced tier."""
        assert coverage.status_of("modelled", refused=True) == "modelled"
        assert coverage.status_of("exact", refused=True) == "published"
        assert coverage.status_of("modelled", pinned=True, refused=True) == "pinned"

    def test_being_out_of_reach_still_comes_first(self) -> None:
        """A method this world cannot do is that before it is anything else -
        the same order every other status is decided in."""
        assert coverage.status_of("default", refused=True, reachable=False) == (
            coverage.UNREACHABLE
        )

    def test_a_decoration_outranks_it(self) -> None:
        """They cannot both be true of one row, and `one-off` is the stronger
        claim: it exempts a method that *has* a rate."""
        assert coverage.status_of(
            "default", one_off=True, refused=True
        ) == coverage.ONE_OFF


def test_a_family_blocker_names_something_that_exists() -> None:
    """**Without expanding the family the report named a phantom.** `Offer a
    ~|blessed bone shards|~ at the libation bowl` asks for `Blessed wine[+]`,
    which the export defines as two jugs - and stripping the marker asked the
    world for a bare "Blessed wine", which is not an item anywhere. Measured
    over the ceiling, expanding it moved 15 rows off `item` and onto the
    object they were really missing."""
    reach = coverage.Reachability(
        items=frozenset({"Jug of blessed wine"}),
        objects=frozenset(),
        tasks=frozenset(),
        npcs=frozenset(),
        chunks=frozenset(),
        families={"Blessed wine[+]": ("Jug of blessed wine", "Jug of blessed sunfire wine")},
    )
    assert reach.has_item("Blessed wine[+]")
    assert not reach.has_item("Superior dragon bones")


def test_a_family_with_no_table_is_still_a_blocker() -> None:
    """One member is enough, but a family nothing defines is satisfiable by
    nothing - which is the derivation's reading too."""
    reach = coverage.Reachability(
        items=frozenset({"Jug of blessed wine"}),
        objects=frozenset(),
        tasks=frozenset(),
        npcs=frozenset(),
        chunks=frozenset(),
    )
    assert not reach.has_item("Blessed wine[+]")
