# UPPilot - Gap analysis strategica

Data: 2026-06-28

Obiettivo: capire cosa manca nel panorama legal AI vicino a UPPilot, non cosa copiare.
La domanda guida non e' "quali feature hanno gli altri?", ma "quale carenza ricorre ovunque e
puo' diventare valore teorico e pratico per una piattaforma UPP local-first?".

## Sintesi brutale

Il mercato legal AI converge su tre promesse:

1. ricerca giuridica assistita;
2. drafting/summarization;
3. review di documenti con citazioni o fonti.

L'open source converge quasi sempre su:

1. chat/RAG su documenti;
2. Q&A con citazioni;
3. pipeline generiche di ingestion, embedding e retrieval.

Regolatori, linee guida giudiziarie e paper accademici insistono invece su:

1. supervisione umana;
2. logging/audit;
3. trasparenza;
4. controllo delle allucinazioni;
5. spiegabilita' e gestione del rischio.

Il buco sta proprio tra questi due mondi: quasi nessuno traduce trasparenza, controllo umano e
affidabilita' in una plancia processuale concreta per chi deve preparare una decisione.

La direzione differenziante per UPPilot e':

> passare da "assistente che produce una bozza" a "banco di lavoro probatorio-decisionale
> auditabile", dove ogni richiesta e ogni paragrafo nascono da una matrice verificabile:
> domanda, fatto, onere, prova, controprova, fonte, lacuna, scelta umana, motivazione, export.

In breve: non un altro Legal ChatGPT, non un altro RAG con citazioni. Una piattaforma che rende
visibile il lavoro mentale e processuale che normalmente resta implicito.

## Fonti consultate

### Prodotti e mercato

- Harvey: piattaforma AI per studi legali e imprese, orientata a ricerca, drafting, analisi e
  workflow legale. Fonte: https://harvey.ai/
- Lexis+ AI: ricerca conversazionale, drafting, summarization e analisi documentale in ambiente
  proprietario. Fonte: https://www.lexisnexis.com/en-us/products/lexis-plus-ai.page
- Thomson Reuters CoCounsel / Westlaw: AI legale per ricerca, document review, drafting e uso di
  contenuti professionali proprietari. Fonte:
  https://legal.thomsonreuters.com/en/products/cocounsel-legal
- Legora: workspace collaborativo per lavoro legale assistito da AI, con focus su documenti,
  drafting e team workflow. Fonte: https://legora.com/product

Pattern comune: ottimizzano produttivita' professionale, non costruiscono una rappresentazione
processuale auditabile della decisione giudiziaria.

### Open source e repository comparabili

- Judicex: legal RAG/Q&A con "source of truth", answer contract e citazioni su documenti. Fonte:
  https://github.com/JustVugg/judicex
- Open Legal AI / modelli e dataset: ecosistema orientato a modelli, benchmark, retrieval e
  tooling generico. Fonte: https://github.com/topics/legal-ai
- LegalBench-RAG: benchmark per RAG legale e retrieval in dominio giuridico. Fonte:
  https://github.com/zeroentropy-ai/legalbenchrag

Pattern comune: il problema centrale e' "rispondere bene citando fonti". Manca quasi sempre il
modello operativo "domanda processuale -> fatti -> oneri -> prove -> lacune -> bozza".

### Accademia e affidabilita'

- "Hallucination-Free? Assessing the Reliability of Leading AI Legal Research Tools", Stanford HAI:
  anche strumenti legali avanzati possono produrre errori e risposte incomplete; serve verifica
  umana e controllo delle fonti. Fonte:
  https://hai.stanford.edu/news/ai-trial-legal-models-hallucinate-1-out-6-or-more-benchmarking-queries
- "Large Legal Fictions: Profiling Legal Hallucinations in Large Language Models": evidenzia il
  rischio di allucinazioni in compiti legali, soprattutto se la risposta viene percepita come
  autorevole. Fonte: https://arxiv.org/abs/2401.01301
- "LegalBench-RAG: A Benchmark for Retrieval-Augmented Generation in the Legal Domain": conferma che
  il retrieval legale e' un problema autonomo, misurabile e non risolto da una semplice chat. Fonte:
  https://arxiv.org/abs/2408.10343

Pattern comune: i paper misurano affidabilita', hallucination e retrieval, ma raramente producono
una UX processuale che costringa il sistema a mostrare cosa manca prima di scrivere.

### Regolazione, corti e principi

- EU AI Act, Annex III: i sistemi AI destinati ad assistere autorita' giudiziarie nella ricerca,
  interpretazione dei fatti o applicazione della legge rientrano nell'area ad alto rischio. Fonte:
  https://ai-act-service-desk.ec.europa.eu/en/ai-act/annex-3
- EU AI Act, Article 12: i sistemi ad alto rischio devono avere logging/record keeping. Fonte:
  https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-12
