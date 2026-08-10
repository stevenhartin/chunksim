"""Decode source-chunk's Firebase-safe string encoding.

Object/array keys and values in the raw map payload are passed through
`encodeRFC5987ValueChars`/`encodeObject` (index.js) before being written to
Firebase, so nested payloads read back encoded: `.` `#` `/` `'` `,` `+` `!`
become sentinel tokens (`%2E`, `%2F`, ...), the result is percent-encoded and
`%` is rewritten to `-_-` (Firebase keys can't contain `.`, `#`, `$`, `[`, `]`,
or `/`), purely-numeric keys gain a `*fb*_` prefix (Firebase would otherwise
treat them as array indices), and task names are interned to `t_N` ids via
`tasksMap.json`. This module ports the inverse, `decodeQueryParam` and
`decodeObject`.

Upstream additionally runs decoded strings through `DOMPurify.sanitize` to
strip HTML before they reach the DOM. That defence has no purpose here — this
data is never rendered as HTML — so it's omitted.
"""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Mapping
from typing import Any

# Applied in this order both before and after the real percent-decode pass,
# matching `decodeQueryParam`. These are not real percent-encodings (`G`,
# `H`, `I`, `J`, `Q` aren't hex digits) - they're sentinels chosen so the
# round trip survives `decodeURIComponent`/`unquote`.
_SENTINELS: tuple[tuple[str, str], ...] = (
    ("%2E", "."),
    ("%2F", "#"),
    ("%2G", "/"),
    ("%2H", "'"),
    ("-2H", "'"),
    ("%2I", ","),
    ("%2J", "+"),
    ("%2Q", "!"),
)

# Escapes a stray `%` (not part of a real percent-encoding) before the
# decode pass, so it round-trips to a literal `%` rather than being
# misread. `unquote` is lenient about malformed sequences and would leave
# one unescaped just the same, but this mirrors upstream's guard exactly.
_STRAY_PERCENT = re.compile(r"%(?![0-9a-zA-Z][0-9a-zA-Z]+)")

_NUMERIC_KEY_PREFIX = "*fb*_"


def _apply_sentinels(value: str) -> str:
    for token, replacement in _SENTINELS:
        value = value.replace(token, replacement)
    return value


def decode_string(value: str) -> str:
    """Port of `decodeQueryParam`: reverse the Firebase-safe string encoding."""
    decoded = _apply_sentinels(value.replace("-_-", "%").replace("%25", "%"))
    decoded = _STRAY_PERCENT.sub("%25", decoded)
    decoded = urllib.parse.unquote(decoded)
    return _apply_sentinels(decoded)


def decode_key(key: str, tasks_map: Mapping[str, str] | None = None) -> str | None:
    """Port of `decodeObject`'s per-key handling.

    Returns `None` if `key` is a `t_N` task-id reference absent from
    `tasks_map` - upstream drops such entries rather than keeping a raw id.
    Pass `tasks_map=None` where `key` is known never to hold a task id, to
    skip that lookup (and the drop-on-miss behaviour) entirely.
    """
    if tasks_map is not None and "t_" in key:
        resolved = tasks_map.get(key)
        if resolved is None:
            return None
        key = resolved
    key = decode_string(key)
    if _NUMERIC_KEY_PREFIX in key:
        key = key.split(_NUMERIC_KEY_PREFIX, 1)[1]
    return key


def decode_value(value: str, tasks_map: Mapping[str, str] | None = None) -> str | None:
    """Port of `decodeObject`'s per-string-value handling (dict values only -
    array elements and the top-level scalar case never resolve task ids;
    see `decode_payload`)."""
    if tasks_map is not None and "t_" in value:
        resolved = tasks_map.get(value)
        if resolved is None:
            return None
        value = resolved
    return decode_string(value)


def reverse_tasks_map(tasks_map: Mapping[str, Any]) -> dict[str, str]:
    """Build the `t_N -> task name` map from `tasksMap.json`'s `name -> t_N`.

    `tasksMap.json` also carries a `currentNextIndex` counter (an int, not a
    `t_N` string); it's naturally excluded by the `isinstance` check below.
    """
    return {value: name for name, value in tasks_map.items() if isinstance(value, str)}


def decode_payload(payload: Any, tasks_map: Mapping[str, str] | None = None) -> Any:
    """Port of `decodeObject`: recursively decode a Firebase-encoded payload.

    Dict keys and dict string-values resolve `t_N` task ids through
    `tasks_map` (pass the reverse map from `reverse_tasks_map`); the
    top-level scalar case and array elements never do - this matches
    upstream, which only performs that lookup inside the object-key/value
    branch. An entry whose key or value is an unresolved `t_N` id is
    dropped, as upstream does.
    """
    if isinstance(payload, bool):
        return payload
    if isinstance(payload, str):
        return decode_string(payload)
    if isinstance(payload, list):
        decoded_items: list[Any] = []
        for item in payload:
            if isinstance(item, (dict, list)):
                decoded_items.append(decode_payload(item, tasks_map))
            elif isinstance(item, str):
                decoded_items.append(decode_string(item))
            else:
                decoded_items.append(item)
        return decoded_items
    if isinstance(payload, dict):
        output: dict[str, Any] = {}
        for key, value in payload.items():
            new_key = decode_key(key, tasks_map)
            if new_key is None:
                continue
            if isinstance(value, (dict, list)):
                output[new_key] = decode_payload(value, tasks_map)
            elif isinstance(value, str):
                new_value = decode_value(value, tasks_map)
                if new_value is not None:
                    output[new_key] = new_value
            else:
                output[new_key] = value
        return output
    return payload


def decode_challenge_keyed(
    payload: Any, tasks_map: Mapping[str, str] | None, *, skip_task_ids: bool = False
) -> dict[str, Any]:
    """Decode a `{category: {key: value}}` map-payload branch - the shape
    `activeTasks`/`completedChallenges`/`checkedChallenges`/`backlog` all
    share.

    Inner keys are `t_N` task ids resolved through `tasks_map`, but a given
    branch can mix ids and literal encoded challenge names: `tasksMap.json`
    interns names lazily (it carries a `currentNextIndex` counter), so a
    name that has never been interned is stored literally instead. Real map
    data has both - `completedChallenges.BiS` was 65 ids to 5 literals, and
    `completedChallenges.Extra` 277 to 1, with every literal confirmed
    absent from `tasksMap.json`. `decode_key` already routes each form
    correctly (its `'t_' in key` test can't false-positive on an encoded
    name: the encoding only ever emits `_` inside a `-_-` triple, so `_` is
    always preceded by `-`, never by `t`), so no per-category rule is
    needed here - **do not special-case `BiS`**: it looks literal-only on a
    small sample purely because literal keys sort before `t_N` ones
    (`'O' < 't'`), and skipping id resolution for it silently drops the
    overwhelming majority of its entries.

    Pass `skip_task_ids=True` for `manualTasks`, which genuinely does use
    literal name keys throughout - verified against real map data, where
    its names *are* present in `tasksMap.json` yet are still stored by name.
    """
    if not isinstance(payload, dict):
        return {}
    result: dict[str, Any] = {}
    for raw_category, entries in payload.items():
        category = decode_key(raw_category, None)
        if category is None or not isinstance(entries, dict):
            continue
        result[category] = decode_payload(entries, None if skip_task_ids else tasks_map)
    return result
