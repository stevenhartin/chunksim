# Let's start putting in the work to estimate the chunk completion time

Useful Source:

* [osrs wiki](https://oldschool.runescape.wiki/) is the old school wiki with lots of pages containing estimates for time

Outcome:

* We produce an estimate time to complete the outstanding valid tasks

How will we do this:

* It's going to be very heuristic driven.
* A lot is going to be estimates based off high level assumptions. We do not need an accurate estimate, it just needs to give a rough idea.

 Herustics:

* We can bucket tasks into the following:
  * Quests
  * Boss Drops (Which can give items for quests, tasks, BiS slots)
  * Activity Unlocks (Which can also give items for quests, tasks, BiS slots) (Similar to a 'boss')
  * Skilling requirements (Levels to unlock)

What we need to do is work out all the item requirements for a chunk.

* For example, if we need to complete the BiS task to "Obtain an Inquisitor's plateskirt", we need to identify that this requires the "Inquisitor Plateskirt" item
* We then need to work out the sources for that item, it will usually be a boss drop or an activity unlock.
* We then need to work out the drop rate and apply an estimate for average kills per hour for that particular boss to give us a rough estimate to otbain the item.

Quest:

* Quest time can be obtain from [osrs quest list](https://oldschool.runescape.wiki/w/Quests/List), it lists the "Length".
* We should assume Very Short is 10 minutes, Short is an hour, Medium is 2 hours, Long is 4 hours and Very Long is 6 hours.
* This does not include the time taken to obtain the items for the quest, use the aformentioned heuristics for that for new items. Assume we already have items which are not new to this chunk.
* If we only need to do a partial step, simply assume quest progression is linear. E.g. if we only need to do 2/8 steps for a short quest, we should apply 2/8 to the 1 hour to give us 1/4 hour.

We can search either the wiki or Google for the best kills per hour using optimal gear. We should use this as our initial estimate. Eventually we will do something a bit smarter, but for example searching for "General Graardor kills per hour" sends us to this wiki page, [Money Making Guide/Killing General Graardor](https://oldschool.runescape.wiki/w/Money_making_guide/Killing_General_Graardor), which lists it as 27 kills per hour.

We should create a tool to try and scrape this data together, generate a config file which lists all the heurstic categories. We should base this off the chunkinfo JSON, so we should have a heuristic for every item, even things we've already obtained or aren't part of our chunk data.
This should be ran very infrequent (effectively whenever we update the chunkinfo). If it's a config file we should be able to adjust the values ourselves and correct the results by hand.
