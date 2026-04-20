# dev-create-datelist

Generate Option Omega-compatible datelists (ISO `YYYY-MM-DD`, comma-wrapped) from the entry-filter data of a block. The skill takes one or more filter expressions and emits **two** copy-paste-ready code blocks:

1. **Specific Dates (whitelist)** — AND-intersection of every filter. Paste into OO's "Specific Dates" slot to tell the strategy "only run on these dates."
2. **Blackout Dates (per filter)** — the inverse of each filter, listed independently. Paste into OO's "Blackout Dates" slot to tell the strategy "skip any date listed here."

## Why two blocks?

OO's two datelist slots have opposite semantics, and conflating them silently breaks the strategy:

| OO slot | Logic | Source of truth in this skill |
|---|---|---|
| Specific Dates | AND — trade must be on a listed date to run | Single label, single dates row (intersection of all filters) |
| Blackout Dates | OR — any match vetoes the trade | One label + dates row per filter (overlap allowed) |

If you pasted per-filter lists into the Specific Dates slot, OO would treat the whole thing as a giant OR (trade runs if any row matches), which is the opposite of what you want. If you pasted an AND-intersection into Blackout, you'd only block the rare days where every filter failed simultaneously — also wrong. Two blocks, two slots, one correct outcome.

## Philosophy: drop filters by deleting rows

The blackout block is deliberately per-filter so you can iterate without re-running the skill:

```
blackout dates: VIX_IVP <= 92.032 gen 20260413.
,2022-10-17, ,2024-04-22, ...

blackout dates: VIX9D_VIX_Ratio >= 0.807 gen 20260413.
,2024-10-14, ,2024-10-21, ...

blackout dates: margin_per_contract <= 234 gen 20260413.
,2022-08-22, ,2022-10-10, ...
```

Want to see how the strategy performs without the margin filter? Delete those two lines and paste the rest. No re-run, no skill invocation, no mental intersection math — just remove the rows you don't want active. Because blackouts are OR-combined in OO, subtracting a filter is exactly equivalent to deleting its row.

The specific-dates block can't work that way: dropping one filter from an intersection requires recomputing the intersection of the remaining filters (a date might satisfy the dropped filter but fail the rest, so it appears or vanishes from the keep set in non-obvious ways). To drop a filter from the whitelist, re-invoke the skill without that filter.

## The `gen` date tag

Every label includes `gen YYYYMMDD`. That date is **the last `date_opened` in the block's `entry_filter_data.csv`** — not today's date and not when the skill was run. It tells you exactly how fresh the underlying trade set was when the list was generated.

If you paste this datelist into OO three months from now, the `gen` tag makes it obvious whether to regenerate (new trades have been added since) or paste as-is (nothing new yet). No need to remember when you last ran the skill — the coverage date is baked into the label.

## Label format

| Block | Label |
|---|---|
| Specific | `specific dates: {f1} + {f2} + ... gen {YYYYMMDD}, start dates.` |
| Blackout | `blackout dates: {filter_expression} gen {YYYYMMDD}.` |

- The datelist type (`specific dates:` / `blackout dates:`) is always part of the label so a copied fragment self-describes — there's never ambiguity about which OO slot it belongs in.
- `{filter_expression}` is the verbatim condition as the user wrote it (e.g., `SLR >= 0.47`, `VIX9D_VIX_Ratio >= 0.807`), not an internal column code.
- The specific block carries `start dates` to match OO's convention (open-date-based filtering); the blackout block drops it because blackout is inherently opened-date-based.

## Date format rules

1. ISO `YYYY-MM-DD`.
2. Every date wrapped by commas on both sides, including the first and last: `,2026-01-03,`.
3. Dates separated by a space: `,2026-01-03, ,2026-01-10,`.
4. One continuous line per dates block — no line breaks inside the sequence (OO won't parse them).

## Summary table (printed before the code blocks)

Every run emits a summary table as the first output, so you can see the retention picture before deciding to copy anything. Columns:

- **Keep / Blackout** — trade counts (Blackout excludes rows where the filter column was NULL — those are reported as "data gap," not as failures).
- **Net ROR** — sum of `rom_pct` over the keep subset, expressed as % of baseline Net ROR. Baseline row = 100.0% by definition.
- **Avg ROR** and **Avg ROR +pts** — mean `rom_pct` of the keep subset, and the delta in percentage points versus the baseline row.
- **WR** and **WR +pts** — win rate of the keep subset, and the delta in percentage points versus baseline.

The first row is always **All Trades (baseline)** so every other row reads as "what this filter does relative to doing nothing." The last row is **All AND (specific dates)** — the whitelist that OO would actually run if you pasted the specific block.

## When to use

- You finished threshold analysis or a heatmap and have one or more filters you want to backtest in OO without modifying the strategy file.
- You want to A/B test filter combinations quickly — generate with N filters, then edit the blackout block to remove filters one at a time between OO runs.
- You want to share a datelist with someone else and need the label to self-document (filter criteria + data coverage date).

## Related skills

- `dev-entry-filter-analysis` — orchestrator that runs the full pipeline and typically invokes this skill as its final step. Use when you want a recommended filter list built for you.
- `dev-entry-filter-threshold-analysis` — find the optimal threshold for a single filter before generating a datelist.
- `dev-entry-filter-heatmap` — click cells to capture candidate filter expressions, then hand those expressions to this skill.
- `dev-entry-filter-build-data` — upstream. Produces the `entry_filter_data.csv` this skill reads.

## What NOT to do

- Don't paste the specific block into OO's Blackout slot (or vice versa). The type tag exists specifically to prevent this.
- Don't hand-AND the blackout rows into a single list — the whole point is that OR-veto lets you edit them individually.
- Don't re-run the skill just to drop one filter from the blackout set. Delete the two lines for that filter and paste the remainder.
- Don't trust the `gen` date as a "run date." It's the data coverage date — the actual generation time is when the skill was invoked, which may or may not be the same.
