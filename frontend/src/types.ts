export interface Utente {
  id: number;
  username: string;
  email: string;
  ruolo: string;
}

export interface ProgressoTask {
  fase?: string;
  corrente?: number;
  totale?: number;
  percentuale?: number;
  messaggio?: string;
  aggiornato_at?: string;
}

export interface PrivacyReport {
  ok: boolean;
  leaks: { placeholder: string; token: string }[];
  unknown_pii: { tipo: string; token: string }[];
  malformed_placeholders: string[];
  warnings: number;
}

export interface WorkflowChecklist {
  documenti_caricati: number;
  documenti_pronti: number;
  documenti_da_verificare: number;
  documenti_in_lavorazione: number;
  analisi_pronta: boolean;
  analisi_parziale: boolean;
  analisi_completata: boolean;
  richieste_totali: number;
  richieste_approfondite: number;
  motivazioni_redatte: number;
  pqm_compilato: boolean;
}

export interface DocumentiStatistiche {
  totali: number;
  in_lavorazione: number;
  pseudonimizzati: number;
  accettati: number;
  da_verificare: number;
}

export interface Documento {
  id: number;
  file: string;
  nome_logico: string;
  ordine: number;
  tipo_rilevato: string;
  stato_estrazione: "in_attesa" | "in_corso" | "completato" | "errore";
  errore_estrazione: string;
  metodo_estrazione: string;
  flag_bassa_confidenza: boolean;
  passaggi_incerti: string[];
  stato_anonimizzazione: "in_attesa" | "in_corso" | "completata" | "errore";
  errore_anonimizzazione: string;
  pseudonimizzato: boolean;
  testo_pseudonimizzato: string;
  mappa_entita: Record<string, string>;
  stato_accettazione: "da_verificare" | "verificato" | "accettato_senza_verifica";
  utilizzabile: boolean;
  privacy_report: PrivacyReport;
}

export interface Sezione {
  id: number;
  tipo: "generici" | "attore" | "convenuto";
  documenti: Documento[];
}

export type StatoLavorazione = "in_attesa" | "in_corso" | "completata" | "errore";

export interface Lavoro {
  id: number;
  titolo: string;
  stato: string;
  analisi_stato: StatoLavorazione;
  analisi_errore: string;
  analisi_progresso: ProgressoTask;
  approfondimento_stato: StatoLavorazione;
  approfondimento_errore: string;
  approfondimento_progresso: ProgressoTask;
  ricerca_stato: StatoLavorazione;
  ricerca_errore: string;
  ricerca_progresso: ProgressoTask;
  modello_testo: string;
  assegnato_a: number | null;
  revisore: number | null;
  stato_revisione: "da_rivedere" | "in_revisione" | "validato" | "esportato";
  sezioni: Sezione[];
  documenti_statistiche: DocumentiStatistiche;
  checklist: WorkflowChecklist;
  privacy_report: PrivacyReport;
  created_at: string;
  updated_at: string;
}

export interface Richiesta {
  id: number;
  ordine: number;
  parte_richiedente: "attore" | "convenuto";
  tipo: "domanda" | "difesa_eccezione" | "riconvenzionale" | "istruttoria" | "altro";
  testo: string;
  confidence: number;
  flags: string[];
  avvisi: string[];
  stato: string;
  onere_probatorio: string;
  allegati_collegati: number[];
  non_contestazioni: string[];
  quesiti_aperti: string[];
  motivazione: string;
  fonti_tracciate: FonteTracciata[];
}

export interface FonteTracciata {
  documento_id: number;
  documento_nome: string;
  documento_url: string;
  sezione: "generici" | "attore" | "convenuto";
  sezione_label: string;
  score: number;
  affidabilita: "alta" | "media" | "bassa";
  affidabilita_label: string;
  termini: string[];
  numeri: string[];
  motivi: string[];
  snippet: string;
  posizione: number;
  anchor: string;
  valutazione_operatore?: "decisiva" | "irrilevante" | "da_verificare";
  valutazione_label?: string;
}

export type StatoProva =
  | "da_verificare"
  | "provato"
  | "non_provato"
  | "controverso"
  | "insufficiente"
  | "da_decidere";

export type FunzioneFonte =
  | "supporta"
  | "contraddice"
  | "integra"
  | "neutra"
  | "insufficiente"
  | "contesto";

export type StatoContraddittorio =
  | "pacifico"
  | "contestato"
  | "non_contestato"
  | "controprovato"
  | "silente"
  | "da_decidere";

export interface FattoProcessuale {
  id: number;
  richiesta_id: number;
  ordine: number;
  testo: string;
  parte_richiedente: Richiesta["parte_richiedente"];
  tipo: Richiesta["tipo"];
  richiesta_testo: string;
  onere_probatorio: string;
  motivazione: string;
  allegati_collegati: number[];
  quesiti_aperti: string[];
  fonti: FonteTracciata[];
  fonti_count: number;
  score_massimo: number;
  affidabilita_massima: "alta" | "media" | "bassa" | "assente";
  lacune: string[];
  stato_prova: StatoProva;
  stato_prova_label: string;
  stato_suggerito: StatoProva;
  stato_suggerito_label: string;
  funzione_prevalente: FunzioneFonte;
  funzione_prevalente_label: string;
  stato_contraddittorio: StatoContraddittorio;
  stato_contraddittorio_label: string;
  stato_contraddittorio_suggerito: StatoContraddittorio;
  stato_contraddittorio_suggerito_label: string;
  fonti_attore: FonteTracciata[];
  fonti_convenuto: FonteTracciata[];
  fonti_generiche: FonteTracciata[];
  fonti_supporto: FonteTracciata[];
  fonti_controparte: FonteTracciata[];
  contraddittorio_lacune: string[];
  note_operatore: string;
  note_contraddittorio: string;
  quesito_umano: string;
  created_at: string;
  updated_at: string;
}

