import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  CircleCheck,
  ClipboardPaste,
  Download,
  Eye,
  ExternalLink,
  FolderOpen,
  HelpCircle,
  Loader2,
  Play,
  Save,
  Scale,
  Search,
  ShieldAlert,
  TriangleAlert,
  Upload,
} from "lucide-react";
import { api, ApiError } from "@/api";
import type { Bozza, Documento, Lavoro, Richiesta, Sezione, Spunto } from "@/types";
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

const baseName = (p: string) => decodeURIComponent(p.split("/").pop() || p);
const isTerminale = (s: string) => s === "completata" || s === "errore";

type Pending = { analisi?: boolean; approf?: boolean; ricerca?: boolean };

export function LavoroDettaglio({ id, onIndietro }: { id: number; onIndietro: () => void }) {
  const [lavoro, setLavoro] = useState<Lavoro | null>(null);
  const [bozza, setBozza] = useState<Bozza | null>(null);
  const [richieste, setRichieste] = useState<Richiesta[]>([]);
  const [spunti, setSpunti] = useState<Spunto[]>([]);
  const [commerciale, setCommerciale] = useState(false);
  const [pending, setPending] = useState<Pending>({});

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

  // Quando un'operazione raggiunge uno stato terminale, sgancia il "pending".
  useEffect(() => {
    if (!lavoro) return;
    setPending((p) => ({
      analisi: isTerminale(lavoro.analisi_stato) ? false : p.analisi,
      approf: isTerminale(lavoro.approfondimento_stato) ? false : p.approf,
      ricerca: isTerminale(lavoro.ricerca_stato) ? false : p.ricerca,
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
      if (!esito) setPending((p) => ({ ...p, [chiave]: false }));
    },
    [azione],
  );

  if (!lavoro) return <Skeletons />;

  const s = statoLavoro(lavoro.stato);
  const daAccettare = lavoro.sezioni.some((sez) =>
    sez.documenti.some((d) => d.pseudonimizzato && d.stato_accettazione === "da_verificare"),
  );
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
            onRiprova={(d) =>
              azione(() => api.post(`/documenti/${d}/ripseudonimizza/`), "Anonimizzazione riavviata")
            }
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

      <MotoreCard commerciale={commerciale} onChange={setCommerciale} />

      <AnalisiCard
        lavoro={lavoro}
        inCorso={analisiInCorso}
        onAvvia={() => avvia("analisi", () => api.post(`/lavori/${id}/analizza/`, { commerciale }), "Analisi avviata")}
      />

      {bozza && (
        <BozzaEditor
          bozza={bozza}
          onScarica={() =>
            azione(() => api.download(`/lavori/${id}/esporta/`, `bozza_${id}.docx`), "Documento scaricato")
          }
          onScaricaChiaro={() =>
            azione(
              () => api.download(`/lavori/${id}/esporta/?chiaro=1`, `bozza_${id}_in_chiaro.docx`),
              "Documento in chiaro scaricato",
            )
          }
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
          onApprofondisci={() =>
            avvia("approf", () => api.post(`/lavori/${id}/approfondisci/`, { commerciale }), "Approfondimento avviato")
          }
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
  onRiprova,
}: {
  sezione: Sezione;
  onUpload: (files: File[]) => void;
  onAccetta: (id: number) => void;
  onVerifica: (id: number) => void;
  onRiprova: (id: number) => void;
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
                      <RevisionePrivacy doc={d} onAccetta={onAccetta} onVerifica={onVerifica} />
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
}: {
  doc: Documento;
  onAccetta: (id: number) => void;
  onVerifica: (id: number) => void;
}) {
  const [aperto, setAperto] = useState(false);
  const entita = Object.entries(doc.mappa_entita);
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

        <ScrollArea className="max-h-48 rounded-md border p-3">
          <p className="whitespace-pre-wrap text-sm">{doc.testo_pseudonimizzato || "—"}</p>
        </ScrollArea>

        {entita.length > 0 && (
          <ScrollArea className="max-h-40 rounded-md border">
            <Table>
              <TableBody>
                {entita.map(([k, v]) => (
                  <TableRow key={k}>
                    <TableCell className="font-mono text-xs">{k}</TableCell>
                    <TableCell className="text-sm">{v}</TableCell>
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

function AnalisiCard({
  lavoro,
  inCorso,
  onAvvia,
}: {
  lavoro: Lavoro;
  inCorso: boolean;
  onAvvia: () => void;
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle>Analisi</CardTitle>
        <Button onClick={onAvvia} disabled={inCorso}>
          {inCorso ? <Loader2 className="animate-spin" /> : <Play />}
          {inCorso ? "Analisi in corso…" : "Avvia analisi"}
        </Button>
      </CardHeader>
      <CardContent className="grid gap-3">
        <p className="text-sm text-muted-foreground">
          Sintetizza il fatto ed estrae le richieste delle parti. Usa solo i documenti accettati
          e pseudonimizzati.
        </p>
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
  useEffect(() => setTesto(bozza.in_fatto), [bozza.in_fatto, bozza.versione]);

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle>Bozza — In fatto</CardTitle>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">versione {bozza.versione}</span>
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
        <Textarea value={testo} onChange={(e) => setTesto(e.target.value)} className="min-h-40" />
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
  onApprofondisci,
  onSalvaMotivazione,
}: {
  lavoro: Lavoro;
  richieste: Richiesta[];
  nomiAllegati: Record<number, string>;
  inCorso: boolean;
  onApprofondisci: () => void;
  onSalvaMotivazione: (richiestaId: number, testo: string) => void;
}) {
  return (
    <div className="grid gap-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold tracking-tight">Richieste delle parti</h2>
        <Button variant="outline" onClick={onApprofondisci} disabled={inCorso}>
          {inCorso ? <Loader2 className="animate-spin" /> : <Scale />}
          {inCorso ? "Approfondimento in corso…" : "Approfondisci in diritto"}
        </Button>
      </div>

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
                <span className="text-left font-normal">{r.testo}</span>
              </span>
            </AccordionTrigger>
            <AccordionContent className="grid gap-4">
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
  onCercaWeb,
  onManuale,
}: {
  lavoro: Lavoro;
  spunti: Spunto[];
  inCorso: boolean;
  onCercaWeb: () => void;
  onManuale: (argomento: string, materiale: string) => void;
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle>Spunti di approfondimento giuridico</CardTitle>
        <div className="flex items-center gap-2">
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
