---
name: alex-oo-signal-csv
version: 0.1.0
description: |
  Generate Option Omega Custom Signals Tester CSV files from any signal source — chat-described trades, paired entries/exits, TradeBlocks block trade data, datelist outputs, or filtered backtest results. Auto-selects the right OO format option (1: entry times only, 2: entry+exit times, 3: entry+strikes, 4: full leg control) based on what data the user provides. Saves to vault/_Outputs/OO-Signals/ with a per-signal README documenting source and methodology; mirrors to a by-block folder when the signal references a specific TB block. Use whenever the user wants to feed signals into Option Omega's Custom Signals Tester — e.g. "create an OO signal CSV", "build an entry times file", "make a custom signal", "pair these entries with those exits", "generate OO signal from block X", "turn this analysis into an OO signal". Don't write ad-hoc OO CSVs by hand — the strict format rules, format-option inference, and dual-write convention all live here, and getting any of them wrong silently changes what OO simulates.
---

# alex-oo-signal-csv

Generate **Option Omega Custom Signals Tester** CSV files from any signal source — chat-described trades, paired entries/exits, TradeBlocks block trade data, datelist outputs, or analysis tables.

The Custom Signals Tester is OO's import path for "do exactly these trades" backtesting. It accepts four CSV shapes depending on how much of the trade you want to specify in the file versus the UI. The bulk of this skill is **picking the right shape from the user's phrasing** and **writing the file in a form OO will actually accept** — its parser is strict and rejects quoted fields, alternate datetime formats, or missing headers.

## What this skill produces

For each invocation:

1. A `.csv` file in OO Custom Signals Tester format.
2. A `README.md` documenting source, methodology, format option chosen, and the OO UI settings to combine with.

Both files land in **`vault/_Outputs/OO-Signals/_all/<YYYYMMDD>-<descriptor>/`** (chronological catch-all). If the signal references a specific TB block, **also mirror** to `vault/_Outputs/OO-Signals/by-block/<block-id>/<YYYYMMDD>-<descriptor>/` — same content, full copy (not symlink, since OneDrive sync mangles symlinks).

## OO format options — pick the simplest one that fits the user's data

OO supports four CSV shapes. Don't add columns the user didn't ask for, and don't drop columns OO needs. **Match the user's phrasing.**

| Option | Required columns | When to use |
|---|---|---|
| **1. Entry times only** | `OPEN_DATETIME` | User has a list of when to enter; structure + exit rules go in OO UI |
| **2. Entry + exit times** | `OPEN_DATETIME, CLOSE_DATETIME` | Paired entries + exits; structure goes in OO UI |
| **3. Entry times + strikes** | `OPEN_DATETIME, STRIKE` | Entry list with strike override; structure goes in OO UI |
| **4. Full leg control** | `OPEN_DATETIME, CLOSE_DATETIME, BUY_SELL, CALL_PUT, STRIKE, EXPIRATION, QUANTITY` | Reproducing a specific multi-leg trade (one row per leg, all legs share open/close) |

### Strict formatting rules (OO will reject otherwise)

- Headers exactly as shown above — capitalized, underscored, unquoted, comma-separated, no surrounding whitespace.
- `OPEN_DATETIME` / `CLOSE_DATETIME`: `YYYY-MM-DD HH:MM` (24-hour, no seconds).
- `EXPIRATION`: `YYYY-MM-DD`.
- `BUY_SELL`: `B` or `S` only.
- `CALL_PUT`: `C` or `P` only.
- `STRIKE`: integer or decimal, no trailing zeros (`6855`, not `6855.0`).
- `QUANTITY`: positive integer.
- **No quoting** on headers or values — OO rejects `"..."`-wrapped fields. This contradicts the CLAUDE.md global CSV rule about quoting comma-containing fields; OO's rule wins here because the rest of the project never reads these files.
- LF line endings. UTF-8 without BOM is safest — OO's parser may not strip BOM.
- No trailing blank line, no header-comment lines.

### Format inference — map user phrasing → option

| User says (or implies)… | Option |
|---|---|
| "entry times only" / "list of dates" / "just open times" / "datelist" / no strikes or exits mentioned | **1** |
| "pair entries with exits" / "open and close" / "entry and exit datetimes" / "matched to exit log" | **2** |
| "entries with strike X" / "entry times + strikes" / "datetime + strike list" | **3** |
| User describes legs (B/S, C/P, strikes, expirations) / "full trade" / "replay this trade" / multi-leg structure / screenshot of an OO trade row | **4** |

**Ambiguous case**: ask the user. The wrong option doesn't fail loudly — it silently changes what OO simulates. Better to clarify than guess.

**Mismatched case**: if the user says "entry times only" but also volunteers strikes and exits, ask whether they really want Option 1 (and want OO to ignore the extra info) or actually want a richer option.

## Data sources

Four common sources. Identify which one applies, then gather data accordingly.

### Source A: Chat description (single trade)

User pastes a screenshot or describes legs in chat. Parse the structure directly from their message. This is **almost always Option 4** because the user is reproducing a specific trade.

