"""Actions upstream files as training methods and nobody trains with.

**Four shapes, and the `reason` beside each says which.** The status is named
for the first because it came first; what they have in common is that
"how fast can this be repeated" is not a question about the action.

- **A decoration placed once** - the trophy mounts, the boat cosmetics and the
  four pheasant costume pieces. Doing it twice is not the point and mostly not
  possible.
- **A loop whose cadence belongs to a supply nothing states** - the Arceuus
  reanimations wait on ensouled heads dropped by monsters, and `Resurrect
  Crops` on a farming patch having died. Both are repeatable and neither has
  a rate: the spell's own cast is instant beside the wait, so a figure
  computed from the cast would be a claim about the spell when the answer is
  a property of the drop table or the growth clock. That is the shape
  `costing/disclaimed.py` describes as "everything needed for a model is
  published except the one thing that matters".

  **The five splitbark pieces are the same shape wearing a minigame's name.**
  Each is sewn from bark and a `Fine cloth`, and fine cloth comes only from
  the Shades of Mort'ton reward chests - so what decides how often one can be
  sewn is how fast the minigame's whole loop can be run, and nothing
  publishes that. See their entries for the shares upstream states.
- **A permanent upgrade assembled once out of unique drops.** The seven
  avernic tread variants each destroy a pair of boss-drop treads and one or
  more of the three boot upgrades and hand back a single better boot; the
  noxious halberd is three Araxxor drops made into one weapon; the toxic
  blowpipe is one Zulrah fang and a chisel; the three rat bone weapons are one
  `Scurrius' spine` and a base weapon. There is one
  slot and the inputs are gone, so a second is not a slower repeat of the
  first - it is a thing nobody does. This is the *mounts* argument without
  their complication: no page anywhere says a duplicate pays again.

  **The rat bone three are where the game says it in so many words**: one
  spine makes a mace, a shortbow *or* a staff, so at most one of the three
  happens at all - and "excess spines can be traded to Historian Aldo for
  experience lamps", which is upstream stating the use of a second spine and
  it is not a second bow.

  **A rate is not the test, and the mace is the proof.** `Make a ~|bone
  mace|~` was the only one of the three whose `{{Recipe}}` states ticks, so it
  alone priced - at 357/hr, a plausible number on a real task - while its two
  identical siblings read `unpriced`. `one_off` is checked *ahead* of every
  priced tier precisely so an accident of the wiki's coverage cannot decide
  which of three identical challenges is a training method.

  **"The inputs are gone" is a claim to check, not to assume**, and the
  blowpipe is where it earns its keep: destroying a *sword mount* hands the
  quest weapon straight back, which is why those are a priced build-and-destroy
  loop in `recipe_rates.RETURNED_MATERIALS` rather than an entry here.
  Dismantling a blowpipe yields 20,000 Zulrah's scales and no fang.

- **An obstacle opened once and then permanently open.** The God Wars
  Dungeon rope descent is a `Tie-rope` at Agility 70 followed by a free
  `Climb-down` for ever, which is precisely what `costing/shortcuts.py`
  assumes no shortcut is - see the entry's own note.

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
    # **A head slot filled once, out of a reward pool rather than a drop
    # table.** The twelve ordinary tiaras beside this one are priced and
    # rightly so - their talismans are common drops and the loop really is
    # repeatable, which is why `Craft an air tiara` reads 184/hr. The
    # catalytic talisman is not a drop at all: it comes "from the Rewards
    # Guardian, using points earned while playing Guardians of the Rift",
    # and making the tiara consumes it. What is left is a permanent
    # convenience - the tiara opens every catalytic altar from the head
    # slot, "freeing up an inventory slot that the catalytic talisman would
    # otherwise occupy" - so a second one does nothing, exactly as a second
    # pair of avernic treads does nothing.
    "Craft a ~|catalytic tiara|~": (
        "a head slot filled once - the talisman is a Guardians of the Rift "
        "reward rather than a common drop, and the tiara consumes it"
    ),
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
    # **A permanent upgrade fused once, and the fusion eats both halves.**
    # The seven avernic tread variants each consume a pair of `Avernic
    # treads` - a Doom of Mokhaiotl drop - plus one or more of the three
    # boot upgrades, and hand back a single better boot. Nobody makes a
    # second pair: there is one slot, the inputs are destroyed, and each of
    # the boots behind them is itself a one-time build (`Eternal boots` is
    # an eternal crystal from Cerberus fused onto infinity boots bought over
    # an hour at the Mage Training Arena).
    #
    # **Named individually like everything else here**, and the seven are
    # the whole family: upstream carries them under Smithing and Runecraft
    # alike, with the same `Items` and the same `Priority` block.
    "Create ~|avernic treads (et)|~": "a permanent fusion that eats both boots",
    "Create ~|avernic treads (pe)|~": "a permanent fusion that eats both boots",
    "Create ~|avernic treads (pr)|~": "a permanent fusion that eats both boots",
    "Create ~|avernic treads (pe)(et)|~": "a permanent fusion that eats both boots",
    "Create ~|avernic treads (pr)(et)|~": "a permanent fusion that eats both boots",
    "Create ~|avernic treads (pr)(pe)|~": "a permanent fusion that eats both boots",
    "Create ~|avernic treads (max)|~": "a permanent fusion that eats both boots",
    # **The same fusion shape one weapon over.** A noxious halberd is three
    # unique Araxxor drops - point, blade and pommel - assembled into one
    # weapon. Upstream files it under Crafting and Smithing alike and one
    # entry covers both, since `ONE_OFF` is keyed by task.
    "Craft a ~|noxious halberd|~": "three unique drops assembled into one weapon",
    # **And the same shape from a single drop, with the check that matters.**
    # A toxic blowpipe is a chisel on a `Tanzanite fang`, which upstream puts
    # at 1/1024 off Zulrah. The tempting objection is the sword mounts', where
    # destroying the object hands the quest weapon back and the loop is real
    # (`recipe_rates.RETURNED_MATERIALS`) - so the page was checked and says
    # the opposite: "players can dismantle an uncharged blowpipe to receive
    # 20,000 Zulrah's scales", and nothing anywhere returns the fang. It never
    # breaks either, so one is made and kept.
    "Fletch a ~|toxic blowpipe|~": "one Zulrah drop consumed into a permanent weapon",
    # **Three weapons and one spine, so at most one of them happens.** A
    # `Scurrius' spine` (1/33) is attached to a rune mace, a yew shortbow or a
    # battlestaff to make the rat bone weapon of that class - each permanent,
    # each non-degrading, each one slot. The game says outright what a second
    # spine is for and it is not a second bow: "excess spines can be traded to
    # Historian Aldo for experience lamps".
    #
    # **The mace is why "it has a rate" is not the test.** Its `{{Recipe}}`
    # states ticks where the other two leave them blank, so it alone priced -
    # at 357/hr, a plausible number on a real task for a thing nobody repeats -
    # while its two identical siblings read `unpriced`. Naming one and not the
    # others would file the same mechanic three ways.
    #
    # The staff's 1,000 chaos runes are a *charge*, not a material -
    # "uncharging the staff returns all remaining runes back" - and no page
    # states a reversion for any of the three, so the spine is gone.
    "Make a ~|bone mace|~": "one spine, one weapon slot, and a second is a lamp",
    "Make a ~|bone shortbow|~": "one spine, one weapon slot, and a second is a lamp",
    "Make a ~|bone staff|~": "one spine, one weapon slot, and a second is a lamp",
    # **A door opened once stays open, which is the opposite of every other
    # Agility obstacle.** `costing/shortcuts.py`'s whole argument is that a
    # shortcut is used again every time you pass, so eight ticks is a cadence;
    # the God Wars Dungeon rocks are not that. `Rock (God Wars Dungeon)` says
    # "a rope must be attached to each rock one time, requiring 70 Agility
    # before it can be used", and the infobox carries the tie and the climb as
    # separate versions - `Tie-rope` at level 70, `Climb-down` free forever
    # after. There is no second tie to time.
    #
    # **This is also how the one place two wiki sources disagree stops
    # mattering.** The page's own `{{Agility info}}` states `xp = 0` where the
    # `Shortcuts` list's `XP` column says 6, and nothing here can say which is
    # right. `one_off` is checked ahead of every priced tier, so the answer is
    # the same either way - which is the better resolution than picking a
    # number, and better than `shortcuts.REFUSED`, whose test *is* the zero.
    "Access the rope descent to ~|Saradomin's Encampment|~": (
        "a rope tied to the rock once at level 70, then climbed free forever"
    ),
    # **The supply is a reward chest in a minigame nothing times.** Splitbark
    # is sewn from `Bark` and `Fine cloth`, and fine cloth comes only from the
    # Shades of Mort'ton reward chests - "from any level of chest other than
    # bronze, but the higher level chests have a better chance". Upstream
    # states the shares and the best of them is a **gold chest at 21/143.91**,
    # about one open in seven, with a silver at the same rate, a black at one
    # in twenty and a steel at one in 1,679. Eleven pieces make the set.
    #
    # **The rate is not the test and the chest's share is not either.** What
    # disqualifies these is the shape the Arceuus reanimations are in: a chest
    # is earned by running the whole minigame - gathering kindling, cremating
    # shades, buying keys - and nothing anywhere publishes how long that
    # takes, so a figure computed from the sewing would describe the sewing
    # when the answer is a property of the minigame. `estimate._route_hours`'
    # certainty gate refuses the chest roll for its own reasons and would
    # leave these five reading `unpriced`, which says a model has a gap where
    # the truth is that the question does not arise.
    "Craft a ~|splitbark body|~": "fine cloth is a Shades of Mort'ton chest roll",
    "Craft a ~|splitbark boots|~": "fine cloth is a Shades of Mort'ton chest roll",
    "Craft a ~|splitbark gauntlets|~": "fine cloth is a Shades of Mort'ton chest roll",
    "Craft a ~|splitbark helm|~": "fine cloth is a Shades of Mort'ton chest roll",
    "Craft a ~|splitbark legs|~": "fine cloth is a Shades of Mort'ton chest roll",
    # **A costume, and the tempting reason is the wrong one.** The four
    # pheasant pieces are "a piece of the pheasant costume", stored in a
    # magic wardrobe - so they are the *first* shape here, a decoration made
    # once, beside the trophy mounts and the boat cosmetics.
    #
    # **Not the event's cadence**, which is what this looked like: the
    # feathers come from the Pheasant Control Forestry event, and
    # `costing/forestry.py` already states 30 events an hour force-spawned, so
    # "nothing publishes how often" would simply be false. Nor is it rarity -
    # upstream puts the feather at `1/2` on the event's own table, a coin
    # flip. What settles it is that a costume piece is not a thing anybody
    # makes twice.
    "Craft a ~|pheasant hat|~": "a pheasant costume piece, stored in a wardrobe",
    "Craft ~|pheasant legs|~": "a pheasant costume piece, stored in a wardrobe",
    "Craft ~|pheasant boots|~": "a pheasant costume piece, stored in a wardrobe",
    "Craft a ~|pheasant cape|~": "a pheasant costume piece, stored in a wardrobe",
    # **The top of a one-slot ladder, and the game states what a spare is
    # for.** A gem sack is made "by combining a gem tote, gem bag, and
    # immaculate mole skin" - both containers go *into* it, so there is one
    # sack and no second to make. That is the same third shape as the avernic
    # treads, and it has the rat bone weapons' clincher beside it:
    # `Immaculate mole skin` says outright that "extra immaculate mole skins
    # can be exchanged with Wyson the gardener for five bird nests", which is
    # the game naming the use of a second one and it is not a second sack.
    #
    # (Upstream marks the bag and the tote *unmarked* while the wiki says
    # both are combined in. `*` is not reliable by itself - see the quest
    # prizes in `costing/spells.py` - and the wiki is explicit here.)
    "Craft a ~|gem sack|~": "one gem slot: the bag and tote are combined into it",
}


def reason(task: str) -> str:
    """Why `task` is not a training method, or `""` if it is one."""
    return ONE_OFF.get(task, "")
