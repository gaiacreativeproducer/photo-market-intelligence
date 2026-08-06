# Photo Market Intelligence

Photo Market Intelligence is an early-stage system for finding, normalizing, and evaluating photography and video equipment listings. Its goal is to compare offers with reference market data, score each opportunity, retain a traceable price history, and notify users only when a listing is genuinely interesting.

The project is designed as a decision-support tool. It does not purchase products or contact sellers.

> **Project status:** foundations are complete and the initial product database is the current focus. The application modules are planned but not yet implemented; the repository is not yet a runnable product.

## Purpose

The system is intended to automate the following workflow:

1. Search public and authorized sources for photography and video equipment listings.
2. Identify each product's brand, model, version, and price.
3. Compare the listing with reference and historical prices.
4. Assign a score and a clear decision.
5. Store normalized, deduplicated results in automatically updated data files.
6. Send a notification only when an opportunity crosses the configured threshold.

Initial sources identified in the project specification include the official eBay API, Google Programmable Search, indexed results from Subito and JuzaPhoto, MPB, RCE Foto, and E-Infinity. Integrations must favor official APIs, feeds, indexed searches, and public sources; fragile scraping or access that conflicts with a site's terms is outside the project principles.

## Architecture overview

Photo Market Intelligence follows a data pipeline architecture:

```text
Listing sources
      │
      ▼
Radar ── search, normalize, deduplicate
      │
      ▼
Decision Engine ── identify, estimate, score, explain
      │
      ├──► CSV data and price history
      ├──► Google Sheets dashboard
      └──► Email / Telegram notifications above threshold
```

CSV files are the initial source of truth. Google Sheets is planned as a dashboard, not as the primary database.

The decision engine combines objective rules, historical data, market comparisons, AI-assisted analysis, and wishlist priorities. Its output is expected to include a score from 0 to 100, estimated market value, target price, negotiation margin, decision, short rationale, and confidence level.

The initial scoring weights are:

| Factor | Weight |
| --- | ---: |
| Price relative to market | 40% |
| Condition and warranty | 20% |
| Product liquidity | 15% |
| Source reliability | 10% |
| Strategic wishlist interest | 10% |
| Creative or collectible value | 5% |

Scores map to four initial decisions: `PRENDERE` (85–100), `TRATTARE` (70–84), `MONITORARE` (50–69), and `PASSARE` (below 50). The decision-engine design also defines `REVISIONE MANUALE` for cases such as an unrecognized product.

## Repository structure

```text
photo-market-intelligence/
├── config/                 # Planned runtime configuration
├── data/
│   └── products.csv        # Initial product reference database (currently empty)
├── docs/
│   ├── PROJECT_SPEC.md     # Scope, principles, data model, and modules
│   ├── ROADMAP.md          # Versioned delivery plan
│   └── DECISION_ENGINE-md  # Decision-engine rules and responsibilities
├── prompts/
│   └── 001_generate_products_database.md
│                              # Requirements for generating the initial dataset
├── scripts/                # Planned project scripts
├── src/
│   ├── dashboard/          # Google Sheets export and visualization module
│   ├── engine/             # Market valuation, scoring, and decisions
│   ├── notifier/           # Email and Telegram notifications
│   ├── radar/              # Listing discovery and normalization
│   └── utils/              # Logging, dates, currency, deduplication, configuration
├── tests/                  # Automated tests
├── LICENSE                 # MIT License
└── requirements.txt        # Python dependencies
```

Empty directories represent the planned architecture and do not yet contain working modules.

The complete data model also calls for:

- `data/wishlist.csv` — products and queries to monitor;
- `data/listings.csv` — normalized listings, scores, decisions, and state;
- `data/price_history.csv` — dated reference and observed prices.

These files are planned and have not yet been created.

## Development workflow

Development follows the version sequence in the roadmap. Work should remain within the active milestone and preserve the documented contracts between data files and modules.

For the current repository state:

