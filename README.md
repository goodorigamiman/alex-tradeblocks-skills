# alex-tradeblocks-skills

Custom agent skills for analyzing Option Omega backtests and options trading portfolios.

## Skills

| Skill | Description |
|-------|-------------|
| `entry-filter-pareto` | Pareto chart comparing all candidate entry filters side-by-side. Shows Avg ROR vs % of baseline Net ROR retained. |
| `threshold-analysis` | Generic threshold sweep for any trade or market field (SLR, VIX, premium, gap, etc.) with interactive chart. |
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
- Market data (SPX/QQQ daily OHLCV + VIX context) for regime analysis
- Optional: `MASSIVE_API_KEY` for intraday data and trade replay

## Usage

Invoke skills with `/alex-tradeblocks:<skill-name>` or let Claude auto-detect based on your request.

## License

MIT
