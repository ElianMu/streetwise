# How STROLLANE compares with similar products

Written 2026-11-15 in response to the review point on benchmarking. Product facts were looked up on that date and
each is linked; where a fact could not be confirmed it says so. STROLLANE's own figures come from this repository
(`benchmarks/ROUTE_BENCHMARK.md`, `METHODOLOGY.md`, `AUDIENCE.md`).

**中文摘要。** 主流导航（Google Maps、Citymapper）的步行路线以最快为主，只提供一两个固定选项；专门做"好走的路"的产品和
研究（Go Jauntly、Green Paths、Footways、Happy Maps）都在伦敦、布里斯托或赫尔辛基，每个只优化一到三个方面。STROLLANE
的不同之处是：在曼哈顿、12 个维度可自由组合、每条路线都说明分数由哪些指标算出以及覆盖了多少。最大的短板是没有真人验证：
Happy Maps 用 30 + 54 位参与者证明了路线确实更受欢迎，STROLLANE 目前只有系统自己的分数。

## The comparison

| Product | Where | What a walker can ask for | What the route is built from | Evidence that people prefer the route |
|---|---|---|---|---|
| **Google Maps** | Worldwide | The fastest walk. A "Prefer shade" switch was found in the Android app's code in November 2025 ([Android Authority](https://www.androidauthority.com/google-maps-sun-shade-apk-teardown-3613515/)); I could not confirm that it has launched | Not published | Not published |
| **Citymapper** | Selected cities, New York included | Two fixed choices: *Fast* or *Main Roads*. Main Roads is offered as a proxy for well-lit streets and steers away from parks and river paths ([Citymapper](https://citymapper.com/news/2407/pick-main-roads-for-your-walk-route)) | Road type, surface, pedestrian areas, stairs, elevation ([docs](https://docs.external.citymapper.com/walk/walk-overview.html)) | Not published |
| **Komoot** | Worldwide, outdoor-oriented | Sport type, round trip or one way, and since January 2026 route requirements such as scenery, tranquil paths or flat terrain ([What's New](https://komoot.com/whats-new)). Shows the way types and surfaces of the route | OpenStreetMap way types and surfaces, community highlights | Not published |
| **Go Jauntly** | UK and Ireland | *Green Routes*: the greenest, quietest, least polluted walk from A to B or as a loop ([App Store](https://apps.apple.com/app/1150399087)) | Open environmental datasets and, in London and Bristol, the Tranquil City Index (street design, green space, air and noise pollution) ([Go Jauntly](https://www.gojauntly.com/blog/tranquility-ratings)) | Its own report from a Bristol City Council project: the feature raised the stated likelihood of walking by 36 % ([article](https://countryside-jobs.com/article/2023-02-17-go-jauntlys-green-routes-increased-the-likelihood-of-walking-by-36)) |
| **Green Paths** (University of Helsinki) | Helsinki region; version 2 is built to be moved to other cities | Quieter, cleaner-air or greener walking and cycling routes, each shown against the shortest | Real-time air quality index, modelled traffic noise, street-level greenery from street-view images; open source ([project page](https://www.helsinki.fi/en/researchgroups/digital-geography-lab/green-paths)) | Used in published exposure studies; presented by its authors as a proof of concept |
| **Footways** | Central London | Nothing to ask for: a fixed network of quiet, interesting streets on a printed and online map | Chosen by hand: its founders walked the city and consulted local officers and guides ([SW Londoner](https://swlondoner.co.uk/?p=93905)) | None needed in the same sense; the judgment is the editors' |
| **Happy Maps** (Quercia, Schifanella, Aiello, 2014) | London and Boston; research, not a product | The beautiful, quiet or happy route | Votes from more than 3,300 people comparing pairs of street photos, and Flickr metadata ([paper](https://arxiv.org/abs/1407.1031)) | Yes: 30 participants in London and 54 in Boston judged the recommended routes more beautiful than the shortest ones, at about 12 % extra length ([MIT Technology Review](https://www.technologyreview.com/2014/07/08/12999/forget-the-shortest-route-across-a-city-new-algorithm-finds-the-most-beautiful/)) |
| **STROLLANE · NYC** | Manhattan | Any mix of 12 dimensions, three preset activities, a plain-language request, a destination or a recommended loop | 20 computed indicators from NYC Open Data and OpenStreetMap, ranked within Manhattan; listed per route with sources, time windows and coverage | **None yet.** A benchmark of the router against itself: +8.3 points on the requested dimension for a 4.0 % mean detour over 228 runs. `RESEARCH_PROTOCOL.md` describes the user study; it has not been run |

I found no product offering experience-based walking routes for New York beyond Citymapper's Main Roads switch. That
is a statement about what my search turned up, not proof that none exists.

## What STROLLANE does that the others do not

- **It says what a score is made of.** For each priority the visitor chose, *Why this route?* names the indicators,
  their sources and record dates, the share of the route that has a score, and how the route compares with the
  shortest one. Green Paths shows exposure along a route; none of the commercial products publishes its inputs.
- **Missing data stays missing.** A dimension with no data on a stretch is N/A, never zero and never borrowed, and
  the share of routable length scored on fewer indicators is published (`METHODOLOGY.md`).
- **It declines what it cannot measure.** Asked for something no dataset covers, the request interpreter says so and
  names the nearest dimension instead of bending the request into one (checked on the live site on 2026-11-15).
- **Twelve dimensions that can be combined**, where the others optimise one to three.

## Where STROLLANE is weaker

- **No evidence from walkers.** This is the largest gap. Happy Maps tested its routes with 84 people and Go Jauntly
  reports a behavioural result; STROLLANE's gain is its own metric moving. Until the study in `RESEARCH_PROTOCOL.md`
  is run, "more pleasant" is a hypothesis.
- **Twelve dimensions is the outlier, and not obviously the better choice.** Every product above that reached real
  users offers one to three options. The priority row now leads with three activities and three featured dimensions
  for this reason; whether visitors use the other nine is something the study should record.
- **Static scores.** Green Paths uses real-time air quality and the shade tools reason about time of day. STROLLANE's
  street scores are a snapshot of records retrieved on 2026-10-23; weather is the only live input.
- **One borough**, against city-wide or national coverage.
- **Short trips gain little.** Under 1.5 km, 32 of 72 benchmark runs returned the shortest route and the mean gain
  was 4.2 points, which is why `AUDIENCE.md` aims the product at walks of 20 minutes or more.
- **A web page, not an installed app**, on a host that sleeps when idle, so the first request can take tens of
  seconds.

## What to take from the comparison

1. **Borrow the Happy Maps test.** Show people who know the area the shortest route and the recommended one, without
   saying which is which, and ask which they would rather walk. It is cheap, it needs no app changes, and it is the
   comparison a reviewer will ask for.
2. **Report detour the way they do.** Happy Maps' headline is "about 12 % longer"; STROLLANE's 4.0 % mean detour is a
   strong number and belongs next to any claim about gain.
3. **Keep the transparency.** It is the one thing here no commercial product does, and it costs nothing to keep.
