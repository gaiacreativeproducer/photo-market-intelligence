</> Markdown
# Photo Market Intelligence — Roadmap

# VERSIONE 0.1 — Fondamenta

## Ambiente

- [x] Repository GitHub
- [x] VS Code
- [x] Git
- [x] Python
- [x] Struttura cartelle

## Documentazione

- [x] PROJECT_SPEC.md
- [x] DECISION_ENGINE.md

---

# VERSIONE 0.2 — Database

Obiettivo:
Costruire il database prodotti.

Task:

- [ ] products.csv
- [ ] wishlist.csv
- [ ] listings.csv
- [ ] price_history.csv
- [x] Sprint 2: catalogo prodotti validato con produttori, attacchi e alias normalizzati

---

# VERSIONE 0.3 — Radar

Obiettivo:
Recuperare automaticamente annunci.

Task:

- [ ] Google Programmable Search
- [ ] eBay API
- [ ] MPB
- [ ] RCE
- [ ] deduplica
- [x] Sprint 3: astrazione comune e modello annunci normalizzato
- [x] Sprint 3: esecuzione indipendente, retry sicuri e deduplica connettori
- [x] Sprint 3: monitoraggio salute e persistenza incidenti
- [x] Sprint 3: connettore mock e proposte diagnostiche di riparazione

---

# VERSIONE 0.4 — Decision Engine

Obiettivo:
Valutare gli annunci.

Task:

- [ ] riconoscimento modello
- [ ] riconoscimento versione
- [ ] stima prezzo
- [ ] score
- [ ] motivazione
- [ ] confidence score
- [x] Sprint 4: fatti strutturati per condizioni, difetti, garanzia e accessori
- [x] Sprint 4: motore decisionale esplicito e spiegabile
- [x] Sprint 4: confronto deterministico nuovo-usato e confidence score
- [x] Sprint 5: analisi deterministica bilingue delle descrizioni
- [x] Sprint 5: estrazione di condizioni, accessori, documenti e difetti
- [x] Sprint 5: integrazione immutabile dei fatti negli annunci normalizzati
- [x] Sprint 6: riconoscimento deterministico di prodotto, versione e attacco
- [x] Sprint 6: ranking spiegabile, gestione ambiguità e annunci kit
- [x] Sprint 6: integrazione del catalogo normalizzato e degli alias

---

# VERSIONE 0.5 — Dashboard

Obiettivo:
Visualizzare i risultati.

Task:

- [ ] Google Sheets
- [ ] grafici
- [ ] KPI
- [ ] filtri

---

# VERSIONE 0.6 — Notifiche

Task:

- [ ] Telegram
- [ ] Email
- [ ] Digest giornaliero

---

# VERSIONE 1.0

Sistema completamente funzionante.
