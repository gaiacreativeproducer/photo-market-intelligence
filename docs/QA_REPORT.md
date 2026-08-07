# QA Automation Report

Date: 2026-08-07

Branch: `feature/product-workspace`

Browser: Playwright Chromium 151.0.7922.34

## Summary

The browser suite executes 54 serial, persona-oriented scenarios against a localhost-only dashboard and an isolated temporary runtime directory. The verified run completed with 53 passed, 1 failed, and 0 skipped scenarios. The failing scenario remains active so CI reports the product defect.

| Area | Result | Notes |
| --- | --- | --- |
| Search and catalog aliases | PASS | A7IV, A7 IV, ILCE-7M4, Sigma versions, partial/case/empty/rapid queries |
| Product workspaces | PASS | All 34 catalog pages, zero-offer state, offer actions, NEW/USED and same-segment comparisons |
| Manual listing entry | PASS | Recognition, extraction, validation, persistence, duplicate handling, immediate refresh |
| Manual product association | PASS | Ambiguity, assignment, reassignment, removal, fallback, identity preservation |
| Wishlist, inventory, decisions | PASS | Empty/populated states, safe links, private serial exclusion |
| Security and error handling | PASS | Host/Origin, URL credentials, malformed input/query, body limit, unsafe-looking text |
| Keyboard and mobile smoke | PASS | Panel focus restoration, keyboard comparison, critical mobile navigation |
| Coarse performance smoke | PASS | Home/search, 50-offer workspace, 200-record Annunci rendering |
| Annunci blank filters | FAIL | Empty numeric fields are sent as query values, API returns 400, UI raises a JavaScript exception |

## Scenarios executed

- New user: Home orientation, catalog search, zero-offer workspace, first-listing path.
- A7 IV buyer: NEW €1,595 and USED €1,200 with 60,000 shutter actuations, €395 / 24.8% comparison, honest ownership insufficiency, coherent conclusion.
- Ambiguous listing user: review queue, manual association, workspace move, reassignment, override removal, automatic fallback.
- Wishlist, inventory, and decision-history users: empty and populated states plus safe workspace navigation.
- Multi-offer user: replacement-ready checkbox selection, same-segment facts, NEW/USED ownership comparison, cross-currency refusal.
- Search-heavy user: aliases, model codes, version specificity, partial/case variants, nonexistent/empty/rapid searches.
- Error-prone and security users: invalid and hostile-looking input, duplicate listing, mutation protections, body limits.
- Keyboard-only and mobile users: primary controls, panels, focus restoration, offer selection, responsive critical paths.
- Performance smoke: generous local thresholds with deterministic 50- and 200-record fixtures.

## Blocker bugs

None preventing the QA harness from running or producing artifacts.

## Major UX issues

1. **Annunci filter submission breaks with untouched numeric fields.** Opening Annunci and selecting `Applica filtri` without entering prices sends blank `price_min` and `price_max` values. `/api/listings` responds with HTTP 400 and `openDataView` then reads `data.items.length`, producing `Cannot read properties of undefined`. The listing panel stops rendering instead of preserving results or displaying the structured API error.

Recommended priority: **P1**, because the default filter action creates an uncaught browser error in a primary navigation flow.

## Minor issues

- Generic Wishlist, Corredo, and Decisioni workspace links open a new tab because the shared link helper treats local product links as external. Navigation remains functional and safe, but the behavior is surprising for an internal action.
- The static HTML mixes Italian and English labels. This is not a functional blocker but makes the interface less consistent.

## Security and test observations

- Dashboard binding remains `127.0.0.1`; CI does not expose it publicly.
- Browser/API tests confirm invalid Host and Origin rejection, embedded-credential URL rejection, JSON/body limits, and unsupported mutation handling.
- Script-like and HTML-like listing text remains text; no unsafe `innerHTML` path was observed.
- Private inventory serial references do not appear in rendered inventory or product pages.
- Reports contain deterministic fixture data only. Runtime data under `data/user/` is never used.
- The Playwright dependency audit reports zero known vulnerabilities at installation time.

## Test-infrastructure observations

- The first draft used a fixed port and could connect to an unrelated pre-existing local server. The runner now allocates a free loopback port and fails if its child dashboard exits early.
- The suite runs with one worker because scenarios intentionally exercise a shared isolated runtime and stateful user journeys.
- On failure, Playwright retains screenshot, video, trace, console diagnostics, and safe request-failure summaries; the HTML report is always generated.

## Recommended next steps

1. Fix blank filter serialization or make the API ignore blank numeric query values, and render structured errors safely.
2. Rerun the unchanged failing scenario until the suite reaches 54/54.
3. Consider keeping internal workspace navigation in the same tab unless a new tab is an explicit UX decision.
4. Standardize visible interface language in a dedicated UX pass.
