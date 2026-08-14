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
"""
