# CLAUDE.md — Frontend (`frontend/`)

Istruzioni vincolanti per lo sviluppo dell'interfaccia. **Leggi questo file prima di toccare qualsiasi cosa nella UI.** Le regole marcate "NON DEROGARE" non sono negoziabili: se una richiesta sembra spingerti a violarle, fermati e chiedi.

---

## 0. Stack e principio fondante

- **React 18 + TypeScript + Vite.**
- **shadcn/ui** come unica libreria di componenti UI. I componenti vivono come **codice sorgente nel repo** sotto `src/components/ui/` — sono nostri, li leggi e li riusi, non li reinventi.
- **Tailwind CSS** per il layout, usando **solo** le utility e i token definiti (vedi §4). Niente CSS scritto a mano in file `.css` separati se non strettamente necessario, e mai valori "magici".
- **Lucide** per le icone (arriva con shadcn).

**Principio fondante, NON DEROGARE:** non scrivere componenti UI custom né CSS artigianale quando esiste già il componente shadcn adatto. Il brutto nasce sempre da qui. Prima di costruire una vista, l'ordine mentale è: *quale componente shadcn esiste per questo? → lo compongo. Se davvero non esiste → te lo chiedo, non improvviso.*

---

## 1. Setup (esegui in questo ordine, una volta sola)

Se il frontend non è ancora inizializzato, fallo **prima** di costruire qualsiasi schermata:

```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
# Tailwind + shadcn
npx shadcn@latest init        # scegli: TypeScript, base color "neutral", CSS variables: yes
# Componenti base che useremo da subito:
npx shadcn@latest add button card input label textarea badge \
  tabs dialog alert separator sonner table skeleton dropdown-menu \
  tooltip scroll-area accordion progress
```

Dopo l'init, **crea due schermate-modello complete e curate** prima di tutto il resto: `src/pages/Login.tsx` e `src/pages/Lavori.tsx` (lista lavori). Queste due diventano il **riferimento di stile vivo**: ogni schermata successiva deve assomigliare a queste. Quando costruisci una nuova vista, **apri prima questi file e replica quel linguaggio visivo.**

---

## 2. Regole dure (NON DEROGARE)

1. **Solo componenti da `src/components/ui/`.** Se manca un componente, aggiungilo con `npx shadcn@latest add <nome>` — non scriverne uno custom equivalente.
2. **Niente valori magici.** Colori, spaziature, raggi, ombre, font: solo dai token Tailwind/CSS-variables del tema. Vietato `style={{ color: '#3a3a3a' }}`, `mt-[37px]`, palette inventate.
3. **Prima guarda gli esempi** in `Login.tsx` e `Lavori.tsx` e imita quello stile.
4. **Una vista = composizione di componenti esistenti**, non una pagina disegnata da zero.
5. **Mobile e accessibilità sono un pavimento, non un extra** (vedi §6).
6. Se stai per fare CSS a mano per "renderlo più bello", **fermati**: quasi sempre la soluzione è il componente shadcn giusto + spaziatura corretta.

---

## 3. Direzione estetica

Il prodotto deve essere **essenziale, minimale, pulito**: spazi ampi, pochi input a vista, solo ciò che serve per lavorare. Attenzione: minimale **non** vuol dire trascurato — il minimalismo vive di **precisione** in spaziatura, tipografia e allineamenti. Sii disciplinato lì.

