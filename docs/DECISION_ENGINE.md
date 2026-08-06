</> Markdown
# Decision Engine

## Obiettivo

Valutare ogni annuncio come opportunità reale, non solo in base al prezzo.

## Principio

Il sistema combina:

- regole oggettive;
- dati storici;
- confronto di mercato;
- analisi AI;
- priorità della wishlist.

L'AI può proporre nuovi parametri e nuove soglie sulla base dei dati osservati, ma ogni modifica stabile alle regole deve essere tracciabile.

## Regole oggettive

Queste regole non dipendono dall'AI:

- URL duplicato: scarta.
- Prezzo assente: risultato incompleto.
- Prezzo non valido: scarta.
- Prodotto non riconosciuto: invia a revisione.
- Acquisti automatici: vietati.
- Chiavi API: mai salvate nel repository.

## Parametri dinamici

Il sistema deve poter aggiornare automaticamente:

- prezzo medio;
- prezzo mediano;
- prezzo minimo recente;
- soglia affare;
- liquidità;
- trend di svalutazione;
- probabilità di trattativa;
- valore accessori;
- penalità per usura;
- affidabilità della fonte.

## Valutazione di un annuncio

Ogni annuncio deve essere valutato considerando:

- prezzo;
- condizioni;
- garanzia;
- fattura;
- numero di scatti;
- accessori;
- scatola e documentazione;
- anzianità dell'annuncio;
- domanda del prodotto;
- facilità di rivendita;
- trend di mercato;
- interesse strategico;
- valore creativo o collezionistico.

## Output

Il sistema deve restituire:

- score da 0 a 100;
- valore di mercato stimato;
- prezzo target;
- margine di trattativa;
- decisione;
- motivazione sintetica;
- livello di confidenza.

## Decisioni

- PRENDERE
- TRATTARE
- MONITORARE
- PASSARE
- REVISIONE MANUALE

## Ruolo dell'AI

L'AI deve:

- riconoscere modello e versione;
- interpretare la descrizione;
- stimare il valore degli accessori;
- rilevare anomalie;
- proporre soglie aggiornate;
- spiegare la decisione.

L'AI non deve:

- acquistare;
- contattare venditori;
- modificare regole critiche senza tracciamento;
- nascondere l'incertezza.
