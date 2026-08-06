</> Markdown
# Photo Market Intelligence — Project Spec

## Obiettivo

Creare un sistema automatico che:

1. cerchi annunci e offerte di attrezzatura fotografica e video;
2. riconosca marca, modello, versione e prezzo;
3. confronti ogni risultato con prezzi di riferimento;
4. assegni un punteggio;
5. salvi tutto in file aggiornati automaticamente;
6. invii una notifica solo per le occasioni realmente interessanti.

## Principi

- I dati devono aggiornarsi automaticamente.
- Google Sheets sarà una dashboard, non il database principale.
- Il database iniziale sarà composto da file CSV.
- Nessuno scraping fragile o contrario ai termini dei siti.
- Preferire API ufficiali, feed, ricerche indicizzate e fonti pubbliche.
- Ogni annuncio deve essere deduplicato.
- Nessuna notifica per risultati sopra soglia.
- Il codice deve essere leggibile, modulare e testabile.

## Fonti iniziali

- eBay tramite API ufficiale
- Google Programmable Search
- risultati indicizzati di Subito
- risultati indicizzati di JuzaPhoto
- MPB
- RCE Foto
- E-Infinity
- altri negozi aggiungibili in seguito

## File dati

### data/products.csv

Contiene il database dei prodotti:

- categoria
- brand
- modello
- versione
- attacco
- prezzo nuovo medio
- prezzo usato medio
- prezzo affare
- prezzo massimo acquisto
- liquidità
- interesse futuro
- valore creativo
- note

### data/wishlist.csv

Contiene i prodotti da monitorare:

- id
- query
- categoria
- brand
- modello
- fonte
- prezzo massimo
- priorità
- attivo

### data/listings.csv

Contiene gli annunci trovati:

- id
- data rilevazione
- fonte
- titolo
- url
- categoria
- brand
- modello riconosciuto
- versione riconosciuta
- prezzo
- valuta
- condizioni
- località
- venditore
- descrizione sintetica
- score
- decisione
- stato

### data/price_history.csv

Contiene lo storico prezzi:

- data
- prodotto
- fonte
- prezzo
- tipo prezzo
- condizioni
- url

## Moduli

### src/radar

Ricerca nuove offerte e normalizza i risultati.

### src/engine

Calcola valore di mercato, punteggio e decisione.

### src/notifier

Invia email o Telegram solo sopra soglia.

### src/dashboard

Esporta dati verso Google Sheets.

### src/utils

Funzioni condivise: log, date, valuta, deduplica, configurazione.

## Logica iniziale di valutazione

Lo score totale va da 0 a 100.

Pesi iniziali:

- prezzo rispetto al mercato: 40%
- condizioni e garanzia: 20%
- liquidità del prodotto: 15%
- affidabilità della fonte: 10%
- interesse strategico della wishlist: 10%
- valore creativo o collezionistico: 5%

Decisioni:

- 85–100: PRENDERE
- 70–84: TRATTARE
- 50–69: MONITORARE
- sotto 50: PASSARE

## Deduplica

Un annuncio è duplicato se:

- ha lo stesso URL;
- oppure stesso titolo normalizzato, prezzo e fonte;
- oppure stesso modello, prezzo, località e venditore entro 30 giorni.

## Sicurezza

- Le chiavi API non devono finire su GitHub.
- Devono stare in un file `.env`.
- Il file `.env` deve essere ignorato da Git.
- Nessuna automazione deve effettuare acquisti.
- Il sistema deve solo cercare, valutare e notificare.
