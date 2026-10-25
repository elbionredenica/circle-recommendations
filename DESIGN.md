# Design

## What I built

A FastAPI service that ranks Circles for a member and gives three plain-language reasons per pick. The seed data loads into SQLite on startup. The ranking is about 90 lines of pure functions in `app/recommender.py`, so each rule can be tested on its own.

## How it ranks

1. **Filter.** Drop Circles she's already in, unlisted Circles, full Circles, and Circles quiet for more than 45 days.
2. **Sort by three keys, in order.** Her topic, then whether she can surely attend, then health. An earlier key always wins. The first two are strict priorities, so a sort expresses them directly, where a weighted score would need tuned weights to imitate them.
3. **Keep one Circle per topic.** Set aside any Circle whose topic is already on the list, and use set-aside Circles only to fill leftover slots. Same-topic Circles share a description here, so topic is the best duplicate signal available. This is [Maximal Marginal Relevance](https://www.elastic.co/search-labs/blog/maximum-marginal-relevance-diversify-results) with a yes-or-no similarity. A repeat always loses to a new topic, so there's no λ to tune.
4. **Explain.** Three template sentences, built only from facts that ranked the Circle: why it fits her, when it was last active, and how it meets.

**Health** averages four credits, each from 0 to 1. Posts, chat, and engagement per post (reactions + 2 × comments + saves) each count up to "enough", the 75th percentile across Circles, so the busiest Circles can't take every slot. Recency halves every 15 quiet days. The four credits count equally, because nothing in the data gives a reason to weight one over another. "Now" is the latest timestamp in the snapshot.

## Signals

| Signal | What the data shows | Decision |
|---|---|---|
| Topic interests | Members are 2.4× as likely to be in a Circle on their topic (90% range 1.95× to 2.90×) | First key |
| Format | In-person Circles show 1.4× the membership rate only because they're bigger (13.3 vs 9.5 members) | Second key, as a rule |
| Posts, chat, recency, engagement | Four views of whether a Circle is alive | Health |
| Tags | Tag-only matches: 1.05× (0.79× to 1.32×) | Not used |
| Post text | 15 sentences shared across all Circles | Not used |
| Job, industry, bio, location | Circles have no industry, job, or location, and their text is templated. Members in the same industry are 0.90× as likely to share a Circle as members in different industries (0.75× to 1.06×) | Not used |

`python scripts/design_numbers.py` reproduces these numbers.

## Judgment calls

Nothing in the data settles these, so each is a reasoned choice. The first four were each tested at six values across the range shown, one at a time (`tests/test_judgment_calls.py`). All four scenarios pass at every value, and at least 99 of 100 members keep the same Circles on their own topics. What moves is the lower slots.

| Setting | Value | Why | Scenarios pass across |
|---|---|---|---|
| Inactive cutoff | 45 days | One and a half missed monthly meetings | 21 to 226 days, with identical lists. No Circle was last active in that gap |
| Recency half-life | 15 days | Half a meeting cycle, so recency fades to an eighth by the cutoff | 1 to 365 days |
| "Enough" level | 75th percentile | At the median, half of all Circles would get full credit and health couldn't separate them. At the max, one outlier would set the bar | 1st to 99th percentile |
| Comment weight | 2× | A reply takes more effort than a tap, and 2 is the smallest step up | 0× to 100× |
| Default limit | 5 | Each Circle is a monthly commitment, so a short list is easier to choose from | Doesn't affect the ranking |

## Tradeoffs

- **In-person Circles rank after ones she can surely attend.** Circles have no location. If in-person Circles were spread across cities the way members are, the chance one is in her city would be 13%. At that value an in-person Circle never outranks an online one, so the rule needs no tuned number. The cost: user 15 gets the quieter online #37, not the thriving in-person #13.
- **Lower slots look alike across members.** Below her topics there's no personal signal, so #39 appears in 89 of 100 lists. That would crowd demand onto a few small, capped groups.
## Production scale

- **Speed.** Precompute health with a scheduled job. Index Circles by topic, so a request fetches only Circles on her topics plus a short list of the healthiest others. Cache lists per member.
- **Tuning.** Log what each member was shown, where it sat in her list, and what she joined, since memberships alone are biased toward whatever the app showed before. Then learn the judgment calls from joins and 30-day retention, and A/B test them.
- **Location.** Add Circle locations and compare metro areas: same metro counts as attendable, another metro is filtered out, and an unknown location keeps today's rule.
- **Demand.** Rotate the lower slots among healthy Circles with open seats.
- **Longer lists.** One per topic suits five slots but is strict: user 7's healthiest leadership Circle, #1, first appears at position 23. Past five, allow a second Circle on her own topics before unrelated ones.
- **Text.** Once descriptions and posts are real, use text similarity to find duplicates and to suggest topics from a member's bio. A suggestion uses only her own words, never infers gender, ethnicity, or other identity from a name or photo, says it's based on her profile, and counts less than a topic she chose.