Required to extract: open datetime, close datetime, every leg's BUY_SELL / CALL_PUT / STRIKE / QUANTITY, and the EXPIRATION.

### Source B: TB analytics DB (single trade or batch)

User points at a TB block. Pull from `trades.trade_data` via `mcp__tradeblocks__run_sql`:

```sql
SELECT date_opened, time_opened, date_closed, time_closed,
       strategy, legs, num_contracts, dte
FROM trades.trade_data
WHERE block_id = '<block-id>'
  AND date_opened BETWEEN '<from>' AND '<to>'
ORDER BY date_opened, time_opened
```

The `legs` column is OO's pipe- or `/`-separated leg string. Parse it into individual rows. The expiration date is `date_opened + dte` calendar days (verify against the leg string if a date is embedded).

### Source C: Analysis output (CSV/table from another skill)

User points at a TB analysis output — datelist CSV, paired-trades table, filter result, etc. Read the file with the `Read` tool. Map its columns to OO's columns based on what's present:

| File column | OO column |
|---|---|
| `date` / `entry_date` / `date_opened` | `OPEN_DATETIME` (combine with the user-specified time, or 09:32 default if not specified) |
| `exit_date` / `date_closed` | `CLOSE_DATETIME` |
| `strike` / `strike_price` | `STRIKE` |
| `expiration` / `expiry` | `EXPIRATION` |
| `side` / `bs` | `BUY_SELL` (`B`/`S`) |
| `right` / `cp` | `CALL_PUT` (`C`/`P`) |
| `qty` / `contracts` | `QUANTITY` |

If the file has more columns than OO needs, drop the extras. If it has fewer, ask the user how to fill the gaps.

### Source D: Paired entries from another trade's exits

User wants to enter trades at the exact times some other trade exited. Pull exit times via SQL:

```sql
SELECT date_closed, time_closed
FROM trades.trade_data
WHERE block_id = '<block-id>'
  AND date_closed BETWEEN '<from>' AND '<to>'
ORDER BY date_closed, time_closed
```

Format each as `<date> <HH:MM>` and write into `OPEN_DATETIME`. This is **Option 1** (entry times only) unless the user pairs with their own exits too (Option 2).

## Filename and folder conventions

### Filename

`<YYYYMMDD>-<descriptor>-OO-signal.csv`

- `YYYYMMDD` = the **signal generation date** (today), not the trade dates. Different signals built from the same data on different days should be distinguishable.
- `descriptor` = lowercase, hyphen-separated, ASCII. Pull terms from: block id, trade structure, format option, methodology. Aim for self-describing but under 80 chars.

Examples:
- `20251010-spx-call-fly-21d-6815-6855-6895-OO-signal.csv`
- `20260326-block-20260319-sam-port-exits-as-entries-OO-signal.csv`
- `20260420-slimp-tuesday-09-32-entries-OO-signal.csv`

### Folder structure

```
vault/_Outputs/OO-Signals/
├── README.md                            (index — Dataview-powered, see Index README below)
├── _all/                                (chronological catch-all — every signal lives here)
│   └── <YYYYMMDD>-<descriptor>/
│       ├── signal.csv                   (the actual upload file)
│       └── README.md                    (source, methodology, OO settings)
└── by-block/                            (block-tied signals organized by block id)
    └── <block-id>/
        └── <YYYYMMDD>-<descriptor>/
            ├── signal.csv               (full copy, same content)
            └── README.md                (full copy, same content)
```