- EU AI Act, Article 14: i sistemi ad alto rischio devono essere progettati per una supervisione
  umana effettiva. Fonte: https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-14
- CEPEJ, European Ethical Charter on AI in judicial systems: principi di rispetto dei diritti,
  non discriminazione, qualita'/sicurezza, trasparenza e controllo dell'utente. Fonte:
  https://rm.coe.int/ethical-charter-en-for-publication-4-december-2018/16808f699c
- NCSC, guidance on implementing AI in courts: approccio pragmatico a governance, rischi, sicurezza,
  dati e uso responsabile negli uffici giudiziari. Fonte:
  https://www.ncsc.org/resources-courts/guidance-implementing-ai-courts
- Ufficio per il processo e AI, Giustizia Insieme: il modello UPP viene letto come organizzazione
  aperta a innovazione e AI, ma con forte dipendenza dal disegno organizzativo. Fonte:
  https://www.giustiziainsieme.it/articolo/2364-il-nuovo-ufficio-per-il-processo-un-modello-organizzativo-aperto-all-intelligenza-artificiale

Pattern comune: chiedono governance, audit e human oversight, ma non indicano un prodotto concreto
per il lavoro quotidiano del redattore UPP.

## Cosa hanno tutti

### 1. Chat con documenti

Carico documenti, chiedo, ricevo risposta con citazioni. Utile, ma non basta per una decisione:
una sentenza non e' una risposta a domanda singola, e' una struttura argomentativa con parti,
domande, eccezioni, prove, oneri e conseguenze.

### 2. Drafting veloce

La promessa commerciale e' spesso "scrivi piu' velocemente". Per un UPP il problema non e' solo
velocita': e' sapere se il testo e' sostenibile rispetto al fascicolo.

### 3. Citazioni come prova di affidabilita'

Molti sistemi trattano la citazione come garanzia. Ma una citazione puo' essere pertinente, parziale,
contraddetta, mal classificata o insufficiente rispetto all'onere probatorio.

### 4. Benchmark astratti

I benchmark misurano retrieval, QA, hallucination, sometimes legal reasoning. Ma un redattore non
lavora a benchmark: lavora su un fascicolo con parti contrapposte e scelte da lasciare al magistrato.

### 5. Human-in-the-loop nominale

Quasi tutti dicono "l'umano verifica". Pochi progettano una UX in cui la verifica e' inevitabile,
tracciata e trasformata in informazione strutturata.

## Cosa manca

### Gap principale: matrice processuale probatorio-decisionale

Manca un oggetto centrale che sia piu' forte della chat e piu' utile della bozza:

| Livello | Domanda |
|---|---|
| Richiesta | Cosa chiede la parte? |
| Fondamento | Quali fatti costitutivi/impeditivi/modificativi/estintivi servono? |
| Onere | Chi deve provare cosa? |
| Fonte | Dove nel fascicolo emerge quel fatto? |
| Contraddittorio | L'altra parte contesta, ammette, tace o produce controprova? |
| Stato prova | Provato, non provato, controverso, insufficiente, da decidere |
| Rischio | Quale passaggio e' fragile, mancante o non fondato? |
| Scelta umana | Cosa deve decidere il magistrato/redattore? |
| Output | Quale paragrafo della bozza dipende da questa catena? |

Questa matrice dovrebbe essere il cuore del prodotto. La bozza diventa un effetto, non il centro.

### Gap secondario 1: citazioni senza funzione processuale

Il settore mostra fonti, ma spesso non dice "a quale elemento della fattispecie serve questa fonte".
UPPilot deve agganciare ogni fonte a una funzione:

- fatto storico;
- domanda;
- eccezione;
- prova documentale;
- non contestazione;
- controprova;
- questione giuridica;
- lacuna.

### Gap secondario 2: mancanza di simmetria attore/convenuto

Molti tool leggono tutto come corpus unico. Un fascicolo giudiziario e' invece avversariale. Serve
una vista simmetrica:

- cosa sostiene l'attore;
- cosa sostiene il convenuto;
- dove coincidono;
- dove divergono;
- dove uno parla e l'altro tace;
- quali documenti supportano o indeboliscono ciascuna posizione.

### Gap secondario 3: audit trail del ragionamento, non solo log tecnico

Il logging tecnico non basta. Serve un registro leggibile:

- quale modello ha proposto una classificazione;
- quali fonti sono state usate;
- quale score era associato;
- cosa ha modificato l'utente;
- quale suggerimento e' stato accettato o scartato;
- quale testo finale dipende da quali fonti.

Questo e' coerente con AI Act e linee guida, ma diventa anche una feature di prodotto.

### Gap secondario 4: rifiuto produttivo

I prodotti cercano di rispondere sempre. Una piattaforma per UPP dovrebbe invece saper dire:

- "non posso fondare questa richiesta sul fascicolo caricato";
- "manca il documento necessario";
- "la prova esiste ma sostiene la parte opposta";
- "la fonte e' debole o solo indiretta";
- "qui serve una decisione umana esplicita".

