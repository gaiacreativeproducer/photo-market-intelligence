# MVP Status

## Completed modules

Catalog, connectors, description intelligence, product recognition, market intelligence, decision and ownership engines, privacy-safe user memory, local dashboard and search, universal radar, local notifications, and the deterministic contextual assistant.

## Commands

```text
python3 src/main.py
python3 -m src.dashboard.server
python3 -m src.radar.scheduler --once
```

## Current capabilities and limitations

- Radar sources: JSON feed, RSS/Atom, CSV/JSON file import, and manually supplied URL records.
- Manual listings can be inserted through the local dashboard using URL, title, description, price, and source metadata.
- URL-only extraction and automatic Subito page reading are not implemented.
- eBay API integration is pending.
- The assistant is deterministic and uses existing structured local data only. No external AI is used.
- Dashboard and console are the only implemented notification channels. Email, Telegram, and macOS channels are inactive placeholders.
- The system does not contact sellers or make automatic purchases.

## Post-MVP priorities

Dedicated compliant marketplace connectors, official eBay integration, richer persisted market and decision views, and optional external channels with explicit configuration and privacy review.
