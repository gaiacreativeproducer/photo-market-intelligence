# eBay Browse API setup

Photo Market Intelligence uses the official eBay Browse API. It does not scrape eBay pages, authenticate eBay users, bid, or purchase.

1. Create or open an application under **Application Keys** in the eBay Developers Program.
2. Copy the Sandbox App ID (Client ID) and Cert ID (Client Secret) into local environment variables:

   ```sh
   export PMI_EBAY_CLIENT_ID="your-sandbox-client-id"
   export PMI_EBAY_CLIENT_SECRET="your-sandbox-client-secret"
   export PMI_EBAY_ENVIRONMENT="SANDBOX"
   ```

3. Run the conservative connection check:

   ```sh
   python3 scripts/test_ebay_connection.py
   ```

4. Copy the disabled `EBAY_BROWSE` example from `data/templates/radar_sources.example.json` into `data/user/radar_sources.json`, then set `enabled` to `true`.
5. Run one source refresh with `python3 -m src.radar.scheduler --once --source ebay-it`, or use **Aggiorna offerte eBay** in a ProductWorkspace.

For the approved future six-hour cadence, use the existing scheduler with `python3 -m src.radar.scheduler --interval-minutes 360 --source ebay-it` under the deployment's process supervisor.

Supported V1 marketplaces are `EBAY_IT`, `EBAY_DE`, `EBAY_FR`, `EBAY_ES`, and `EBAY_GB`. The default query limit is 50 and the safe maximum is 200. A future recurring deployment should use the existing scheduler at a six-hour cadence.

Production uses the same code with `PMI_EBAY_ENVIRONMENT=PRODUCTION`, but eBay may require separate Production Buy API approval. A Production keyset alone may not enable Browse access.

Never commit `.env`, credentials, access tokens, or Authorization headers. Credentials and tokens are not written to project data. Seller usernames are not persisted.