Il rifiuto non e' fallimento: e' valore.

### Gap secondario 5: didattica incorporata per non esperti

Il target UPP puo' includere utenti non specialisti del dominio o giovani giuristi. Il tool non deve
solo produrre output, deve educare al metodo:

- perche' serve quel documento;
- perche' un fatto e' decisivo;
- cosa significa onere probatorio in quella domanda;
- cosa manca prima di scrivere una motivazione robusta.

## Posizionamento proposto

UPPilot dovrebbe dichiararsi come:

> una piattaforma local-first per costruire una bozza giudiziaria auditabile a partire da una
> matrice processuale delle richieste, dei fatti, delle prove, delle lacune e delle decisioni umane.

Non:

- "chatbot legale";
- "generatore automatico di sentenze";
- "RAG con fonti";
- "assistant generico per documenti".

Si':

- "workbench probatorio-decisionale";
- "sistema di tracciabilita' fascicolo -> richiesta -> prova -> bozza";
- "AI che rende esplicito cio' che manca";
- "strumento per ridurre il rischio di motivazioni non fondate".

## Roadmap focused

### Task 1 - Matrice richieste/prove

Creare una nuova vista per ogni lavoro: "Matrice del fascicolo".

Righe:

- richiesta;
- fatto rilevante;
- parte;
- onere;
- fonti a supporto;
- fonti contrarie;
- stato prova;
- lacune;
- quesito umano.

Prima versione pragmatica:

- usare le `Richiesta` gia' estratte;
- usare `fonti_tracciate`;
- aggiungere un modello `FattoProcessuale`;
- collegare `FattoProcessuale` a richiesta e documenti;
- permettere editing manuale di stato e note.

### Task 2 - Score di funzione fonte

Lo score attuale misura pertinenza. Il salto e' classificare la funzione della fonte:

- supporta;
- contraddice;
- integra;
- e' neutra;
- e' insufficiente;
- e' solo contesto.

Questo trasforma la fonte da link a elemento probatorio.

### Task 3 - Vista simmetrica attore/convenuto

Per ogni richiesta:

- colonna attore;
- colonna convenuto;
- documenti/fatti per ciascuna parte;
- contestazioni/non contestazioni;
- controprove;
- squilibri.

Questa vista differenzia UPPilot dai RAG generici perche' rispetta la forma avversariale del
processo.

### Task 4 - Registro decisionale umano

Aggiungere un ledger consultabile:

- proposta AI;
- fonti usate;
- score;
- scelta utente;
- edit manuale;
- timestamp;
- autore;
- impatto su bozza/export.

Non deve essere pesante: puo' partire come log strutturato degli eventi importanti.

### Task 5 - Export con allegato di audit

Oltre al DOCX della bozza, esportare un allegato "tracciabilita'":

- elenco richieste;
- fonti principali;
- lacune;
- scelte umane;
- punti da verificare;
- avvisi privacy e affidabilita'.

Questo e' utile internamente anche se non viene mai depositato.

### Task 6 - Modalita' "red team del fascicolo"

Un comando che non scrive la bozza, ma cerca debolezze:

- affermazioni non provate;
- richieste senza fonte;
- fonti contraddittorie;
- passaggi giuridici non agganciati;
- PQM non coerente con richieste/motivazione.

Qui UPPilot puo' diventare piu' intelligente proprio perche' smette di essere compiacente.

## Priorita' consigliata

Ordine pratico:

1. Matrice richieste/prove.
2. Funzione fonte: supporta/contraddice/insufficiente.
3. Vista simmetrica attore/convenuto.
4. Registro decisionale umano.
5. Export allegato audit.
6. Red team del fascicolo.

La prima milestone dovrebbe essere piccola ma visibile:

> per ogni richiesta, mostrare una tabella "Fatti e fonti" con stato prova modificabile dall'utente.

Questo crea subito valore e prepara tutto il resto.

## Perche' questa e' la falla giusta

Perche' e' difficile da replicare superficialmente.

Un clone banale puo' fare:

- upload documenti;
- RAG;
- citazioni;
- export Word;
- chat legale.

E' molto piu' difficile replicare:

- modello dati processuale;
- workflow UPP;
- simmetria attore/convenuto;
- tracciabilita' fonte -> fatto -> richiesta -> paragrafo;
- audit umano;
- rifiuto produttivo quando manca prova.

Questo rende UPPilot meno spettacolare come demo, ma piu' utile come strumento serio.

## Decisione strategica

La prossima fase non dovrebbe essere "miglioriamo il chatbot" o "aggiungiamo altra AI".

La prossima fase dovrebbe essere:

> costruire il livello probatorio-decisionale sopra le fonti gia' tracciate.

La tracciabilita' fonti implementata oggi e' il ponte perfetto: non va trattata come feature finale,
ma come primo mattone della matrice processuale.