export interface EventoDecisionale {
  id: number;
  lavoro: number;
  richiesta: number | null;
  fatto: number | null;
  utente: number | null;
  utente_username: string;
  tipo: string;
  tipo_label: string;
  campo: string;
  descrizione: string;
  valore_precedente: Record<string, unknown>;
  valore_nuovo: Record<string, unknown>;
  created_at: string;
}

export interface RedTeamIssue {
  richiesta_id: number | null;
  fatto_id: number | null;
  richiesta: string;
  severita: "alta" | "media" | "bassa";
  ambito: string;
  messaggio: string;
  azione_suggerita: string;
}

export interface RedTeamReport {
  ok: boolean;
  totale: number;
  conteggi: { alta: number; media: number; bassa: number };
  issues: RedTeamIssue[];
}

export interface Bozza {
  lavoro: number;
  in_fatto: string;
  pqm: string;
  contenuto_per_richiesta: Record<string, unknown>;
  versione: number;
  updated_at: string;
}

export interface Spunto {
  id: number;
  argomento: string;
  query_pseudonimizzata: string;
  sintesi: string;
  suggerimento: string;
  fonte: string;
  stato_fonte: "ok" | "insufficiente";
  fonte_affidabilita: "alta" | "media" | "bassa" | "non_indicata" | "insufficiente";
  fonte_label: string;
  tipo_fonte: string;
  motivazione_affidabilita: string;
  origine: "web" | "manuale";
  created_at: string;
}

export interface CommentoEditor {
  id: number;
  lavoro: number;
  utente: number | null;
  utente_username: string;
  sezione: "in_fatto" | "in_diritto" | "pqm" | "fonte" | "privacy" | "generale";
  sezione_label: string;
  riferimento_id: number | null;
  testo: string;
  risolto: boolean;
  created_at: string;
  updated_at: string;
}

export interface AzioneLacuna {
  tipo: string;
  label: string;
  descrizione: string;
  fatto_id: number | null;
  richiesta_id: number | null;
  severita: "alta" | "media" | "bassa";
}

export interface RevisioneChecklistItem {
  id: string;
  label: string;
  ok: boolean;
}

export interface TemplateProvvedimento {
  id: string;
  label: string;
  ambito: string;
  testo: string;
}

export interface RevisioneFascicolo {
  pronto_export: boolean;
  messaggio: string;
  blocchi: string[];
  avvisi: string[];
  checklist: RevisioneChecklistItem[];
  dashboard: {
    oggetto: string;
    stato: string;
    parti_placeholder: string[];
    domande: {
      id: number;
      parte: Richiesta["parte_richiedente"];
      tipo: Richiesta["tipo"];
      testo: string;
      confidence: number;
    }[];
    prove_chiave: FonteTracciata[];
    punti_controversi: string[];
    rischi: RedTeamIssue[];
    prossime_azioni: AzioneLacuna[];
  };
  qualita_ai: {
    score: number;
    documenti_coperti: number;
    documenti_utilizzabili: number;
    copertura_documenti_percentuale: number;
    richieste_totali: number;
    richieste_confidenza_bassa: number;
    fonti_totali: number;
    fonti_deboli: number;
    fonti_assenti: number;
    fonti_decisive: number;
    quesiti_aperti: number;
    coerenze_da_rivedere: number;
    progressi: Record<string, unknown>;
  };
  red_team: RedTeamReport;
  azioni_lacune: AzioneLacuna[];
  privacy_assistita: {
    ok: boolean;
    report: PrivacyReport;
    entita: { placeholder: string; valore: string }[];
    placeholder_sospetti: string[];
    residui_sospetti: unknown[];
  };
  documenti_workflow: {
    totali: number;
    accettati: number;
    da_verificare: number;
    in_lavorazione: number;
    duplicati_sospetti: { documento_id: number; nome: string; simile_a: number }[];
    ordine_cronologico: {
      id: number;
      nome: string;
      nome_logico: string;
      ordine: number;
      sezione: Sezione["tipo"];
      tipo_rilevato: string;
      created_at: string;
    }[];
  };
  template_disponibili: TemplateProvvedimento[];
}

export interface DocumentoCorpus {
  id: number;
  titolo: string;
  fonte: string;
  categoria: string;
  stato: "in_attesa" | "in_corso" | "completato" | "errore";
  errore: string;
  n_frammenti: number;
  eliminabile: boolean;
  created_at: string;
}

export interface FrammentoCorpus {
  id: number;
  ordine: number;
  testo: string;
}

export interface NodoGrafo {
  id: number;
  tipo: "concetto" | "riferimento" | "caso";
  etichetta: string;
  sintesi: string;
  documento: number | null;
  documento_titolo: string;
  lavoro: number | null;
  origine: "fascicolo" | "corpus" | "globale";
  snippet: string;
}

export interface ArcoGrafo {
  id: number;
  da: number;
  a: number;
  tipo: "cita" | "correlato" | "in_contrasto" | "applica";
  peso: number;
}

export interface Grafo {
  nodi: NodoGrafo[];
  archi: ArcoGrafo[];
}

export interface StatoGrafo {
  in_corso: boolean;
  n_nodi: number;
  n_archi: number;
  progresso: ProgressoTask;
  changelog: { evento: string; stato: "ok" | "errore" | string }[];
}

export interface RisultatoCorpus {
  documento_id: number;
  titolo: string;
  fonte: string;
  ordine: number;
  testo: string;
  distanza: number;
  rilevanza: "alta" | "media" | "bassa";
}

export interface HealthAi {
  ok: boolean;
  hint: string;
  checks: Record<string, { ok: boolean; detail: string }>;
}
