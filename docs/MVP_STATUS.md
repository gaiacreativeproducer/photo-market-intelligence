# MVP Status

## Completed modules

Catalog, connectors, description intelligence, product recognition, market intelligence, decision and ownership engines, privacy-safe user memory, local dashboard and search, universal radar, the official eBay Browse connector, local notifications, and the deterministic contextual assistant.

## Commands

```text
python3 src/main.py
python3 -m src.dashboard.server
python3 -m src.radar.scheduler --once
```

## Current capabilities and limitations

- Radar sources: JSON feed, RSS/Atom, CSV/JSON file import, manually supplied URL records, and the official eBay Browse API.
- Manual listings can be inserted through the local dashboard using URL, title, description, price, and source metadata.
- URL-only extraction and automatic Subito page reading are not implemented.
- eBay Browse supports Sandbox and Production through environment configuration. Credentials and application tokens are environment-only and are never persisted.
- Production Buy API access may require separate approval from eBay even when Production credentials exist.
- eBay seller usernames and other unnecessary seller identity data are not stored. The connector cannot bid or purchase.
- The assistant is deterministic and uses existing structured local data only. No external AI is used.
- Dashboard and console are the only implemented notification channels. Email, Telegram, and macOS channels are inactive placeholders.
- The system does not contact sellers or make automatic purchases.

## Post-MVP priorities

Additional compliant marketplace connectors, richer persisted market and decision views, six-hour scheduled eBay refresh deployment, and optional external channels with explicit configuration and privacy review.
