"""Tests for the Firebase-safe string codec.

`decode_string`'s isolated-sentinel cases are grounded directly in the
`replaceAll` table read from `decodeQueryParam` (index.js); the two
`-_-20`/`-_-27` cases are copied verbatim from real values seen in a fetched
map payload (`chunkinfo.activeTasks`, `chunkinfo.completedChallenges`), not
fabricated.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chunksim.model.firebase import (
    encode_key,
    encode_string,
    reverse_tasks_map,
    decode_challenge_keyed,
    decode_key,
    decode_payload,
    decode_string,
    decode_value,
    reverse_tasks_map,
)


def test_decode_string_leaves_plain_text_untouched() -> None:
    assert decode_string("Cooking") == "Cooking"


def test_decode_string_reverses_the_dash_underscore_percent_marker() -> None:
    assert decode_string("a-_-20b") == "a b"


def test_decode_string_reverses_the_dot_sentinel() -> None:
    assert decode_string("a%2Eb") == "a.b"


def test_decode_string_reverses_the_hash_sentinel() -> None:
    assert decode_string("a%2Fb") == "a#b"


def test_decode_string_reverses_the_slash_sentinel() -> None:
    assert decode_string("a%2Gb") == "a/b"


def test_decode_string_reverses_the_apostrophe_sentinels() -> None:
    assert decode_string("a%2Hb") == "a'b"
    assert decode_string("a-2Hb") == "a'b"


def test_decode_string_reverses_the_comma_sentinel() -> None:
    assert decode_string("a%2Ib") == "a,b"


def test_decode_string_reverses_the_plus_sentinel() -> None:
    assert decode_string("a%2Jb") == "a+b"


def test_decode_string_reverses_the_bang_sentinel() -> None:
    assert decode_string("a%2Qb") == "a!b"


def test_decode_string_percent_decodes_a_real_hex_escape() -> None:
    assert decode_string("a%20b") == "a b"


def test_decode_string_tolerates_a_stray_percent() -> None:
    assert decode_string("100% mined") == "100% mined"


def test_decode_string_reproduces_a_real_task_name() -> None:
    # From `chunkinfo.activeTasks.BiS` in a fetched map payload.
    assert decode_string("Melee-_-20BiS-_-20feet") == "Melee BiS feet"


def test_decode_string_reproduces_a_real_apostrophe() -> None:
    # From `chunkinfo.completedChallenges.BiS` in a fetched map payload.
    assert decode_string("craw-_-27s") == "craw's"


def test_decode_key_strips_the_numeric_key_marker() -> None:
    assert decode_key("*fb*_13874") == "13874"


def test_decode_key_leaves_a_plain_key_untouched() -> None:
    assert decode_key("Boosting") == "Boosting"


def test_decode_key_resolves_a_task_id() -> None:
    assert decode_key("t_10460", {"t_10460": "Obtain a whip"}) == "Obtain a whip"


def test_decode_key_drops_an_unresolved_task_id() -> None:
    assert decode_key("t_99999", {}) is None


def test_decode_key_skips_task_resolution_without_a_tasks_map() -> None:
    assert decode_key("t_99999", None) == "t_99999"


def test_decode_value_resolves_a_task_id() -> None:
    assert decode_value("t_10460", {"t_10460": "Obtain a whip"}) == "Obtain a whip"


def test_decode_value_drops_an_unresolved_task_id() -> None:
    assert decode_value("t_99999", {}) is None


def test_reverse_tasks_map_excludes_the_index_counter() -> None:
    tasks_map = {"Obtain a whip": "t_1", "currentNextIndex": 2}

    assert reverse_tasks_map(tasks_map) == {"t_1": "Obtain a whip"}


def test_decode_payload_decodes_nested_keys_and_values() -> None:
    payload = {"*fb*_13874": {"*fb*_1": True, "*fb*_2": False}}

    assert decode_payload(payload) == {"13874": {"1": True, "2": False}}


def test_decode_payload_resolves_task_ids_in_dict_keys() -> None:
    payload = {"t_10460": True, "t_99999": True}
    tasks_map = {"t_10460": "Obtain a whip"}

    assert decode_payload(payload, tasks_map) == {"Obtain a whip": True}


def test_decode_payload_never_resolves_task_ids_in_array_elements() -> None:
    # Upstream's `decodeObject` array branch calls `decodeQueryParam` directly
    # on each element, with no `tasksMapReverse` lookup - unlike its
    # dict-value branch.
    payload = ["t_10460"]
    tasks_map = {"t_10460": "Obtain a whip"}

    assert decode_payload(payload, tasks_map) == ["t_10460"]


def test_decode_payload_top_level_string_never_resolves_task_ids() -> None:
    # Matches upstream: only the dict-value branch does t_ resolution.
    assert decode_payload("t_10460", {"t_10460": "Obtain a whip"}) == "t_10460"


def test_decode_payload_leaves_non_string_scalars_untouched() -> None:
    assert decode_payload({"level": 32, "primary": True, "empty": None}) == {
        "level": 32,
        "primary": True,
        "empty": None,
    }


def test_decode_challenge_keyed_resolves_task_ids_per_category() -> None:
    payload = {"Woodcutting": {"t_1": True}, "Diary": {"t_2": True}}
    tasks_map = {"t_1": "Chop a tree", "t_2": "Do a diary task"}

    assert decode_challenge_keyed(payload, tasks_map) == {
        "Woodcutting": {"Chop a tree": True},
        "Diary": {"Do a diary task": True},
    }


def test_decode_challenge_keyed_resolves_task_ids_in_the_bis_category() -> None:
    # Regression: `BiS` was special-cased to skip `t_N` resolution, on the
    # false premise that its keys are always literal names. Real map data
    # had 65 ids to 5 literals there, so skipping resolution silently
    # dropped the overwhelming majority of completed BiS entries (they
    # stayed as raw `t_N` and matched no generated task name).
    payload = {"BiS": {"t_10226": True}}
    tasks_map = {"t_10226": "Obtain a ~|black cape|~"}

    assert decode_challenge_keyed(payload, tasks_map) == {
        "BiS": {"Obtain a ~|black cape|~": True}
    }


def test_decode_challenge_keyed_handles_a_category_mixing_ids_and_literals() -> None:
    # A name is only stored literally when it has never been interned into
    # `tasksMap.json`, so one category can hold both forms at once.
    payload = {"BiS": {"t_1": True, "Obtain-_-20a-_-20~|zamorak-_-20monk-_-20top|~": True}}
    tasks_map = {"t_1": "Obtain a ~|black cape|~"}

    assert decode_challenge_keyed(payload, tasks_map) == {
        "BiS": {"Obtain a ~|black cape|~": True, "Obtain a ~|zamorak monk top|~": True}
    }


def test_decode_challenge_keyed_skips_task_ids_when_asked() -> None:
    # `manualTasks` stores literal names for every category even when those
    # names *are* interned - verified against real map data.
    payload = {"Quest": {"~|Nature-_-20Spirit|~-_-20Complete-_-20the-_-20quest": True}}

    assert decode_challenge_keyed(payload, {}, skip_task_ids=True) == {
        "Quest": {"~|Nature Spirit|~ Complete the quest": True}
    }


def test_decode_challenge_keyed_tolerates_a_missing_branch() -> None:
    assert decode_challenge_keyed(None, {}) == {}
    assert decode_challenge_keyed({}, {}) == {}


# --- writing a payload back ------------------------------------------------
#
# This module was decode-only until the GUI needed to tick a task off. Reading
# a map never needs an encoder; writing one does, and a mis-encoded key is the
# worst kind of defect available here - `decode_challenge_keyed` would simply
# not see the tick, and the map would derive as though it had never happened.


def test_a_string_survives_the_round_trip() -> None:
    """Every character the codec has a sentinel for, plus the `%` escape that
    has to be applied first."""
    for value in ("a.b", "a#b", "a/b", "a'b", "a,b", "a+b", "a!b", "50%", "plain"):
        assert decode_string(encode_string(value)) == value


def test_the_percent_escape_is_applied_before_the_sentinels() -> None:
    """`decode_string` undoes them in the opposite order - `-_-` to `%` first,
    then the table - so encoding the other way round would let a `%` the
    sentinels introduced be escaped a second time."""
    assert encode_string("100%.") == "100-_-%2E"
    assert decode_string("100-_-%2E") == "100%."


def test_a_numeric_key_regains_its_prefix() -> None:
    """Firebase cannot hold a purely numeric key, so upstream prefixes one;
    `decode_key` strips the prefix and this has to put it back."""
    assert decode_key(encode_key("123"), None) == "123"
    assert encode_key("123").startswith("*fb*_")


def test_an_apostrophe_takes_the_canonical_sentinel() -> None:
    """The table maps *two* tokens to `'` - `%2H` and `-2H` - because
    upstream's own encoding is not injective there. The first is canonical."""
    assert encode_string("craw's bow") == "craw%2Hs bow"
    assert decode_string("craw-2Hs bow") == "craw's bow"


@pytest.mark.real_cache
def test_every_real_task_name_survives_the_round_trip() -> None:
    """**The claim that matters, over 49,721 real names.**

    `encode(decode(k)) == k` is deliberately *not* asserted: upstream percent-
    encodes a space as `%20` and then escapes the `%`, so its keys hold
    `-_-20` where this writes a plain space. The encoding is not canonical and
    does not need to be - what a tick requires is that the name this writes
    reads back as the same name, which is the direction below.

    The two sequences that cannot round-trip (`-_-` and `-2H`, documented on
    `encode_string`) appear in no real name, which is the only honest defence:
    guarding a case upstream never produces would be inventing a format.
    """
    # This checkout's own cache, not a `tmp_path` - the `real_cache` marker is
    # exactly the statement that it is populated.
    root = Path(__file__).resolve().parent.parent
    blob = json.loads((root / "cache" / "reference" / "tasks_map.json").read_text())
    names = set(reverse_tasks_map(blob["data"]).values())

    assert len(names) > 1_000, "expected the real interning table"
    assert [name for name in names if decode_string(encode_string(name)) != name] == []
    assert [name for name in names if "-_-" in name or "-2H" in name] == []
