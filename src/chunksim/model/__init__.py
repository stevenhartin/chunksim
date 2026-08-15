"""What upstream's data *is*, before anything is derived from it.

The export and the map payload as typed, tolerant accessors (`chunkinfo`,
`summary`), the wire encoding they arrive in (`firebase`), and the two exact
vocabularies they are written in: drop-rate strings (`rates`) and the XP curve
(`experience`).

**The highest fan-in in the project and the lowest churn** - `chunkinfo` and
`summary` have 19 dependents each - which is why they are grouped: a directory
that imports from no other is one you can read first and then stop thinking
about.

`experience.py` sits here rather than with the estimator on purpose. It is the
one exact, non-overridable input, and that separation from `heuristics.py` is
the point of the module; a directory boundary states it better than a docstring
can.

The modules, and what each owns:

- `chunkinfo.py` - typed, tolerant accessors over the parsed export. Build
  **one** per invocation; the ~10MB parse is the expensive part.
- `firebase.py` - the Firebase-safe codec, both ways, including mixed
  `t_N`/literal keys and the encoder the GUI's edit mode writes through.
- `summary.py` - pure reductions over a raw payload; extend this, not the CLI.
  Also `format_age`, and `_mapping`, the tolerant dict accessor eight modules
  import despite the leading underscore.
- `rates.py` - drop-rate string parsing and formatting matching JS's rounding,
  **and its division**, so a zero denominator is `inf`.
- `experience.py` - the exact 1-99 XP curve, closed-form. **Not a heuristic and
  not overridable.**
- `rules.py` - upstream's seed `rules`, for a map this project makes from
  nothing. **A missing rule key skips its gate where `False` refuses it**, so an
  absent branch is the most permissive map there is rather than a neutral one;
  the measurement is in the docstring.
- `edits.py` - a tick written back into a payload, **the one place this project
  writes to upstream's data**. The danger is silence, not complexity.
"""
