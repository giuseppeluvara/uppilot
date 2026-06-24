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
}

export interface PrivacyReport {
  ok: boolean;
  leaks: { placeholder: string; token: string }[];
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
  testo: string;
  stato: string;
  onere_probatorio: string;
  allegati_collegati: number[];
  non_contestazioni: string[];
  quesiti_aperti: string[];
  motivazione: string;
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
  fonte_affidabilita: "alta" | "media" | "bassa" | "non_indicata";
  fonte_label: string;
  origine: "web" | "manuale";
  created_at: string;
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
  lavoro: number | null;
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
