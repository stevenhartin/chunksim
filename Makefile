# The compiled development loop.
#
# `setup.py` builds six hot modules with mypyc and this is what turns it on for
# the checkout rather than only for the Windows installer. A roll of a grind
# simulation goes 2.98s -> 2.44s, 18%.
#
# **The cost is that a `.so` shadows the `.py` beside it, silently.** An edited
# source that has not been rebuilt still imports, still answers, and answers
# with the old code - so every target that runs anything rebuilds first, and
# `tests/conftest.py` refuses to collect at all while an extension is older
# than its source. That guard is what makes this safe to leave on; do not
# remove it to save four seconds.
#
# Rebuilds are incremental: ~4.8s when nothing changed, and only the modules
# whose sources moved are recompiled otherwise.
#
# `python3` is the *system* interpreter on purpose, and `--no-build-isolation`
# is implied by using setup.py directly: an isolated backend has no mypy, and
# mypyc reads `[tool.mypy]`, whose `python_executable` is relative to this
# directory. Both mean these targets must run from the repo root.

VENV := .venv/bin
PYTHON := python3

.PHONY: all compile test oracles slow check clean interpreted help

## check: the commit gate - compile, typecheck, run the suite
check: compile
	mypy
	$(VENV)/pytest

## compile: build the mypyc extensions in place (incremental)
#   The stamp is not cosmetic. mypyc decides what to rebuild from source
#   *content*, so a source whose mtime moved without its bytes changing is
#   correctly skipped - and would then sit forever newer than the extension
#   that already matches it, with the staleness guard refusing to run and
#   another `make compile` unable to help. Stamping after a successful build
#   says "these extensions correspond to these sources", which is what the
#   guard is actually asking.
#   `find` rather than a `$(wildcard)`: make expands a whole recipe before
#   running any of it, so a wildcard here would be evaluated before the build
#   and come back empty on the first compile after `make clean`.
compile:
	CHUNKSIM_COMPILE=1 $(PYTHON) setup.py build_ext --inplace
	@find src -name '*.cpython-*.so' -exec touch {} +

## test: the ordinary suite, against compiled modules
test: compile
	$(VENV)/pytest

## oracles: the opt-in correctness signal - needs a populated cache/
oracles: compile
	CHUNKSIM_CHUNKINFO=cache/reference/chunkinfo.json CHUNKSIM_MAP_CACHE=1 \
		$(VENV)/pytest

## slow: the oracles including the ones that take minutes
slow: compile
	CHUNKSIM_CHUNKINFO=cache/reference/chunkinfo.json CHUNKSIM_MAP_CACHE=1 \
		CHUNKSIM_SLOW_ORACLES=1 $(VENV)/pytest

## interpreted: drop the extensions and run the suite as pure Python
#   The `.py` is canonical: if the two ever disagree, this is the right answer
#   and the compiled build is the bug. Worth reaching for when a failure looks
#   like it could be mypyc's rather than yours.
interpreted: clean
	$(VENV)/pytest

## clean: remove every built extension and the mypyc build tree
#   The `__mypyc` shim in src/ is hash-named after the source group, so a
#   changed module list leaves the old one behind; this is what removes it.
clean:
	rm -f src/*.so src/chunksim/*/*.so
	rm -rf build/

## help: list these targets
help:
	@grep -E '^## ' $(MAKEFILE_LIST) | sed 's/^## //'

all: check
