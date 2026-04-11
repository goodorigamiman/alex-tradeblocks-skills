# alex-tradeblocks-skills

Custom agent skills for analyzing Option Omega backtests and options trading portfolios.

## Skills

| Skill | Description |
|-------|-------------|
| `alex-entry-filter-pareto` | Pareto chart comparing all candidate entry filters side-by-side. Shows Avg ROR vs % of baseline Net ROR retained. |
| `alex-threshold-analysis` | Generic threshold sweep for any trade or market field (SLR, VIX, premium, gap, etc.) with interactive chart. |
| `example-skill` | Placeholder skill demonstrating the correct SKILL.md format |

## Installation

### Via Marketplace

```
/plugin marketplace add goodorigamiman/alex-tradeblocks-skills
/plugin install alex-tradeblocks@alex-tradeblocks-skills
```

### Manual

Clone this repo and copy the `skills/` folders into `~/.claude/skills/`.

## Requirements

- [TradeBlocks MCP server](https://github.com/davidromeo/tradeblocks) running
- Option Omega CSV exports imported into blocks
- Market data API connection for OHLCV + VIX data (Massive.com, ThetaData, or CSV import)
- No dependency on other skill plugins — all skills are self-contained

## Usage

Invoke skills with `/alex-tradeblocks:<skill-name>` or let Claude auto-detect based on your request.

## Development

See [CLAUDE.md](CLAUDE.md) for the full dev workflow. In short:

1. Create `dev-<name>/SKILL.md` in your project's `.claude/skills/` — test as `/dev-<name>`
2. When ready, copy to `skills/alex-<name>/` in this repo (replace `dev-` with `alex-`)
3. Bump version in `plugin.json` + `marketplace.json`, commit, push
4. Update: `/plugin marketplace update alex-tradeblocks-skills`

## License

MIT
