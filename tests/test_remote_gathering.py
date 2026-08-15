"""`remote/gathering.py` and `remote/skillcalc.py`: the wikitext the model reads.

Fixtures are trimmed copies of the real pages, kept small enough to read but
keeping every shape that has already cost something: the `colspan=2` item
header, the header arriving as a data row, a footnote glued to a number, and a
`materials` block whose own `name` must not be read as the row's.
"""

from __future__ import annotations

from chunksim.remote import gathering, skillcalc

WILLOW_CHART = """
Some prose about willow trees.
{{Skilling success chart|label=Willow tree cut chance|showbefore=no
|label1=Bronze|low1=16|high1=50|req1=30|color1=saddlebrown
|label2=Rune|low2=56|high2=175|req2=41|color2=steelblue
|label3=Crystal|low3=64|high3=195|req3=71|color3=cyan
}}
"""

IRON_CHART = """
{{Skilling success chart|label=Iron rocks mining chance|showbefore=no
|label1=Iron rocks|low1=96|high1=350|req1=15|color1=brown
}}
"""

PICKAXE_PAGE = """
==Standard pickaxes==
{| class="wikitable"
!colspan=2|Item
!{{SCP|Mining}}
!{{SCP|Attack}}
!Weight
!Ticks between rolls
|-
|{{plinkt|Bronze pickaxe}}
|1
|1
|2.267&nbsp;kg
|8
|-
|{{plinkt|Dragon pickaxe}}
|61
|60
|2.4&nbsp;kg
|2.83{{efn|3 ticks by default, 1/6 chance to be 2 ticks.}}
|}

==Other pickaxes==
{| class="wikitable"
!colspan=2|Item
!{{SCP|Mining}}
!{{SCP|Attack}}
!Weight
!Ticks between rolls
|-
|{{plinkt|Gilded pickaxe}}
|41
|40
|2.267&nbsp;kg
|3
|}
"""

DESPAWN_PAGE = """
{| class="wikitable"
|-
! Tree !! Despawn time
!Respawn time
|-
| [[Oak tree]] || 27 seconds
|8.4 seconds
|-
| [[Yew tree]] || 1 minute, 54 seconds
|59.4 seconds
|}
"""

FISHING_MODULE = """
return {
\t{
    \tname = 'Raw shrimps',
        level = 1,
        xp = 10,
        members = 'No',
        type = 'Small net'
    }, {
    \tname = 'Raw sardine',
        level = 5,
        xp = 20,
        materials = {
        \t{ name = 'Fishing bait', quantity = 1 }
        },
        members = 'No',
        type = 'Bait'
    }
}
"""


class TestSuccessCharts:
    def test_reads_every_series_in_written_order(self) -> None:
        charts = gathering.parse_success_charts(WILLOW_CHART)
        assert len(charts) == 1
        assert [series.label for series in charts[0]] == ["Bronze", "Rune", "Crystal"]
        assert charts[0][1].low == 56.0
        assert charts[0][1].high == 175.0
        assert charts[0][1].requirement == 41

    def test_a_single_series_chart_labels_the_resource(self) -> None:
        (curves,) = gathering.parse_success_charts(IRON_CHART)
        assert len(curves) == 1
        assert curves[0].label == "Iron rocks"
        assert (curves[0].low, curves[0].high) == (96.0, 350.0)

    def test_a_page_with_no_chart_yields_nothing(self) -> None:
        assert gathering.parse_success_charts("just prose") == ()

    def test_a_series_missing_its_curve_is_dropped(self) -> None:
        # A legend entry rather than a rate - see `parse_success_charts`.
        text = "{{Skilling success chart|label1=Legend|req1=1}}"
        assert gathering.parse_success_charts(text) == ()


