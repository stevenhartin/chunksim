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
"""