```bash
git clone <repository-url>
cd photo-market-intelligence
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

There is no application entry point or documented test command yet. Until implementation begins, changes should be validated against the project specification, the decision-engine rules, and the CSV schemas. When code is introduced, it should include proportionate automated tests under `tests/`.

Recommended change cycle:

1. Confirm the relevant roadmap milestone and specification section.
2. Keep data schemas and module boundaries consistent with the documentation.
3. Implement a small, focused change with tests where applicable.
4. Verify that credentials, generated data, and local configuration are not committed.
5. Update documentation when a contract, rule, threshold, or milestone changes.

## Roadmap

| Version | Focus | Status |
| --- | --- | --- |
| 0.1 | Repository, environment, structure, and core documentation | Complete |
| 0.2 | Product, wishlist, listing, and price-history CSV databases | In progress |
| 0.3 | Listing radar using Google Programmable Search, eBay API, MPB, and RCE; deduplication | Planned |
| 0.4 | Model/version recognition, price estimation, scoring, rationale, and confidence | Planned |
| 0.5 | Google Sheets dashboard, charts, KPIs, and filters | Planned |
| 0.6 | Telegram, email, and daily digest notifications | Planned |
| 1.0 | Fully functioning system | Planned |

See [the detailed roadmap](docs/ROADMAP.md) for the milestone checklist.

## Current project status

The repository currently provides:

- the project specification and architectural principles;
- the decision-engine design and objective safeguards;
- the versioned roadmap;
- the planned source-module directory structure;
- Python dependency declarations;
- an empty `data/products.csv` placeholder and a prompt defining its initial dataset requirements.

No radar integrations, decision-engine implementation, dashboard, notifier, or automated tests are present yet. The next documented milestone is version 0.2: build `products.csv`, `wishlist.csv`, `listings.csv`, and `price_history.csv`.

## Coding principles

Contributions should preserve the principles established in the project specification:

- Keep code readable, modular, and testable.
- Treat CSV data as the initial database and Google Sheets as a presentation layer.
- Prefer official APIs, feeds, indexed searches, and public sources.
- Avoid fragile scraping and respect source terms.
- Deduplicate every listing before evaluation or notification.
- Keep critical rules and stable AI-proposed changes traceable.
- Make uncertainty visible; incomplete or unrecognized results require explicit handling.
- Never automate purchases or seller contact.
- Never commit API keys. Store secrets in `.env` and keep that file out of version control.

Objective validation rules take precedence over AI analysis: duplicate URLs are discarded, missing prices are marked incomplete, invalid prices are discarded, and unrecognized products go to manual review.

## Contributing

The project is in an early design and data-foundation phase. Before contributing, read:

- [Project specification](docs/PROJECT_SPEC.md)
- [Decision engine](docs/DECISION_ENGINE-md)
- [Roadmap](docs/ROADMAP.md)

To propose a change:

1. Choose an open task from the current roadmap milestone.
2. Create a focused branch and keep the change limited to one concern.
3. Follow the documented schemas, boundaries, scoring rules, and safety constraints.
4. Add or update tests for implemented behavior when applicable.
5. Update the relevant documentation if the change affects a public contract or roadmap item.
6. Open a pull request describing the problem, the approach, validation performed, and any data or security implications.

Changes that introduce a new source should document how it is accessed and confirm that the approach is public, authorized, and maintainable. Changes to stable decision rules or thresholds must be reviewable and traceable.

## Future modules

The documented module plan includes:

- **Radar (`src/radar`)** — retrieve listings, normalize source data, and deduplicate results.
- **Decision engine (`src/engine`)** — recognize products, estimate market value, calculate scores, explain decisions, and report confidence.
- **Dashboard (`src/dashboard`)** — export results to Google Sheets and provide charts, KPIs, and filters.
- **Notifier (`src/notifier`)** — deliver Telegram, email, and daily digest notifications for qualifying opportunities.
- **Shared utilities (`src/utils`)** — logging, dates, currency handling, deduplication, and configuration.

The decision engine is also expected to support dynamic market parameters such as average and median price, recent minimum price, deal threshold, liquidity, depreciation trend, negotiation probability, accessory value, wear penalties, and source reliability.

## License

Photo Market Intelligence is available under the [MIT License](LICENSE).