class TestToolSpeeds:
    def test_reads_both_tables_and_resolves_the_colspan(self) -> None:
        speeds = {tool.name: tool for tool in gathering.parse_tool_speeds(PICKAXE_PAGE)}
        # The `Other pickaxes` table is the second one; reading only the first
        # loses four of the twelve tools the export names.
        assert set(speeds) == {"Bronze pickaxe", "Dragon pickaxe", "Gilded pickaxe"}
        assert speeds["Bronze pickaxe"].ticks == 8.0
        assert speeds["Bronze pickaxe"].level == 1

    def test_a_footnote_glued_to_the_number_is_ignored(self) -> None:
        speeds = {tool.name: tool for tool in gathering.parse_tool_speeds(PICKAXE_PAGE)}
        assert speeds["Dragon pickaxe"].ticks == 2.83
        assert speeds["Dragon pickaxe"].level == 61

    def test_a_page_without_the_column_yields_nothing(self) -> None:
        assert gathering.parse_tool_speeds(DESPAWN_PAGE) == ()


class TestNodeCycles:
    def test_reads_prose_durations_as_seconds(self) -> None:
        cycles = {cycle.name: cycle for cycle in gathering.parse_node_cycles(DESPAWN_PAGE)}
        assert cycles["Oak tree"].despawn == 27.0
        assert cycles["Oak tree"].respawn == 8.4
        assert cycles["Yew tree"].despawn == 114.0
        assert cycles["Yew tree"].respawn == 59.4

    def test_the_header_row_is_not_read_as_a_node(self) -> None:
        # This table opens with `|-` before its `!` lines, so `rows` yields the
        # header as row one - a real shape, not a hypothetical.
        assert "Tree" not in {
            cycle.name for cycle in gathering.parse_node_cycles(DESPAWN_PAGE)
        }


class TestSkillCalc:
    def test_reads_name_level_experience_and_kind(self) -> None:
        rows = skillcalc.parse_rows(FISHING_MODULE)
        assert [row.name for row in rows] == ["Raw shrimps", "Raw sardine"]
        assert rows[0].level == 1
        assert rows[0].experience == 10.0
        assert rows[0].kind == "Small net"
        assert rows[0].members is False

    def test_a_rows_own_name_survives_its_materials(self) -> None:
        # The trap the brace matching exists for: splitting on `name =` gives
        # the material's name to the row.
        sardine = skillcalc.parse_rows(FISHING_MODULE)[1]
        assert sardine.name == "Raw sardine"
        assert sardine.materials == (skillcalc.Ingredient("Fishing bait", 1.0),)

    def test_a_row_with_no_materials_picks_up_none(self) -> None:
        assert skillcalc.parse_rows(FISHING_MODULE)[0].materials == ()

    def test_nothing_parseable_yields_nothing(self) -> None:
        assert skillcalc.parse_rows("return {}") == ()


class TestBuildTables:
    def test_sequences_the_four_stages_over_injected_fetches(self) -> None:
        pages = {
            "Willow tree": WILLOW_CHART,
            "Iron rocks": IRON_CHART,
            gathering.PICKAXE_PAGE: PICKAXE_PAGE,
            gathering.WOODCUTTING_PAGE: DESPAWN_PAGE,
            "Module:Skill calc/Fishing": FISHING_MODULE,
        }
        tables = gathering.build_tables(
            lambda template: ["Willow tree", "Iron rocks", "Nowhere"],
            lambda titles: {title: pages[title] for title in titles if title in pages},
        )
        assert set(tables.curves) == {"Willow tree", "Iron rocks"}
        assert tables.tool_ticks["Bronze pickaxe"] == 8.0
        assert tables.cycles["Oak tree"].respawn == 8.4
        assert [row.name for row in tables.actions["Fishing"]] == [
            "Raw shrimps",
            "Raw sardine",
        ]
        # A title that answered with nothing is visible in the accounting
        # rather than silently shortening the table.
        assert tables.sources["success charts"] == (2, 3)

    def test_never_fetches_when_nothing_transcludes_the_template(self) -> None:
        tables = gathering.build_tables(lambda template: [], lambda titles: {})
        assert tables.curves == {}
        assert tables.sources["success charts"] == (0, 0)