**Rules:**
- Always write to `_all/`.
- ALSO write to `by-block/<block-id>/` if the signal references a specific TB block (Sources B, D, or sometimes C). Block-id is the folder name as it appears in TB root.
- Ad-hoc signals not tied to a block (Source A typically) go in `_all/` only.
- Use **full copies**, not symlinks (OneDrive sync doesn't preserve symlinks).
- If the `_Outputs/OO-Signals/` folder doesn't exist yet on first invocation, create it along with the top-level `README.md` index.

### Top-level `_Outputs/OO-Signals/README.md` (create once, leave alone)

```markdown
---
type: index
tags: [oo-signals, index]
---

# OO Signals — Index

Every Option Omega Custom Signals Tester CSV generated by `alex-oo-signal-csv`. Source of truth = the per-signal README in each subfolder.

## Recent signals

\`\`\`dataview
TABLE WITHOUT ID
  link(file.folder, regexreplace(file.folder, ".*/", "")) AS Signal,
  format AS "Option",
  source AS Source,
  block AS Block,
  rows AS Rows,
  generated AS Generated
FROM "vault/_Outputs/OO-Signals/_all"
WHERE type = "oo-signal"
SORT generated DESC
\`\`\`
```

### Per-signal `README.md`

```markdown
---
type: oo-signal
format: 4                          # 1 / 2 / 3 / 4
source: chat                       # chat / block / file / paired-exits
block:                             # block-id if applicable, else empty
rows: 3                            # row count in the CSV (excluding header)
generated: 2026-05-10
---

# <Signal name>

**Format:** Option <N> — <name>
**Source:** <chat description / block <id> / file <path> / paired-from-<block>>
**Rows:** <count>
**Datetime span:** <first OPEN_DATETIME> → <last CLOSE_DATETIME or OPEN_DATETIME>

## Methodology / filters

<Free text. What filters or criteria produced this signal. From the user's description verbatim where possible.>

## OO UI settings to combine with

<What the user needs to set in OO UI alongside this CSV upload.
- Option 1: ticker, strategy template, position-size, exit rules
- Option 2: ticker, strategy template, position-size
- Option 3: ticker, leg structure (only strike comes from CSV)
- Option 4: ticker only — everything else comes from the CSV>

## Signal contents (first 5 rows)

\`\`\`csv
<paste first 5 lines of signal.csv including header>
\`\`\`
```

## Workflow

1. **Identify source** (A/B/C/D) from the user's request.
2. **Infer format option** (1/2/3/4) from phrasing. Ask if ambiguous.
3. **Gather data** — parse chat, run SQL, or read file depending on source.
4. **Normalize datetimes** — `YYYY-MM-DD HH:MM` (24-hour, no seconds, no quoting).
5. **Generate descriptive filename**.
6. **Create the signal directory** under `_all/<YYYYMMDD>-<descriptor>/`.
7. **Write `signal.csv`** and `README.md` to that directory.
8. **If block-tied**, mirror both files to `by-block/<block-id>/<YYYYMMDD>-<descriptor>/`.
9. **Report the final paths** to the user along with any OO UI settings they'll need (ticker, strategy template, etc.).

## Worked examples

### Example 1 — Multi-leg trade from chat (Source A, Option 4)

User: "Build an OO signal CSV for this trade: SPX call fly, BTO 1 6815C @ 48.25, STO 2 6855C @ 43.70, BTO 1 6895C @ 20.85, all Oct 31 2025 expiry, opened 09:32, closed 15:59 on Oct 10 2025."

Parse → Option 4, 3 leg rows, single trade.
Filename: `20251010-spx-call-fly-21d-6815-6855-6895-OO-signal.csv`.
Not block-tied → `_all/` only.

CSV:

```csv
OPEN_DATETIME,CLOSE_DATETIME,BUY_SELL,CALL_PUT,STRIKE,EXPIRATION,QUANTITY
2025-10-10 09:32,2025-10-10 15:59,B,C,6815,2025-10-31,1
2025-10-10 09:32,2025-10-10 15:59,S,C,6855,2025-10-31,2
2025-10-10 09:32,2025-10-10 15:59,B,C,6895,2025-10-31,1
```

### Example 2 — Entry times only from a datelist (Source C, Option 1)

User: "Build an entries-only OO signal — open at 09:35 on every date in `entry_dates.csv`."

Read the file → list of dates. Combine each with `09:35`.

CSV:

```csv
OPEN_DATETIME
2026-01-05 09:35
2026-01-12 09:35
...
```

### Example 3 — Paired entries from another block's exits (Source D, Option 1)

User: "Generate a signal that opens trades at the exact times block `20260319 - Sam Port` exited its trades between Feb and March."

```sql
SELECT date_closed, time_closed
FROM trades.trade_data
WHERE block_id = '20260319 - Sam Port'
  AND date_closed BETWEEN '2026-02-01' AND '2026-03-31'
ORDER BY date_closed, time_closed
```

Format each row as `OPEN_DATETIME`. Block-tied → write to both `_all/` and `by-block/20260319 - Sam Port/`.

## Edge cases and gotchas

- **Times with seconds**: OO format is `HH:MM`. Truncate (don't round) — `09:32:45` → `09:32`. Round only if the user says "round."
- **AM/PM input**: convert to 24-hour. `9:32 AM` → `09:32`; `3:59 PM` → `15:59`. Missing AM/PM and unclear context — ask.
- **Year-ambiguous dates**: `Oct 31` without a year — infer from open date; if still ambiguous, ask.
- **Time zone**: OO assumes ET; don't include time zone in the CSV.
- **0 DTE**: `EXPIRATION` = `OPEN_DATETIME` date. Same `YYYY-MM-DD` on both.
- **Multi-day trades**: `CLOSE_DATETIME` date later than `OPEN_DATETIME` date is fine; OO supports it.
- **Leg ordering** (Option 4): no order required by OO. Group consecutive rows by trade (legs sharing open/close stay adjacent) for human readability.
- **Numeric strikes**: integer preferred (`6855`). Decimals OK if the strike actually has a fraction (`5587.5`). No trailing zeros (`6855` not `6855.0`).
- **OO ticker is set in UI**: don't add a ticker column.
- **No quoting on values, ever**: OO rejects `"..."`-wrapped fields even for fields without commas.

## What this skill does NOT do

- **No market-data validation**: don't query `market.option_chain` to check that strikes/expirations exist. The user has vetted the trade structure; just write the CSV.
- **No backtesting**: this skill writes the signal file. OO runs the backtest on upload. Reporting OO's results back is a different skill.
- **No commission or P/L math**: OO computes those from the simulation. The CSV is purely structural.
- **No ticker translation**: SPX↔SPXW lives in the OO UI, not the file.
