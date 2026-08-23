"""Everything that talks to a machine that is not this one.

`api.py` makes the calls, `wiki.py` parses what the OSRS wiki sends back, and
`scrape.py` is the ~18-request sequence that builds the scraped rate layer out
of both.

**The rule this directory exists to make checkable**: `api.py` is the only
module in the project that opens an outbound connection. That was a sentence in
CLAUDE.md and an honour system; now it is one directory to grep for `urlopen`.
`gui/server.py` remains the one module that accepts *inbound* connections,
which is a different thing and lives with the app that does it.

The map tiles are the host this project never calls: `MAP_TILE_URL` is a
template handed to the browser, because caching the wiki's CC BY-NC-SA
cartography under a GPL-3.0 project would make it a redistributor.

The modules, and what each owns:

- `api.py` - the network. **Five hosts** - the fifth is this project's own
  GitHub releases, the only one about `chunksim` rather than about the game, and
  it **must be a public repo**: GitHub answers unauthenticated requests for a
  private one with 404, and a token shipped in a distributed app is a published
  token. An unknown map is HTTP 200 and a bare `null`, never a 404.
- `wiki.py` - wikitext template parsing and numeric-value extraction
  (arithmetic, `{{#expr:}}`, and what to refuse).
- `wikitable.py` - reading a wikitable: the depth-aware cell splitter and
  `column_index`'s `colspan` resolution.
- `scrape.py` - the sixteen stages (thirty-odd requests) that build the scraped
  layer, and its coverage. **Both apps run it**, so the two cannot write
  different files. Decides no rate.
- `skill_tables.py` - rates from wiki tables, headings and prose, for the skills
  `{{Recipe}}` and the money-making guides cannot describe. **Published hourly
  figures** - somebody else's account; contrast `gathering.py`, which reads what
  a rate is computed *from*. Also the Agility shortcut corpus, where **a list
  is not the world**: `shortcut_pages` reads *every* matching table on the
  `Shortcuts` page rather than the first (the second is headed `Obstacle`), and
  `EXTRA_SHORTCUT_PAGES` names eight more that appear on no list at all.
- `skillcalc.py` - reading a `Module:Skill calc/<Skill>` Lua table, one format
  across eighteen skills. Owns the brace matching, which `farming.py` measured
  first and now imports.
- `bounty.py` - the wiki's bounty table and, from `Boat combat`, the health of
  every sea monster. Health is half the rate, because damage *is* the
  experience.
- `courier.py` - the wiki's courier task table and the coordinates that place
  its ports, from `Courier tasks` and `Module:CourierTaskLine`. Two pages, and
  the second is what turns a port's name into a chunk - which is why this is a
  scrape rather than a hand table.
- `gathering.py` - the inputs a gathering rate is computed from:
  `{{Skilling success chart}}`'s `low`/`high` curves, the tool page's `Ticks
  between rolls`, the despawn/respawn table, the stall and chest restock times,
  the trap-count steps on the Hunter and crab pages, the impling spawn-tier
  tables, and the five skill infoboxes - one of which, `{{Mining info}}`,
  carries **every rock's respawn**, which this project spent a long time
  believing was published nowhere. Also `build_tables`, whose **fetching
  is injected** so the module cannot open a socket.
- `recipes.py` - `{{Recipe}}` as the wiki's Bucket serves it: experience, ticks
  and materials per action, and the `variant` label that says *which* way of
  making the thing a row describes.
- `stores.py` - what a shop charges, and **in what currency**.
- `combat.py` - monster hitpoints and xp multipliers; autocastable spells and
  what each cast consumes.
- `prayer.py` - bones and altars.
- `farming.py` - the Farming calculator's crop table, read as raw Lua.
"""
