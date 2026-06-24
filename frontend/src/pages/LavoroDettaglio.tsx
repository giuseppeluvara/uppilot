import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Ban,
  CircleCheck,
  ClipboardPaste,
  Download,
  Eye,
  ExternalLink,
  FolderOpen,
  HelpCircle,
  Loader2,
  Maximize2,
  Minimize2,
  Play,
  Save,
  Scale,
  Search,
  ShieldAlert,
  Trash2,
  TriangleAlert,
  Upload,
} from "lucide-react";
import { api, ApiError } from "@/api";
import type {
  Bozza,
  Documento,
  Lavoro,
  PrivacyReport,
  ProgressoTask,
  Richiesta,
  Sezione,
  Spunto,
} from "@/types";
import { statoLavoro } from "@/lib/stato";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

const TITOLO_SEZIONE: Record<Sezione["tipo"], string> = {
  generici: "Documenti generici",
  attore: "Fascicolo dell'attore",
  convenuto: "Fascicolo del convenuto / ricorrente",
};

const TIPO_RICHIESTA: Record<Richiesta["tipo"], string> = {
  domanda: "Domanda",
  difesa_eccezione: "Difesa/eccezione",
  riconvenzionale: "Riconvenzionale",
  istruttoria: "Istruttoria",
  altro: "Altro",
};

const baseName = (p: string) => decodeURIComponent(p.split("/").pop() || p);

type Pending = { analisi?: boolean; approf?: boolean; ricerca?: boolean };
type ConfermaAzione = {
  titolo: string;
  descrizione: string;
  conferma: string;
  destructive?: boolean;
  onConfirm: () => void;
};

