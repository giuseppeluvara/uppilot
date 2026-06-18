export interface Utente {
  id: number;
  username: string;
  email: string;
  ruolo: string;
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
  approfondimento_stato: StatoLavorazione;
  approfondimento_errore: string;
  ricerca_stato: StatoLavorazione;
  ricerca_errore: string;
  sezioni: Sezione[];
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
  created_at: string;
}

export interface FrammentoCorpus {
  id: number;
  ordine: number;
  testo: string;
}

export interface RisultatoCorpus {
  documento_id: number;
  titolo: string;
  fonte: string;
  ordine: number;
  testo: string;
  distanza: number;
}