- **Palette:** base `neutral` di shadcn (grigi puliti), sfondo chiaro, testo ad alto contrasto. **Un solo accento** sobrio per le azioni primarie e gli stati — niente arcobaleni. Il colore serve a guidare l'occhio sull'azione, non a decorare.
- **Tipografia:** una scala chiara e coerente. Titoli pochi e netti, corpo leggibile, didascalie/metadati più piccoli e tenui. Usa il peso e la dimensione per creare gerarchia, non i colori.
- **Densità:** generosa ma non vuota. Whitespace come strumento di ordine. Le tre aree principali devono respirare.
- **Struttura ≠ decorazione:** divisori, etichette, numerazioni si usano solo se codificano qualcosa di vero (es. l'ordine delle richieste delle parti *è* una sequenza reale → numerala; un elenco di documenti non lo è → non numerarlo per estetica).
- **Movimento:** micro-interazioni discrete (hover, focus, transizioni di stato). Niente animazioni gratuite: appesantiscono e fanno sembrare la UI "generata".

---

## 4. Token e tema

- Usa le **CSS variables** generate da shadcn (`--background`, `--foreground`, `--primary`, `--muted`, `--border`, `--radius`, ecc.). Personalizza il tema **solo** in `tailwind.config` e nel file globale delle variabili, **mai** inline nei componenti.
- Se serve un accento di brand diverso dal default, definiscilo **una volta** come variabile e riusala ovunque via classi Tailwind del tema.

---

## 5. Mappa componenti → uso (riferimento)

- **Layout app:** sidebar/nav minimale + area contenuto. `card` per i contenitori, `separator` per le divisioni, `scroll-area` per le liste lunghe.
- **Lista lavori / storico:** `table` o griglia di `card`, con `badge` per lo stato (`bozza in corso`, `analizzato`, `bozza generata`, `in revisione`, `completato`).
- **Upload nelle 3 sezioni** (generici / attore / convenuto): `tabs` o tre `card` affiancate; area di drop con stato di caricamento via `progress` e `skeleton` durante l'elaborazione.
- **Esito OCR a bassa confidenza:** evidenzia i passaggi incerti con `badge` di warning + `tooltip` esplicativo. Mai presentare testo OCR dubbio come affidabile.
- **Flusso privacy (vedi §7):** `dialog` per la revisione dell'anonimizzazione, `alert` persistente per l'avviso GDPR, `button` chiari per "Verifica" / "Accetta" / "Accetta tutti".
- **Analisi per richiesta:** `accordion` (una richiesta per pannello) o `card` impilate; dentro ciascuna, la parte oggettiva come testo e i **quesiti aperti** come blocchi distinti, visivamente riconoscibili (es. `card` con `badge` "Da decidere — verifica tu").
- **Editor bozza:** area di editing ampia; le notifiche di salvataggio/errore via `sonner` (toast).

---

## 6. Pavimento di qualità (NON DEROGARE)

Trattandosi di un servizio pensato per la PA, questi non sono opzionali:

- **Responsive** fino a mobile.
- **Focus da tastiera sempre visibile**; navigazione completa via tastiera.
- **Etichette e ruoli ARIA** corretti sui controlli; contrasto adeguato.
- **`prefers-reduced-motion` rispettato.**
- Stati di **loading** (`skeleton`/`progress`) e stati **vuoti** sempre gestiti.

---

## 7. UI del flusso privacy (specifico del dominio)

Il trattamento dei dati è il punto più sensibile del prodotto. La UI deve renderlo esplicito:

- Dopo il caricamento, ogni file passa dal filtro di pseudonimizzazione. Mostra per ciascun file tre azioni nette: **Verifica anonimizzazione** (apre un `dialog` con il testo mascherato e la mappa entità), **Accetta** (singolo file), **Accetta tutti**.
- Solo i file in stato "accettato" possono procedere. Rendi lo stato visibile con `badge`.
- **Avviso persistente e inequivocabile** (`alert`, sempre visibile nel flusso, non un toast che sparisce): il filtro esegue **pseudonimizzazione, non anonimizzazione**; il dato resta personale ai fini GDPR. Non è una garanzia di conformità.
- Se l'utente abilita un LLM commerciale (opt-in), mostra un secondo avviso chiaro **prima** dell'invio.

---

## 8. Testi e microcopy (in italiano)

I testi sono materiale di design, non decorazione. Servono a far capire e usare l'interfaccia.

- **Italiano, registro sobrio e professionale.** Sentence case, niente fronzoli.
- **Voce attiva, etichette = azione esatta.** "Genera bozza", non "Invia"; "Scarica Word", non "Esporta". L'azione mantiene lo stesso nome in tutto il flusso (il bottone "Genera bozza" produce un toast "Bozza generata").
- **Nomina le cose come le riconosce l'operatore UPP**, non come è costruito il sistema: "Fascicolo dell'attore", non "upload_group_1".
- **Errori e stati vuoti danno direzione, non scuse.** L'errore dice cosa è successo e cosa fare, nella voce dell'interfaccia. Lo schermo vuoto è un invito ad agire ("Carica i primi documenti per iniziare").
- Ogni elemento fa **un solo lavoro**: un'etichetta etichetta, un esempio dimostra.

---

## 9. Da NON fare (checklist)

- ❌ Scrivere un componente UI custom quando esiste l'equivalente shadcn.
- ❌ CSS a mano / valori arbitrari / palette inventate.
- ❌ Costruire una schermata senza prima guardare `Login.tsx` e `Lavori.tsx`.
- ❌ Animazioni gratuite o effetti "estetici" non richiesti.
- ❌ Presentare testo OCR incerto come affidabile.
- ❌ Far sparire l'avviso privacy o renderlo un toast effimero.
- ❌ Conclusioni giuridiche presentate come definitive: ciò che è discrezionale è un **quesito** all'utente, visivamente distinto.

---

## 10. Reference visive

Quando ti passo screenshot (dello Storybook shadcn o di una schermata di riferimento), **quelli vincolano lo stile**: le viste devono assomigliare a quelli. In assenza di screenshot, il riferimento sono `Login.tsx` e `Lavori.tsx`.