export function LavoroDettaglio({ id, onIndietro }: { id: number; onIndietro: () => void }) {
  const [lavoro, setLavoro] = useState<Lavoro | null>(null);
  const [bozza, setBozza] = useState<Bozza | null>(null);
  const [richieste, setRichieste] = useState<Richiesta[]>([]);
  const [spunti, setSpunti] = useState<Spunto[]>([]);
  const [commerciale, setCommerciale] = useState(false);
  const [pending, setPending] = useState<Pending>({});
  const [conferma, setConferma] = useState<ConfermaAzione | null>(null);
  const [documentoDaEliminare, setDocumentoDaEliminare] = useState<{ id: number; nome: string } | null>(null);

  const carica = useCallback(async () => {
    try {
      const l = await api.get<Lavoro>(`/lavori/${id}/`);
      setLavoro(l);
      setSpunti(await api.get<Spunto[]>(`/lavori/${id}/spunti/`));
      if (l.analisi_stato === "completata") {
        setRichieste(await api.get<Richiesta[]>(`/lavori/${id}/richieste/`));
        try {
          setBozza(await api.get<Bozza>(`/lavori/${id}/bozza/`));
        } catch {
          /* nessuna bozza */
        }
      }
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Errore di caricamento.");
    }
  }, [id]);

  useEffect(() => {
    carica();
  }, [carica]);

  // Sgancia il "pending" ottimistico quando il SERVER mostra "in_corso" (si è
  // allineato: da qui in poi è lo stato reale a tenere il tasto disabilitato).
  // NON sganciare su uno stato terminale: rilanciando da "completata" il refetch
  // immediato mostra ancora il vecchio "completata" e ri-abiliterebbe il tasto.
  useEffect(() => {
    if (!lavoro) return;
    setPending((p) => ({
      analisi: lavoro.analisi_stato === "in_corso" ? false : p.analisi,
      approf: lavoro.approfondimento_stato === "in_corso" ? false : p.approf,
      ricerca: lavoro.ricerca_stato === "in_corso" ? false : p.ricerca,
    }));
  }, [lavoro]);

  const analisiInCorso = lavoro?.analisi_stato === "in_corso" || !!pending.analisi;
  const approfInCorso = lavoro?.approfondimento_stato === "in_corso" || !!pending.approf;
  const ricercaInCorso = lavoro?.ricerca_stato === "in_corso" || !!pending.ricerca;

  // Polling mentre estrazione o una qualunque elaborazione è in corso.
  const timer = useRef<number>(undefined);
  useEffect(() => {
    const inLavorazione =
      analisiInCorso ||
      approfInCorso ||
      ricercaInCorso ||
      lavoro?.sezioni.some((s) =>
        s.documenti.some(
          (d) =>
            ["in_attesa", "in_corso"].includes(d.stato_estrazione) ||
            d.stato_anonimizzazione === "in_corso",
        ),
      );
    if (inLavorazione) {
      timer.current = window.setTimeout(carica, 2500);
      return () => window.clearTimeout(timer.current);
    }
  }, [lavoro, analisiInCorso, approfInCorso, ricercaInCorso, carica]);

  const azione = useCallback(
    async (fn: () => Promise<unknown>, ok?: string): Promise<boolean> => {
      try {
        await fn();
        if (ok) toast.success(ok);
        await carica();
        return true;
      } catch (err) {
        toast.error(err instanceof ApiError ? err.message : "Operazione non riuscita.");
        return false;
      }
    },
    [carica],
  );

  // Avvia un'elaborazione mostrando subito lo stato (ottimistico), e lo annulla se fallisce.
  const avvia = useCallback(
    async (chiave: keyof Pending, fn: () => Promise<unknown>, ok: string) => {
      setPending((p) => ({ ...p, [chiave]: true }));
      const esito = await azione(fn, ok);
      if (!esito) {
        setPending((p) => ({ ...p, [chiave]: false }));
        return;
      }
      // Sicurezza: se entro 30s il server non ha mostrato "in_corso", sgancia il
      // pending (se nel frattempo è davvero in corso, lo stato reale tiene comunque
      // il tasto disabilitato; questo evita solo che resti bloccato in casi anomali).
      window.setTimeout(() => setPending((p) => ({ ...p, [chiave]: false })), 30000);
    },
    [azione],
  );

  // Interrompe un'elaborazione in corso (avviata per errore o da rifare).
  const annulla = useCallback(
    async (chiave: keyof Pending, fase: string) => {
      setPending((p) => ({ ...p, [chiave]: false }));
      await azione(() => api.post(`/lavori/${id}/annulla/`, { fase }), "Elaborazione interrotta");
    },
    [azione, id],
  );

  if (!lavoro) return <Skeletons />;

  const s = statoLavoro(lavoro.stato);
  const daAccettare = lavoro.sezioni.some((sez) =>
    sez.documenti.some((d) => d.pseudonimizzato && d.stato_accettazione === "da_verificare"),
  );
  const documenti = lavoro.sezioni.flatMap((sez) => sez.documenti);
  const documentiUtilizzabili = documenti.some((d) => d.utilizzabile);
  const documentiInLavorazione = documenti.some(
    (d) =>
      ["in_attesa", "in_corso"].includes(d.stato_estrazione) ||
      d.stato_anonimizzazione === "in_corso",
  );
  const bloccoAnalisi = documentiUtilizzabili
    ? ""
    : documentiInLavorazione
      ? "Attendi la fine di estrazione e pseudonimizzazione prima di avviare l'analisi."
      : daAccettare
        ? "Rivedi e accetta almeno un documento pseudonimizzato prima di avviare l'analisi."
        : "Carica almeno un documento, attendi la pseudonimizzazione e accettalo prima di avviare l'analisi.";
  const analisiParziale = Boolean(lavoro.checklist?.analisi_parziale);
  const privacyReport = lavoro.privacy_report;
  const nomiAllegati: Record<number, string> = {};
  for (const sez of lavoro.sezioni)
    for (const d of sez.documenti) nomiAllegati[d.id] = baseName(d.file);

  function caricaFile(sezioneId: number, files: File[]) {
    return azione(async () => {
      for (const file of files) {
        const form = new FormData();
        form.append("sezione", String(sezioneId));
        form.append("file", file);
        await api.upload("/documenti/", form);
      }
    }, files.length > 1 ? `${files.length} documenti caricati` : "Documento caricato");
  }

  function avviaAnalisi() {
    const start = (conferma_parziale = false) =>
      avvia(
        "analisi",
        () => api.post(`/lavori/${id}/analizza/`, { commerciale, conferma_parziale }),
        "Analisi avviata",
      );
    if (analisiParziale) {
      setConferma({
        titolo: "Avviare analisi parziale?",
        descrizione:
          "Ci sono documenti pseudonimizzati non ancora accettati. L'analisi userà solo quelli già pronti.",
        conferma: "Avvia analisi parziale",
        onConfirm: () => start(true),
      });
      return;
    }
    start(false);
  }

  function scaricaExport(inChiaro: boolean) {
    const path = `/lavori/${id}/esporta/${inChiaro ? "?chiaro=1" : ""}`;
    const scarica = (overridePrivacy = false) =>
      azione(
        () =>
          api.download(
            overridePrivacy ? `/lavori/${id}/esporta/?force_privacy=1` : path,
            `bozza_${id}${inChiaro ? "_in_chiaro" : ""}.docx`,
          ),
        "Documento scaricato",
      );
    if (inChiaro) {
      setConferma({
        titolo: "Scaricare versione in chiaro?",
        descrizione: "Il documento conterrà i dati personali reali delle parti.",
        conferma: "Scarica in chiaro",
        destructive: true,
        onConfirm: () => scarica(false),
      });
      return;
    }
    const warnings = privacyReport?.warnings ?? 0;
    if (warnings > 0) {
      setConferma({
        titolo: "Override controllo privacy?",
        descrizione:
          "Il controllo privacy segnala possibili residui nel testo pseudonimizzato. Scarica solo dopo revisione consapevole.",
        conferma: "Scarica comunque",
        destructive: true,
        onConfirm: () => scarica(true),
      });
      return;
    }
    scarica(false);
  }

  return (
    <div className="grid gap-6">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={onIndietro}>
          <ArrowLeft />
          Archivio
        </Button>
        <Separator orientation="vertical" className="h-5" />
        <h1 className="text-xl font-semibold tracking-tight">{lavoro.titolo}</h1>
        <Badge variant={s.variant}>{s.label}</Badge>
      </div>

      <WorkflowCard lavoro={lavoro} richieste={richieste} />
      <PrivacyReportAlert report={lavoro.privacy_report} />

      <section className="grid gap-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold tracking-tight">Documenti del fascicolo</h2>
          {lavoro.sezioni.some((s) => s.documenti.length > 0) && (
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                azione(
                  () => api.download(`/lavori/${id}/documenti-zip/`, `documenti_lavoro_${id}.zip`),
                  "Documenti scaricati",
                )
              }
            >
              <Download />
              Scarica tutti
            </Button>
          )}
        </div>
        {lavoro.sezioni.map((sez) => (
          <SezioneCard
            key={sez.id}
            sezione={sez}
            onUpload={(files) => caricaFile(sez.id, files)}
            onAccetta={(d) => azione(() => api.post(`/documenti/${d}/accetta/`), "Documento accettato")}
            onVerifica={(d) => azione(() => api.post(`/documenti/${d}/verifica/`), "Anonimizzazione verificata")}
            onSalvaPrivacy={(d, payload) =>
              azione(() => api.patch(`/documenti/${d}/privacy/`, payload), "Correzioni privacy salvate")
            }
            onRiprova={(d) =>
              azione(() => api.post(`/documenti/${d}/ripseudonimizza/`), "Anonimizzazione riavviata")
            }
            onElimina={(d) => setDocumentoDaEliminare({ id: d, nome: nomiAllegati[d] ?? `documento ${d}` })}
          />
        ))}
        {daAccettare && (
          <div>
            <Button
              variant="outline"
              onClick={() => azione(() => api.post(`/lavori/${id}/accetta-tutti/`), "Documenti accettati")}
            >
              Accetta tutti i documenti
            </Button>
          </div>
        )}
      </section>

      <ModelloRedazione
        lavoro={lavoro}
        onSalvaTesto={(testo) =>
          azione(() => api.post(`/lavori/${id}/modello/`, { testo }), "Modello salvato")
        }
        onEstrai={async (file) => {
          const form = new FormData();
          form.append("file", file);
          try {
            const r = await api.upload<{ testo: string }>(`/lavori/${id}/estrai-modello/`, form);
            return r.testo;
          } catch (err) {
            toast.error(err instanceof ApiError ? err.message : "File non leggibile.");
            return null;
          }
        }}
      />

      <MotoreCard commerciale={commerciale} onChange={setCommerciale} />

      <AnalisiCard
        lavoro={lavoro}
        inCorso={analisiInCorso}
        blocco={bloccoAnalisi}
        parziale={analisiParziale}
        progresso={lavoro.analisi_progresso}
        onAvvia={avviaAnalisi}
        onInterrompi={() => annulla("analisi", "analisi")}
      />

      {bozza && (
        <BozzaEditor
          bozza={bozza}
          onScarica={() => scaricaExport(false)}
          onScaricaChiaro={() => scaricaExport(true)}
          onSalva={(testo) =>
            azione(async () => {
              setBozza(await api.patch<Bozza>(`/lavori/${id}/bozza/`, { in_fatto: testo }));
            }, "Bozza salvata")
          }
        />
      )}

      {lavoro.analisi_stato === "completata" && (
        <RichiesteSection
          lavoro={lavoro}
          richieste={richieste}
          nomiAllegati={nomiAllegati}
          inCorso={approfInCorso}
          progresso={lavoro.approfondimento_progresso}
          onApprofondisci={() =>
            avvia("approf", () => api.post(`/lavori/${id}/approfondisci/`, { commerciale }), "Approfondimento avviato")
          }
          onInterrompi={() => annulla("approf", "approfondimento")}
          onSalvaMotivazione={(rid, testo) =>
            azione(() => api.patch(`/richieste/${rid}/`, { motivazione: testo }), "Motivazione salvata")
          }
        />
      )}

      {lavoro.analisi_stato === "completata" && (
        <RicercaCard
          lavoro={lavoro}
          spunti={spunti}
          inCorso={ricercaInCorso}
          progresso={lavoro.ricerca_progresso}
          onInterrompi={() => annulla("ricerca", "ricerca")}
          onCercaWeb={() => avvia("ricerca", () => api.post(`/lavori/${id}/ricerca/`, { commerciale }), "Ricerca avviata")}
          onManuale={(argomento, materiale) =>
            avvia(
              "ricerca",
              () => api.post(`/lavori/${id}/ricerca/manuale/`, { argomento, materiale, commerciale }),
              "Spunto in elaborazione",
            )
          }
        />
      )}

      {bozza && (
        <PqmEditor
          bozza={bozza}
          onSalva={(testo) =>
            azione(async () => {
              setBozza(await api.patch<Bozza>(`/lavori/${id}/bozza/`, { pqm: testo }));
            }, "P.Q.M. salvato")
          }
        />
      )}

      <Dialog open={documentoDaEliminare !== null} onOpenChange={(o) => !o && setDocumentoDaEliminare(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Eliminare il documento?</DialogTitle>
            <DialogDescription>
              “{documentoDaEliminare?.nome}” verrà rimosso definitivamente dal lavoro.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDocumentoDaEliminare(null)}>
              Annulla
            </Button>
            <Button
              variant="destructive"
              onClick={async () => {
                if (!documentoDaEliminare) return;
                const idDocumento = documentoDaEliminare.id;
                setDocumentoDaEliminare(null);
                await azione(() => api.del(`/documenti/${idDocumento}/`), "Documento eliminato");
              }}
            >
              Elimina
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={conferma !== null} onOpenChange={(o) => !o && setConferma(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{conferma?.titolo}</DialogTitle>
            <DialogDescription>{conferma?.descrizione}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConferma(null)}>
              Annulla
            </Button>
            <Button
              variant={conferma?.destructive ? "destructive" : "default"}
              onClick={() => {
                const az = conferma?.onConfirm;
                setConferma(null);
                az?.();
              }}
            >
              {conferma?.conferma ?? "Conferma"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Skeletons() {
  return (
    <div className="grid gap-4">
      <div className="h-8 w-48 animate-pulse rounded-md bg-muted" />
      <div className="h-40 w-full animate-pulse rounded-md bg-muted" />
    </div>
  );
}

const WARNING_COMMERCIALE =
  "Il testo (pseudonimizzato, non anonimizzato) viene inviato a un LLM commerciale in cloud: " +
  "ai fini del GDPR resta dato personale. Configura la chiave API e procedi solo se consapevole.";

function ModelloRedazione({
  lavoro,
  onSalvaTesto,
  onEstrai,
}: {
  lavoro: Lavoro;
  onSalvaTesto: (testo: string) => void;
  onEstrai: (file: File) => Promise<string | null>;
}) {
  const [testo, setTesto] = useState(lavoro.modello_testo);
  const [estraendo, setEstraendo] = useState(false);
  useEffect(() => setTesto(lavoro.modello_testo), [lavoro.modello_testo]);
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle className="text-base">Modello di redazione (facoltativo)</CardTitle>
        {lavoro.modello_testo && <Badge variant="secondary">Attivo</Badge>}
      </CardHeader>
      <CardContent className="grid gap-3">
        <p className="text-sm text-muted-foreground">
          Definisci impostazione (suddivisione in paragrafi) e metodo di scrittura della bozza:
          viene seguito a ogni analisi. Incolla un testo o carica un file (PDF/DOCX/TXT), poi salva.
        </p>
        <Textarea
          value={testo}
          onChange={(e) => setTesto(e.target.value)}
          placeholder="Es. Struttura: Svolgimento del processo; Motivi della decisione. Stile: periodi brevi, sobrio…"
          className="max-h-60 min-h-28"
        />
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <input
              id="modello-file"
              type="file"
              accept=".pdf,.docx,.txt,.md"
              className="sr-only"
              disabled={estraendo}
              onChange={async (e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (!f) return;
                setEstraendo(true);
                const t = await onEstrai(f);
                if (t !== null) setTesto(t);
                setEstraendo(false);
              }}
            />
            <Button asChild type="button" variant="outline" size="sm" disabled={estraendo}>
              <Label htmlFor="modello-file" className="cursor-pointer">
                <Upload />
                Scegli file
              </Label>
            </Button>
            {estraendo && <Loader2 className="size-4 animate-spin text-muted-foreground" />}
          </div>
          <div className="flex items-center gap-2">
            {lavoro.modello_testo && (
              <Button variant="ghost" size="sm" onClick={() => onSalvaTesto("")}>
                Rimuovi
              </Button>
            )}
            <Button size="sm" onClick={() => onSalvaTesto(testo)} disabled={testo === lavoro.modello_testo}>
              <Save />
              Salva
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function MotoreCard({
  commerciale,
  onChange,
}: {
  commerciale: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <Card>
      <CardContent className="grid gap-3">
        <div className="flex items-center gap-2">
          <Checkbox
            id="commerciale"
            checked={commerciale}
            onCheckedChange={(v) => onChange(v === true)}
          />
          <Label htmlFor="commerciale" className="font-normal">
            Usa un LLM commerciale in cloud (opt-in) anziché il modello locale
          </Label>
        </div>
        {commerciale && (
          <Alert variant="destructive">
            <ShieldAlert />
            <AlertTitle>Invio a servizio esterno</AlertTitle>
            <AlertDescription>{WARNING_COMMERCIALE}</AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  );
}

function ProgressMeter({ progress }: { progress?: ProgressoTask }) {
  if (!progress || (!progress.messaggio && progress.percentuale === undefined)) return null;
  const percentuale = Math.max(0, Math.min(100, progress.percentuale ?? 0));
  const secondi =
    progress.aggiornato_at && !Number.isNaN(Date.parse(progress.aggiornato_at))
      ? Math.max(0, Math.round((Date.now() - Date.parse(progress.aggiornato_at)) / 1000))
      : null;
  return (
    <div className="grid gap-1 rounded-lg border bg-muted/20 p-3">
      <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
        <span>{progress.messaggio || progress.fase || "Elaborazione in corso"}</span>
        <span>{secondi !== null ? `${percentuale}% · ${secondi}s` : `${percentuale}%`}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${percentuale}%` }} />
      </div>
    </div>
  );
}

function PrivacyReportAlert({ report }: { report?: PrivacyReport }) {
  if (!report || report.ok) return null;
  const leak = report.leaks.slice(0, 5).map((l) => `${l.token} (${l.placeholder})`);
  const unknown = (report.unknown_pii ?? []).slice(0, 5).map((l) => `${l.token} (${l.tipo})`);
  return (
    <Alert variant="destructive">
      <ShieldAlert />
      <AlertTitle>Controllo privacy da rivedere</AlertTitle>
      <AlertDescription>
        {leak.length > 0 && <>Possibili residui: {leak.join(", ")}. </>}
        {unknown.length > 0 && <>Possibili residui non mappati: {unknown.join(", ")}. </>}
        {report.malformed_placeholders.length > 0 &&
          <>Placeholder anomali: {report.malformed_placeholders.slice(0, 3).join(", ")}. </>}
        Rivedi l'anonimizzazione prima di esportare o rilanciare analisi sensibili.
      </AlertDescription>
    </Alert>
  );
}

function WorkflowCard({ lavoro, richieste }: { lavoro: Lavoro; richieste: Richiesta[] }) {
  const c = lavoro.checklist;
  const approfondite = c.richieste_totali > 0 && c.richieste_approfondite === c.richieste_totali;
  const motivazioni = Math.max(c.motivazioni_redatte, richieste.filter((r) => r.motivazione.trim()).length);
  const passi = [
    {
      label: "Documenti",
      done: c.documenti_caricati > 0,
      current: c.documenti_caricati === 0,
      detail: `${c.documenti_caricati} caricati`,
    },
    {
      label: "Privacy",
      done: c.documenti_pronti > 0 && c.documenti_da_verificare === 0,
      current: c.documenti_caricati > 0 && c.documenti_pronti === 0,
      detail: `${c.documenti_pronti} pronti · ${c.documenti_da_verificare} da verificare`,
    },
    {
      label: "Analisi",
      done: c.analisi_completata,
      current: c.analisi_pronta && !c.analisi_completata,
      detail: c.analisi_parziale ? "Pronta con fascicolo parziale" : c.analisi_pronta ? "Pronta" : "In attesa",
    },
    {
      label: "In diritto",
      done: approfondite,
      current: c.analisi_completata && !approfondite,
      detail: `${c.richieste_approfondite}/${c.richieste_totali} richieste`,
    },
    {
      label: "Bozza",
      done: motivazioni > 0 || c.pqm_compilato,
      current: c.analisi_completata && motivazioni === 0 && !c.pqm_compilato,
      detail: `${motivazioni} motivazioni · P.Q.M. ${c.pqm_compilato ? "ok" : "vuoto"}`,
    },
  ];
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Percorso fascicolo</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 sm:grid-cols-5">
        {passi.map((p) => (
          <div
            key={p.label}
            className={cn(
              "grid min-h-24 gap-2 rounded-lg border p-3",
              p.done ? "border-primary/30 bg-primary/5" : p.current ? "border-amber-300 bg-amber-50/60 dark:bg-amber-950/20" : "bg-muted/20",
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium">{p.label}</span>
              {p.done ? (
                <CircleCheck className="size-4 text-primary" />
              ) : p.current ? (
                <Loader2 className="size-4 animate-spin text-amber-600" />
              ) : (
                <span className="size-4 rounded-full border" />
              )}
            </div>
            <p className="text-xs text-muted-foreground">{p.detail}</p>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function StatoOcr({ doc }: { doc: Documento }) {
  if (doc.stato_estrazione === "errore") return <Badge variant="destructive">Errore</Badge>;
  if (doc.stato_estrazione !== "completato")
    return (
      <Badge variant="secondary" className="gap-1">
        <Loader2 className="size-3 animate-spin" />
        Estrazione…
      </Badge>
    );
  return <Badge variant="outline">{doc.metodo_estrazione}</Badge>;
}

function SezioneCard({
  sezione,
  onUpload,
  onAccetta,
  onVerifica,
  onSalvaPrivacy,
  onRiprova,
  onElimina,
}: {
  sezione: Sezione;
  onUpload: (files: File[]) => void;
  onAccetta: (id: number) => void;
  onVerifica: (id: number) => void;
  onSalvaPrivacy: (id: number, payload: { testo_pseudonimizzato: string; mappa_entita: Record<string, string> }) => void;
  onRiprova: (id: number) => void;
  onElimina: (id: number) => void;
}) {
  const [drag, setDrag] = useState(false);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <FolderOpen className="size-4 text-muted-foreground" />
          {TITOLO_SEZIONE[sezione.tipo]}
          <Badge variant="secondary">{sezione.documenti.length}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4">
        <label
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            const fs = Array.from(e.dataTransfer.files);
            if (fs.length) onUpload(fs);
          }}
          className={cn(
            "flex cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border border-dashed p-6 text-center transition-colors",
            drag ? "border-primary bg-accent" : "hover:bg-accent/50",
          )}
        >
          <Upload className="size-5 text-muted-foreground" />
          <span className="text-sm">
            <span className="font-medium text-primary">Scegli i file</span> o trascinali qui
          </span>
          <span className="text-xs text-muted-foreground">
            PDF, scansioni, immagini o manoscritti — anche più file insieme
          </span>
          <Input
            type="file"
            multiple
            aria-label={`Carica documenti - ${TITOLO_SEZIONE[sezione.tipo]}`}
            data-testid={`upload-${sezione.tipo}`}
            className="hidden"
            onChange={(e) => {
              const fs = Array.from(e.target.files ?? []);
              if (fs.length) onUpload(fs);
              e.target.value = "";
            }}
          />
        </label>

        {sezione.documenti.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nessun documento in questa sezione.</p>
        ) : (
          <div className="grid gap-3">
            {sezione.documenti.map((d) => (
              <div key={d.id}>
                <Separator className="mb-3" />
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">{baseName(d.file)}</span>
                  <AnteprimaDocumento doc={d} />
                  <Button asChild variant="ghost" size="icon" className="size-7" aria-label="Scarica">
                    <a href={d.file} download={baseName(d.file)}>
                      <Download className="size-4" />
                    </a>
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-7 text-destructive"
                    aria-label="Elimina documento"
                    onClick={() => onElimina(d.id)}
                  >
                    <Trash2 className="size-4" />
                  </Button>
                  <StatoOcr doc={d} />
                  {d.stato_estrazione === "completato" && d.stato_anonimizzazione === "in_corso" && (
                    <Badge variant="secondary" className="gap-1">
                      <Loader2 className="size-3 animate-spin" />
                      Anonimizzazione…
                    </Badge>
                  )}
                  {d.flag_bassa_confidenza && (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Badge variant="destructive" className="gap-1">
                          <TriangleAlert className="size-3" />
                          Bassa confidenza
                        </Badge>
                      </TooltipTrigger>
                      <TooltipContent>
                        {d.passaggi_incerti.join("; ") || "Lettura dubbia: verifica il testo."}
                      </TooltipContent>
                    </Tooltip>
                  )}
                  {d.utilizzabile && (
                    <Badge className="gap-1">
                      <CircleCheck className="size-3" />
                      Accettato
                    </Badge>
                  )}
                  <span className="grow" />
                  {d.stato_anonimizzazione === "errore" ? (
                    <>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Badge variant="destructive" className="gap-1">
                            <TriangleAlert className="size-3" />
                            Anonimizzazione fallita
                          </Badge>
                        </TooltipTrigger>
                        <TooltipContent>
                          {d.errore_anonimizzazione || "Riprova l'anonimizzazione."}
                        </TooltipContent>
                      </Tooltip>
                      <Button variant="outline" size="sm" onClick={() => onRiprova(d.id)}>
                        Riprova
                      </Button>
                    </>
                  ) : (
                    d.pseudonimizzato &&
                    d.stato_accettazione === "da_verificare" && (
                      <RevisionePrivacy
                        doc={d}
                        onAccetta={onAccetta}
                        onVerifica={onVerifica}
                        onSalva={onSalvaPrivacy}
                      />
                    )
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function AnteprimaDocumento({ doc }: { doc: Documento }) {
  const url = doc.file;
  const immagine = /\.(png|jpe?g|gif|webp|bmp|tiff?)$/i.test(url);
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="ghost" size="icon" className="size-7" aria-label="Anteprima">
          <Eye className="size-4" />
        </Button>
      </DialogTrigger>
      <DialogContent className="flex h-[90vh] w-[95vw] flex-col gap-3 sm:max-w-5xl">
        <DialogHeader>
          <DialogTitle className="truncate pr-8">{baseName(url)}</DialogTitle>
        </DialogHeader>
        <div className="min-h-0 flex-1 overflow-hidden rounded-md border">
          {immagine ? (
            <img src={url} alt={baseName(url)} className="h-full w-full object-contain" />
          ) : (
            <iframe src={url} title={baseName(url)} className="h-full w-full" />
          )}
        </div>
        <a
          href={url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex shrink-0 items-center gap-1 text-sm text-primary underline-offset-4 hover:underline"
        >
          <ExternalLink className="size-3" />
          Apri in una nuova scheda
        </a>
      </DialogContent>
    </Dialog>
  );
}

function RevisionePrivacy({
  doc,
  onAccetta,
  onVerifica,
  onSalva,
}: {
  doc: Documento;
  onAccetta: (id: number) => void;
  onVerifica: (id: number) => void;
  onSalva: (id: number, payload: { testo_pseudonimizzato: string; mappa_entita: Record<string, string> }) => void;
}) {
  const [aperto, setAperto] = useState(false);
  const [testo, setTesto] = useState(doc.testo_pseudonimizzato);
  const [mappa, setMappa] = useState<Record<string, string>>(doc.mappa_entita);
  useEffect(() => {
    if (!aperto) return;
    setTesto(doc.testo_pseudonimizzato);
    setMappa(doc.mappa_entita);
  }, [aperto, doc.testo_pseudonimizzato, doc.mappa_entita]);
  const entita = Object.entries(mappa);
  const modificato = testo !== doc.testo_pseudonimizzato || JSON.stringify(mappa) !== JSON.stringify(doc.mappa_entita);
  return (
    <Dialog open={aperto} onOpenChange={setAperto}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          Rivedi anonimizzazione
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Revisione anonimizzazione</DialogTitle>
          <DialogDescription>
            Questo è il testo pseudonimizzato che vedrà l'LLM. Verifica le entità mascherate.
          </DialogDescription>
        </DialogHeader>

        <PrivacyReportAlert report={doc.privacy_report} />

        <Textarea
          value={testo}
          onChange={(e) => setTesto(e.target.value)}
          className="max-h-56 min-h-40 font-mono text-xs"
        />

        {entita.length > 0 && (
          <ScrollArea className="max-h-40 rounded-md border">
            <Table>
              <TableBody>
                {entita.map(([k, v]) => (
                  <TableRow key={k}>
                    <TableCell className="font-mono text-xs">{k}</TableCell>
                    <TableCell>
                      <Input
                        value={v}
                        onChange={(e) => setMappa((prev) => ({ ...prev, [k]: e.target.value }))}
                        className="h-8 text-sm"
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </ScrollArea>
        )}

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => {
              onAccetta(doc.id);
              setAperto(false);
            }}
          >
            Accetta senza verifica
          </Button>
          <Button
            variant="outline"
            disabled={!modificato}
            onClick={() => onSalva(doc.id, { testo_pseudonimizzato: testo, mappa_entita: mappa })}
          >
            Salva correzioni
          </Button>
          <Button
            onClick={() => {
              onVerifica(doc.id);
              setAperto(false);
            }}
          >
            Confermo, verificato
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function InterrompiButton({ onInterrompi }: { onInterrompi: () => void }) {
  return (
    <Button variant="outline" size="sm" onClick={onInterrompi}>
      <Ban />
      Interrompi
    </Button>
  );
}

function AnalisiCard({
  lavoro,
  inCorso,
  blocco,
  parziale,
  progresso,
  onAvvia,
  onInterrompi,
}: {
  lavoro: Lavoro;
  inCorso: boolean;
  blocco: string;
  parziale: boolean;
  progresso?: ProgressoTask;
  onAvvia: () => void;
  onInterrompi: () => void;
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle>Analisi</CardTitle>
        <div className="flex items-center gap-2">
          {inCorso && <InterrompiButton onInterrompi={onInterrompi} />}
          <Button onClick={onAvvia} disabled={inCorso || !!blocco}>
            {inCorso ? <Loader2 className="animate-spin" /> : <Play />}
            {inCorso ? "Analisi in corso…" : "Avvia analisi"}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="grid gap-3">
        <p className="text-sm text-muted-foreground">
          Sintetizza il fatto ed estrae le richieste delle parti. Usa solo i documenti accettati
          e pseudonimizzati.
        </p>
        {inCorso && <ProgressMeter progress={progresso} />}
        {parziale && !blocco && (
          <Alert>
            <TriangleAlert />
            <AlertTitle>Fascicolo parziale</AlertTitle>
            <AlertDescription>
              Alcuni documenti pseudonimizzati non sono ancora stati accettati. L'analisi userà solo
              quelli pronti e richiederà conferma prima di partire.
            </AlertDescription>
          </Alert>
        )}
        {blocco && (
          <Alert>
            <TriangleAlert />
            <AlertTitle>Analisi non ancora pronta</AlertTitle>
            <AlertDescription>{blocco}</AlertDescription>
          </Alert>
        )}
        {lavoro.analisi_stato === "errore" && (
          <Alert variant="destructive">
            <TriangleAlert />
            <AlertTitle>Analisi non riuscita</AlertTitle>
            <AlertDescription>{lavoro.analisi_errore}</AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  );
}

function BozzaEditor({
  bozza,
  onSalva,
  onScarica,
  onScaricaChiaro,
}: {
  bozza: Bozza;
  onSalva: (testo: string) => void;
  onScarica: () => void;
  onScaricaChiaro: () => void;
}) {
  const [testo, setTesto] = useState(bozza.in_fatto);
  const [espanso, setEspanso] = useState(false);
  useEffect(() => setTesto(bozza.in_fatto), [bozza.in_fatto, bozza.versione]);

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle>Bozza — In fatto</CardTitle>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">versione {bozza.versione}</span>
          <Button variant="ghost" size="icon-sm" onClick={() => setEspanso((v) => !v)} aria-label="Espandi editor">
            {espanso ? <Minimize2 /> : <Maximize2 />}
          </Button>
          <Button variant="outline" size="sm" onClick={onScarica}>
            <Download />
            Scarica Word
          </Button>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="outline" size="sm" onClick={onScaricaChiaro}>
                <ShieldAlert />
                In chiaro
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              Contiene i dati personali reali delle parti (de-pseudonimizzato).
            </TooltipContent>
          </Tooltip>
        </div>
      </CardHeader>
      <CardContent className="grid gap-3">
        <Textarea
          value={testo}
          onChange={(e) => setTesto(e.target.value)}
          className={cn("min-h-40 max-h-[50vh] overflow-y-auto resize-y", espanso && "min-h-[70vh] max-h-[70vh]")}
        />
        <div className="flex justify-end">
          <Button onClick={() => onSalva(testo)} disabled={testo === bozza.in_fatto}>
            <Save />
            Salva
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function MotivazioneEditor({
  richiesta,
  onSalva,
}: {
  richiesta: Richiesta;
  onSalva: (richiestaId: number, testo: string) => void;
}) {
  const [testo, setTesto] = useState(richiesta.motivazione);
  useEffect(() => setTesto(richiesta.motivazione), [richiesta.motivazione]);
  return (
    <div className="grid gap-2">
      <p className="text-sm font-medium">Motivazione (in diritto)</p>
      <Textarea
        value={testo}
        onChange={(e) => setTesto(e.target.value)}
        placeholder="Redigi qui la motivazione su questa domanda…"
        className="min-h-28"
      />
      <div className="flex justify-end">
        <Button size="sm" onClick={() => onSalva(richiesta.id, testo)} disabled={testo === richiesta.motivazione}>
          <Save />
          Salva motivazione
        </Button>
      </div>
    </div>
  );
}

function PqmEditor({ bozza, onSalva }: { bozza: Bozza; onSalva: (testo: string) => void }) {
  const [testo, setTesto] = useState(bozza.pqm);
  useEffect(() => setTesto(bozza.pqm), [bozza.pqm, bozza.versione]);
  return (
    <Card>
      <CardHeader>
        <CardTitle>P.Q.M.</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        <Textarea
          value={testo}
          onChange={(e) => setTesto(e.target.value)}
          placeholder="Compila il dispositivo…"
          className="min-h-28"
        />
        <div className="flex justify-end">
          <Button onClick={() => onSalva(testo)} disabled={testo === bozza.pqm}>
            <Save />
            Salva
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function RichiesteSection({
  lavoro,
  richieste,
  nomiAllegati,
  inCorso,
  progresso,
  onApprofondisci,
  onInterrompi,
  onSalvaMotivazione,
}: {
  lavoro: Lavoro;
  richieste: Richiesta[];
  nomiAllegati: Record<number, string>;
  inCorso: boolean;
  progresso?: ProgressoTask;
  onApprofondisci: () => void;
  onInterrompi: () => void;
  onSalvaMotivazione: (richiestaId: number, testo: string) => void;
}) {
  const approfondite = richieste.filter((r) => r.stato === "approfondita").length;
  return (
    <div className="grid gap-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold tracking-tight">Richieste delle parti</h2>
        <div className="flex items-center gap-2">
          {inCorso && <InterrompiButton onInterrompi={onInterrompi} />}
          <Button variant="outline" onClick={onApprofondisci} disabled={inCorso}>
            {inCorso ? <Loader2 className="animate-spin" /> : <Scale />}
            {inCorso ? "Approfondimento in corso…" : "Approfondisci in diritto"}
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="secondary">{richieste.length} richieste</Badge>
        <Badge variant="outline">{approfondite} approfondite</Badge>
        <Badge variant="outline">
          {richieste.reduce((n, r) => n + r.allegati_collegati.length, 0)} allegati collegati
        </Badge>
        <Badge variant="outline">
          {richieste.reduce((n, r) => n + r.quesiti_aperti.length, 0)} quesiti aperti
        </Badge>
      </div>

      {inCorso && <ProgressMeter progress={progresso} />}

      {richieste.length > 0 && approfondite < richieste.length && (
        <Alert>
          <HelpCircle />
          <AlertTitle>Griglia in estrazione base</AlertTitle>
          <AlertDescription>
            Le domande sono state individuate, ma onere probatorio, allegati pertinenti,
            non contestazioni e quesiti completi arrivano con l'approfondimento in diritto.
          </AlertDescription>
        </Alert>
      )}

      {lavoro.approfondimento_stato === "errore" && (
        <Alert variant="destructive">
          <TriangleAlert />
          <AlertTitle>Approfondimento non riuscito</AlertTitle>
          <AlertDescription>{lavoro.approfondimento_errore}</AlertDescription>
        </Alert>
      )}

      {richieste.length === 0 && (
        <p className="text-sm text-muted-foreground">Nessuna richiesta estratta dall'analisi.</p>
      )}

      <Accordion type="multiple" className="grid gap-2">
        {richieste.map((r, i) => (
          <AccordionItem key={r.id} value={String(r.id)} className="rounded-lg border px-4">
            <AccordionTrigger>
              <span className="flex items-center gap-2">
                <span className="text-muted-foreground">{i + 1}.</span>
                <Badge variant="secondary" className="capitalize">
                  {r.parte_richiedente}
                </Badge>
                <Badge variant={r.tipo === "riconvenzionale" ? "default" : "outline"}>
                  {TIPO_RICHIESTA[r.tipo]}
                </Badge>
                <Badge variant={r.confidence < 0.55 ? "destructive" : "outline"}>
                  {Math.round((r.confidence ?? 0) * 100)}%
                </Badge>
                <span className="text-left font-normal">{r.testo}</span>
              </span>
            </AccordionTrigger>
            <AccordionContent className="grid gap-4">
              {r.avvisi.length > 0 &&
                r.avvisi.map((avviso, k) => (
                  <Alert key={k} variant="destructive">
                    <TriangleAlert />
                    <AlertTitle>Da rivedere</AlertTitle>
                    <AlertDescription>{avviso}</AlertDescription>
                  </Alert>
                ))}

              <MotivazioneEditor richiesta={r} onSalva={onSalvaMotivazione} />

              <Separator />
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Elementi di supporto (oggettivi)
              </p>

              {r.onere_probatorio && (
                <div className="grid gap-1">
                  <p className="text-sm font-medium">Onere probatorio</p>
                  <p className="text-sm text-muted-foreground">{r.onere_probatorio}</p>
                </div>
              )}

              {r.non_contestazioni.length > 0 && (
                <div className="grid gap-1">
                  <p className="text-sm font-medium">Non contestazioni</p>
                  <ul className="ml-4 list-disc text-sm text-muted-foreground">
                    {r.non_contestazioni.map((nc, k) => (
                      <li key={k}>{nc}</li>
                    ))}
                  </ul>
                </div>
              )}

              {r.allegati_collegati.length > 0 && (
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">Allegati collegati:</span>
                  {r.allegati_collegati.map((aid) => (
                    <Badge key={aid} variant="outline">
                      {nomiAllegati[aid] ?? `doc ${aid}`}
                    </Badge>
                  ))}
                </div>
              )}

              {r.quesiti_aperti.length === 0 ? (
                <p className="text-sm text-muted-foreground">Nessun quesito aperto.</p>
              ) : (
                r.quesiti_aperti.map((q, k) => (
                  <Alert key={k}>
                    <HelpCircle />
                    <AlertTitle>Da decidere — verifica tu</AlertTitle>
                    <AlertDescription>{q}</AlertDescription>
                  </Alert>
                ))
              )}
            </AccordionContent>
          </AccordionItem>
        ))}
      </Accordion>
    </div>
  );
}

function RicercaCard({
  lavoro,
  spunti,
  inCorso,
  progresso,
  onCercaWeb,
  onInterrompi,
  onManuale,
}: {
  lavoro: Lavoro;
  spunti: Spunto[];
  inCorso: boolean;
  progresso?: ProgressoTask;
  onCercaWeb: () => void;
  onInterrompi: () => void;
  onManuale: (argomento: string, materiale: string) => void;
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle>Spunti di approfondimento giuridico</CardTitle>
        <div className="flex items-center gap-2">
          {inCorso && <InterrompiButton onInterrompi={onInterrompi} />}
          <RicercaManuale onManuale={onManuale} />
          <Button onClick={onCercaWeb} disabled={inCorso}>
            {inCorso ? <Loader2 className="animate-spin" /> : <Search />}
            {inCorso ? "Ricerca in corso…" : "Cerca sul web"}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="grid gap-3">
        <p className="text-sm text-muted-foreground">
          Suggerimenti da valutare, non citazioni definitive. La query esce sempre pseudonimizzata.
        </p>
        {inCorso && <ProgressMeter progress={progresso} />}
        {lavoro.ricerca_stato === "errore" && (
          <Alert variant="destructive">
            <TriangleAlert />
            <AlertTitle>Ricerca non riuscita</AlertTitle>
            <AlertDescription>{lavoro.ricerca_errore}</AlertDescription>
          </Alert>
        )}
        {spunti.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Nessuno spunto. Avvia una ricerca o incolla dei risultati.
          </p>
        ) : (
          <div className="grid gap-2">
            {spunti.map((sp) => (
              <div key={sp.id} className="rounded-lg border p-3">
                <div className="flex items-center gap-2">
                  <Badge variant="secondary">{sp.origine}</Badge>
                  <Badge
                    variant={
                      sp.fonte_affidabilita === "insufficiente"
                        ? "destructive"
                        : sp.fonte_affidabilita === "alta"
                          ? "default"
                          : sp.fonte_affidabilita === "bassa"
                            ? "destructive"
                            : "outline"
                    }
                  >
                    {sp.fonte_label}
                  </Badge>
                  <span className="text-sm font-medium">{sp.argomento || "Spunto"}</span>
                </div>
                <p className="mt-2 text-sm text-muted-foreground">{sp.sintesi}</p>
                {sp.suggerimento && (
                  <p className="mt-1 text-sm">
                    <span className="font-medium">Suggerimento: </span>
                    {sp.suggerimento}
                  </p>
                )}
                {sp.fonte && (
                  <a
                    href={sp.fonte}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-2 inline-flex items-center gap-1 text-sm text-primary underline-offset-4 hover:underline"
                  >
                    <ExternalLink className="size-3" />
                    Fonte
                  </a>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function RicercaManuale({
  onManuale,
}: {
  onManuale: (argomento: string, materiale: string) => void;
}) {
  const [aperto, setAperto] = useState(false);
  const [argomento, setArgomento] = useState("");
  const [materiale, setMateriale] = useState("");
  return (
    <Dialog open={aperto} onOpenChange={setAperto}>
      <DialogTrigger asChild>
        <Button variant="outline">
          <ClipboardPaste />
          Incolla risultati
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Incolla i risultati di ricerca</DialogTitle>
          <DialogDescription>
            Incolla massime o estratti trovati altrove: l'assistente ne ricava uno spunto.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <div className="grid gap-2">
            <Label htmlFor="argomento">Argomento (facoltativo)</Label>
            <Input id="argomento" value={argomento} onChange={(e) => setArgomento(e.target.value)} />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="materiale">Risultati</Label>
            <Textarea
              id="materiale"
              value={materiale}
              onChange={(e) => setMateriale(e.target.value)}
              className="min-h-32"
            />
          </div>
        </div>
        <DialogFooter>
          <Button
            disabled={!materiale.trim()}
            onClick={() => {
              onManuale(argomento.trim(), materiale.trim());
              setArgomento("");
              setMateriale("");
              setAperto(false);
            }}
          >
            Crea spunto
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
