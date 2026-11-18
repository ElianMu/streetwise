# STROLLANE · NYC — who it is for

**Status: a design decision resting on a hypothesis. No user research has confirmed it yet** (see
`RESEARCH_PROTOCOL.md`). It answers the critique's question "What is important and to whom?" with a choice that can
be tested and, if wrong, changed.

## Lead audience: people new to New York

People in their first year in the city (new students, recent movers) who have free time and want to get to know a
Manhattan neighbourhood on foot.

Why this group, on the evidence available:

- **The product only pays off on longer, unhurried walks.** In the route benchmark (`benchmarks/ROUTE_BENCHMARK.md`),
  choosing a priority raised that dimension's route score by 4.2 points on average for trips under 1.5 km, where
  32 of 72 runs simply returned the shortest route, against 9.4 points for 1.5–3 km and 12.5 points for 3 km
  and more. Someone going somewhere in a hurry gets nothing from it; someone with 20 minutes or more to spare does.
- **They do not already know which streets are pleasant.** A long-time resident has their own routes. A newcomer has
  the time and the reason to choose a street by what it is like.
- **They come back.** A visitor uses a tool for a few days. A newcomer explores for months, which is what a tool built
  on street-by-street differences needs.
- **They can be reached for validation.** A first round of 8–12 walk-along participants can be recruited among new
  students, so the trust question the critique raised can actually be tested with this group.
- **Coverage fits.** Scores exist for Manhattan only, which is where this group explores first.

## Use cases built around the lead audience

| Use case | What they do | Dimensions it leans on |
|---|---|---|
| Get to know a neighbourhood | Start from where they are, no destination, 30–60 minutes ("Discover for me") | Nature, Quiet & Relax, Architecture |
| Take the nicer way | Between two places they already go (home, campus, a park), accepting a modest detour | Quiet & Relax, Nature, Spatial Comfort |
| A walk with a point | A walk that passes a few places worth knowing (parks, museums, a café) | Culture, Food & Retail, plus the journey stops |

In the app these three are the first three buttons of the walk-priorities row (`walk-presets.js`, `WALK_ACTIVITIES`).
Each button only switches on the dimensions in its row above at the same weight a single pill sets (80); it adds no
dimension, score or route. Walk length is not a new setting either: with no destination the existing recommender
(`journey.js`, `prepareRecommendedWalk`) proposes a walk past real places, 60 minutes for a loop and 75 minutes
open-ended; with a destination the router goes there along streets ranked by those dimensions. The three dimensions of
the first use case (Nature, Quiet & Relax, Architecture) are also the first three pills; the other nine follow in
benchmark order and none is removed.

## Secondary audience: residents who walk for leisure

Same product, different entry: they mostly use "take the nicer way" between familiar places. Nothing extra is built
for them now.

## Not the lead: short-stay visitors

Visitors are landmark-driven and short of time, which is the case the benchmark shows the least benefit for. The
existing visitor features (hotel as a base, luggage storage, services) stay available but are not what the first
screen is written for.

## What would change this decision

- Walk-along participants who are new to the city do not notice or value the difference between the priority route and
  the shortest one, while another group does.
- New arrivals turn out to use it mainly for short point-to-point trips, where it adds little.
- Visitors, not newcomers, are the ones who return to it.
