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
def both_apps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """One cache root that `fray` and `chunksim-gui` both answer against."""
    monkeypatch.delenv("CHUNKSIM_CHUNKINFO", raising=False)
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
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

    (both_apps / "heuristics").mkdir()
    (both_apps / "heuristics" / "overrides.json").write_text(
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
