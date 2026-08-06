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
- [x] Sprint 7: pulizia deterministica e osservazioni di mercato trasparenti
- [x] Sprint 7: statistiche, outlier e confidence del mercato
- [x] Sprint 7: trend storici e svalutazione con requisiti di confidenza
- [x] Sprint 8: confronto deterministico dei percorsi nuovo e usato
- [x] Sprint 8: valore protetto, rischio, rivendita e costo di possesso
- [x] Sprint 8: break-even numerico e raccomandazioni spiegabili
- [x] Sprint 9: memoria utente privata con inventario e storico decisioni
- [x] Sprint 9: wishlist contestuale deterministica e copertura attrezzatura
- [x] Sprint 9: template versionati, storage atomico e validazione privacy

---

# VERSIONE 0.5 — Dashboard

Obiettivo:
Visualizzare i risultati.

Task:

- [ ] Google Sheets
- [ ] grafici
- [ ] KPI
- [ ] filtri
- [x] Sprint 10: dashboard locale read-only con catalogo completo
- [x] Sprint 10: ricerca, filtri, dettagli e confronto prodotti
- [x] Sprint 10: provider dati locale e demo con API privacy-safe

---

# VERSIONE 0.6 — Notifiche

Task:

- [ ] Telegram
- [ ] Email
- [ ] Digest giornaliero

---

# VERSIONE 1.0

Sistema completamente funzionante.
# Sprint 12 — Notification center and contextual assistant (completed)

- Local deterministic notifications with delivery state and deduplication.
- Optional contextual dashboard assistant using allowlisted structured data.
- Privacy-safe assistant history disabled by default and secured local APIs.
# Sprint 11 — Universal live radar pipeline (completed)

- Source-neutral JSON feed, RSS/Atom, file-import, and manually supplied URL adapters.
- Relevant-only live listing persistence with privacy-safe description storage.
- Recoverable radar runs, source health summaries, and local dashboard integration.
- Dedicated marketplace discovery remains behind connector-specific terms review.
