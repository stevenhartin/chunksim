"""Actions upstream files as training methods and nobody trains with.

**Two shapes, and the `reason` beside each says which.** The status is named
for the first because it came first; what the two have in common is that
"how fast can this be repeated" is not a question about the action.

- **A decoration placed once** - the trophy mounts and boat cosmetics. Doing
  it twice is not the point and mostly not possible.
- **A loop whose cadence belongs to a supply nothing states** - the Arceuus
  reanimations wait on ensouled heads dropped by monsters, and `Resurrect
  Crops` on a farming patch having died. Both are repeatable and neither has
  a rate: the spell's own cast is instant beside the wait, so a figure
  computed from the cast would be a claim about the spell when the answer is
  a property of the drop table or the growth clock. That is the shape
  `costing/disclaimed.py` describes as "everything needed for a model is
  published except the one thing that matters".

**A method's rate is only meaningful if repeating it is the point.** Every
other status this project reports answers "what priced this"; these are
challenges where that question does not arise. Reporting them
as `unpriced` says the model has a gap, and reporting them at their arithmetic
rate says something is worth doing that nothing is.

### The four mounts, and the honest reason

**Not "one-time" - the wiki is explicit that it is not.** `Mounted bass` says
"Duplicate big fish can be added for additional experience, provided that the
player has stuffed them and are in building mode", so a second fish really
does pay again. What it also says is "however they **cannot** be removed to
retrieve the stuffed fish", and that is the half that matters: each repeat
consumes a fresh big fish, and a big fish is a rare roll off ordinary fishing
(`Big bass` 1/1000, `Big swordfish` 1/2500, `Big shark` 1/3000). Priced
end to end that is **3.0 to 3.5 experience an hour** - ten to twenty hours of
fishing for one 31-experience placement.

**The rate is not what disqualifies them.** Construction already lists
`steel dragon (Construction)` and `dagannoth (Construction)` at 3/hr and this
project deliberately removed the floor that used to hide such methods - a slow
method is a slow method. What separates these is that the *display* is the
repeatable Construction action and is priced as one (`Oak display` at 120
experience for two oak planks, and its teak and mahogany tiers); the mount is
the trophy you put on it. Upstream models the pair as two challenges and only
the first is training.

**`Alchemical hydra heads (mounted)` is the same shape** - a `Gilded display`
plus a boss drop, with its own page saying the stuffed head "cannot be removed"
either.

### The three boat cosmetics

`Build one of the boat ~|flags|~`, `Apply a ~|boat paint|~ to a boat` and
`Apply a ~|sail colour|~ to a sail` are the clearer case: the Sailing page
describes them as customisation options beside the hull/keel/mast upgrades that
do pay Construction, and no `{{Recipe}}` anywhere states a duration for them.
They were already unpriced for want of a recipe; naming them here says *why*
rather than leaving them in a bucket that means "nothing reached this".

### Why a status rather than a filter

Dropping them from the report would make the per-skill totals stop adding up to
the export's own count, and a reader who went looking for `Build a ~|mounted
bass|~` would find it nowhere at all. A status keeps every challenge visible
and says which question it is exempt from.

**Named individually, never inferred.** There is no property of the export that
marks a decoration - upstream flags all seven `Primary: True`, exactly as it
flags `Build a ~|wooden fence|~` - so a rule over `(mounted)` names or over
`Category: InsidePOH Primary` would sweep in the sword mounts (a real
build-and-destroy loop, `recipe_rates.RETURNED_MATERIALS`) and most of the
furniture. Each entry here was checked against its own wiki page.

Pure: a frozen set of task names, and a predicate over it.
"""

from __future__ import annotations

#: `{task: why}` for every challenge exempt from being priced, with the
#: sentence that settles it. See the module docstring for the reasoning and
#: for why this is a list rather than a rule.
ONE_OFF: dict[str, str] = {
    "Build a ~|mounted bass|~": (
        "a trophy on a display, and the display is the repeatable action - each "
        "mount consumes a Big bass (1/1000 off bass fishing), so repeating it is "
        "~3 xp/hr"
    ),
    "Build a ~|mounted swordfish|~": (
        "a trophy on a display - each mount consumes a Big swordfish (1/2500), so "
        "repeating it is ~3 xp/hr"
    ),
    "Build a ~|mounted shark|~": (
        "a trophy on a display - each mount consumes a Big shark (1/3000), so "
        "repeating it is ~3.5 xp/hr"
    ),
    "Build an ~|alchemical hydra heads (mounted)|~": (
        "a trophy on a gilded display - the stuffed head cannot be removed, and "
        "each mount consumes a boss drop"
    ),
    "Build one of the boat ~|flags|~": "a boat cosmetic, not a hull upgrade",
    "Apply a ~|boat paint|~ to a boat": "a boat cosmetic, not a hull upgrade",
    "Apply a ~|sail colour|~ to a sail": "a sail cosmetic, not a mast upgrade",
    # **The cadence is the head supply, not the cast.** An ensouled head is a
    # monster drop, and the spell is instant beside the wait for one - so a
    # rate computed from the cast would describe the spell where the answer
    # is a property of the drop table.
    "Cast ~|basic reanimation|~": "waits on ensouled heads, which are a drop",
    "Cast ~|adept reanimation|~": "waits on ensouled heads, which are a drop",
    "Cast ~|expert reanimation|~": "waits on ensouled heads, which are a drop",
    "Cast ~|master reanimation|~": "waits on ensouled heads, which are a drop",
    # Same shape against a different clock: you cannot resurrect a crop that
    # has not died, so the cadence is the growth schedule's.
    "Cast ~|resurrect crops|~": "waits on a farming patch dying",
}


def reason(task: str) -> str:
    """Why `task` is not a training method, or `""` if it is one."""
    return ONE_OFF.get(task, "")
