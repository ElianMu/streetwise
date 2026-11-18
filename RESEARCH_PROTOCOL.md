# STROLLANE · NYC — user validation protocol (draft, not yet run)

**Status: a plan. No participant has been recruited, no response collected, and nothing in this repository simulates
user feedback.** The audience groups below are hypotheses to test, not findings.

## 1. Why

The route scores are ranks of proxies computed from public records (`METHODOLOGY.md`). The route benchmark shows the
engine can raise its own score for a requested dimension; it cannot show that a walker perceives a "greener" or
"quieter" walk, or trusts the recommendation. That is the question the critique raised ("Why do you think that's
nice?", "survey people as they use this") and the one this study answers.

## 2. Questions

1. **Understanding** — after reading *Why this route?*, can a participant say what the recommendation is based on?
2. **Trust before walking** — would they choose the recommended route over the shortest one, and why or why not?
3. **Match after walking** — did the walk feel the way the chosen priority promised, and which stretches did or did not?
4. **Proxy validity** — does the perceived difference between two routes go in the same direction as the score
   difference, starting with Nature and Quiet & Relax?
5. **Audience** — does the lead audience chosen in `AUDIENCE.md` (people new to New York) actually want this, and for
   which of its three use cases? Do long-time residents respond differently?

## 3. Design

- **Participants**: 8–12 for a first round. Recruit mainly from the lead audience in `AUDIENCE.md` (people in their
  first year in New York), plus two or three long-time residents as a comparison. Record only: group, how long in NYC
  (banded), how often they walk for leisure (banded).
- **Trips**: use trips from `benchmarks/od_pairs.json` in the medium and long buckets, where the benchmark shows the
  priority actually changes the route. Short trips mostly return the shortest path and cannot test anything.
- **Comparison**: each participant walks **two routes for the same trip**: the shortest route and the priority route,
  in counterbalanced order, **without being told which is which** until the end. Walking only the recommended route
  cannot separate "the route is green" from "I was told it is green".
- **Conditions to record** (they change perceived quiet and greenery): date, start time, weather, season/leaf state.
- **Link to the system**: note the `route_signature` of each route (a field of the `/api/routes` response) plus `score_version` and `network_version`, so every answer traces to an exact route and score build.

## 4. Instruments

Five-point scales (1 = not at all, 5 = very) unless noted. Keep both parts under three minutes.

**Before walking** (after choosing a priority and seeing the routes)

| # | Question | 中文 |
|---|---|---|
| B1 | What kind of walk do you want right now? (free text) | 你现在想要怎样的一段步行？ |
| B2 | In your own words, why does the app recommend this route? (free text) | 用你自己的话说，应用为什么推荐这条路线？ |
| B3 | How clear is the reason for the recommendation? | 推荐理由有多清楚？ |
| B4 | How much do you trust that this route is greener / quieter than the shortest one? | 你有多相信这条路线比最短路线更绿 / 更安静？ |
| B5 | Which would you walk if you were alone: recommended, shortest, or neither? Why? | 如果只有你自己，你会走哪条？为什么？ |

**After each walk** (asked twice, once per route)

| # | Question | 中文 |
|---|---|---|
| A1 | How green did this walk feel? | 这段路感觉有多绿？ |
| A2 | How quiet did this walk feel? | 这段路感觉有多安静？ |
| A3 | How pleasant was it overall? | 整体有多愉快？ |
| A4 | Which stretch matched what you wanted? Which did not? (free text, street names or landmarks) | 哪一段符合你的期待？哪一段不符合？ |

**After both walks**

| # | Question | 中文 |
|---|---|---|
| C1 | Which of the two walks was greener / quieter? (first, second, no difference) | 两段路哪一段更绿 / 更安静？ |
| C2 | (After the reveal) Does the app's recommendation match your experience? | （揭晓后）应用的推荐与你的感受一致吗？ |
| C3 | Was the extra distance worth it? | 多走的路值得吗？ |
| C4 | Would you use this again? For what kind of walk? | 你会再用吗？用在什么样的步行上？ |
| C5 | What made you doubt the recommendation, if anything? (free text) | 有什么让你怀疑过推荐结果？ |

## 5. Analysis

- **Direction agreement** (C1 vs the sign of the score difference between the two routes), reported as a count out
  of N with the score gap beside each case. With 8–12 people this is descriptive, not a significance test.
- **Perceived gap vs score gap**: A1/A2 difference between the two routes plotted against the score difference. Look
  for the smallest score gap people notice; compare it with the 5-point wording threshold in `route-story.js`.
- **Understanding**: code B2 answers as correct / partly / wrong against the indicators actually used.
- Report null and negative results as they are. If people cannot tell the routes apart, that is the finding.

## 6. Privacy and ethics

- No names, emails, device identifiers, GPS traces or precise locations. The trip is one of the fixed benchmark trips,
  so the route is known without tracking anyone.
- Participation is voluntary; walks are in daylight on public streets; participants can stop at any time.
- Before recruiting, confirm with the course instructor whether this needs IRB review or falls under class-project
  practice. Do not publish results beyond the course until that is settled.

## 7. Collecting the answers (technical options)

The site is static (GitHub Pages) with a stateless API, so there is nowhere to store responses today.

1. **External form (recommended first)** — a Google Form or Qualtrics survey. An optional "Tell us how this walk felt"
   link on the route card can pre-fill `route_signature`, `score_version`, chosen priorities and trip id as URL parameters. No
   backend change, no personal data sent by the app. Not implemented yet: it needs the form to exist first.
2. **Paper or interview** — for the first 8–12 people this is enough and gives better free-text answers.
3. **Own endpoint** — a `POST /api/feedback` writing to a small store. Only worth building if a larger second round
   is planned; it adds storage, consent text and abuse handling.
