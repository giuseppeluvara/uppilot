import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Graph from "graphology";
import Sigma from "sigma";
import forceAtlas2 from "graphology-layout-forceatlas2";
import louvain from "graphology-communities-louvain";
import circular from "graphology-layout/circular";
import { Ban, Loader2, Network, RefreshCw, Search, Trash2, X } from "lucide-react";
import { api, ApiError } from "@/api";
import type { ArcoGrafo, Grafo, NodoGrafo, StatoGrafo } from "@/types";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Toggle } from "@/components/ui/toggle";

const CHART_TOKENS = ["--chart-1", "--chart-2", "--chart-3", "--chart-4", "--chart-5"];
const FALLBACK_PALETTE = ["#2563eb", "#059669", "#d97706", "#7c3aed", "#dc2626", "#0891b2"];

const TIPO_LABEL: Record<NodoGrafo["tipo"], string> = {
  concetto: "Concetto/istituto",
  riferimento: "Riferimento normativo",
  caso: "Caso/fascicolo",
};

const ARCO_LABEL: Record<ArcoGrafo["tipo"], string> = {
  cita: "cita",
  correlato: "correlato",
  in_contrasto: "in contrasto",
  applica: "applica",
};

export function Conoscenza() {
  const [grafo, setGrafo] = useState<Grafo | null>(null);
  const [stato, setStato] = useState<StatoGrafo | null>(null);
  const [selezionato, setSelezionato] = useState<number | null>(null);
  const [tipiAttivi, setTipiAttivi] = useState<Set<NodoGrafo["tipo"]>>(
    new Set(["concetto", "riferimento", "caso"]),
  );
  const [query, setQuery] = useState("");
  const [costruendo, setCostruendo] = useState(false);
  const [scope, setScope] = useState<"tutto" | "corpus" | "fascicoli" | "lavoro">("tutto");
  const [lavoroId, setLavoroId] = useState("");

  const container = useRef<HTMLDivElement>(null);
  const sigma = useRef<Sigma | null>(null);

  const carica = useCallback(async () => {
    try {
      const [g, s] = await Promise.all([
        api.get<Grafo>("/grafo/"),
        api.get<StatoGrafo>("/grafo/stato/"),
      ]);
      setGrafo(g);
      setStato(s);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Errore di caricamento.");
    }
  }, []);

  useEffect(() => {
    carica();
  }, [carica]);

  const perId = useMemo(() => {
    const m = new Map<number, NodoGrafo>();
    grafo?.nodi.forEach((n) => m.set(n.id, n));
    return m;
  }, [grafo]);

  const nodoSelezionato = selezionato !== null ? perId.get(selezionato) ?? null : null;

  const risultatiRicerca = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q || !grafo) return [];
    return grafo.nodi
      .filter((n) => {
        const testo = [n.etichetta, n.sintesi, n.documento_titolo, n.snippet].join(" ").toLowerCase();
        return tipiAttivi.has(n.tipo) && testo.includes(q);
      })
      .slice(0, 8);
  }, [query, grafo, tipiAttivi]);

  const vicini = useMemo(() => {
    if (selezionato === null || !grafo) return [];
    const out: { nodo: NodoGrafo; relazione: ArcoGrafo["tipo"] }[] = [];
    for (const e of grafo.archi) {
      if (e.da === selezionato && perId.has(e.a)) out.push({ nodo: perId.get(e.a)!, relazione: e.tipo });
      else if (e.a === selezionato && perId.has(e.da)) out.push({ nodo: perId.get(e.da)!, relazione: e.tipo });
    }
    return out;
  }, [selezionato, grafo, perId]);

  // (Ri)costruisce il renderer quando cambiano il grafo o i filtri.
  useEffect(() => {
    if (!grafo || !container.current) return;
    sigma.current?.kill();
    sigma.current = null;

    const nodiVisibili = grafo.nodi.filter((n) => tipiAttivi.has(n.tipo));
    if (nodiVisibili.length === 0) return;

    const g = new Graph();
    for (const n of nodiVisibili) {
      g.addNode(String(n.id), { label: n.etichetta, size: 4, x: Math.random(), y: Math.random() });
    }
    for (const e of grafo.archi) {
      const da = String(e.da);
      const a = String(e.a);
      if (g.hasNode(da) && g.hasNode(a) && da !== a && !g.hasEdge(da, a)) {
        g.addEdge(da, a, { size: 1, color: "#cbd5e1" });
      }
    }
    g.forEachNode((node) => g.setNodeAttribute(node, "size", 4 + Math.sqrt(g.degree(node)) * 2.2));
    circular.assign(g);
    forceAtlas2.assign(g, { iterations: 120, settings: forceAtlas2.inferSettings(g) });
    louvain.assign(g);
    const styles = getComputedStyle(document.documentElement);
    const coloreUsabile = (value: string) => /^(#|rgb|hsl)/i.test(value);
    const palette = CHART_TOKENS.map((token) => styles.getPropertyValue(token).trim()).filter(coloreUsabile);
    if (palette.length < 3) palette.splice(0, palette.length, ...FALLBACK_PALETTE);
    const edgeColor = coloreUsabile(styles.getPropertyValue("--border").trim())
      ? styles.getPropertyValue("--border").trim()
      : "#cbd5e1";
    const labelColor = coloreUsabile(styles.getPropertyValue("--muted-foreground").trim())
      ? styles.getPropertyValue("--muted-foreground").trim()
      : "#475569";
    g.forEachNode((node, attrs) =>
      g.setNodeAttribute(node, "color", palette[((attrs.community as number) ?? 0) % palette.length]),
    );

    const renderer = new Sigma(g, container.current, {
      renderEdgeLabels: false,
      defaultEdgeColor: edgeColor,
      labelColor: { color: labelColor },
      labelDensity: 0.35,
      labelRenderedSizeThreshold: 8,
    });
    renderer.on("clickNode", ({ node }) => setSelezionato(Number(node)));
    renderer.on("clickStage", () => setSelezionato(null));
    sigma.current = renderer;

    return () => {
      renderer.kill();
      sigma.current = null;
    };
  }, [grafo, tipiAttivi]);

  function centraNodo(trovato: NodoGrafo | undefined) {
    if (!sigma.current) return;
    if (!trovato) {
      toast.error("Nessun nodo trovato.");
      return;
    }
    setSelezionato(trovato.id);
    const pos = sigma.current.getNodeDisplayData(String(trovato.id));
    if (pos) sigma.current.getCamera().animate({ x: pos.x, y: pos.y, ratio: 0.4 }, { duration: 500 });
  }

  function centra(query: string) {
    if (!query.trim() || !grafo || !sigma.current) return;
    centraNodo(risultatiRicerca[0]);
  }

  async function aggiorna() {
    const lavoro = Number(lavoroId);
    if (scope === "lavoro" && (!Number.isInteger(lavoro) || lavoro <= 0)) {
      toast.error("Inserisci un ID fascicolo valido.");
      return;
    }
    setCostruendo(true);
    try {
      await api.post("/grafo/costruisci/", scope === "lavoro" ? { scope, lavoro_id: lavoro } : { scope });
      toast.info("Costruzione del grafo avviata…");
      for (let i = 0; i < 120; i++) {
        await new Promise((r) => setTimeout(r, 3000));
        const s = await api.get<StatoGrafo>("/grafo/stato/");
        setStato(s);
        if (!s.in_corso) break;
      }
      await carica();
      toast.success("Grafo aggiornato");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Operazione non riuscita.");
    } finally {
      setCostruendo(false);
    }
  }

  async function annulla() {
    try {
      await api.post("/grafo/annulla/");
      setCostruendo(false);
      await carica();
      toast.success("Costruzione interrotta");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Operazione non riuscita.");
    }
  }

  async function elimina(id: number) {
    try {
      await api.del(`/grafo/nodo/${id}/`);
      setSelezionato(null);
      await carica();
      toast.success("Nodo eliminato");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Operazione non riuscita.");
    }
  }

  function toggleTipo(t: NodoGrafo["tipo"]) {
    setTipiAttivi((prev) => {
      const next = new Set(prev);
      next.has(t) ? next.delete(t) : next.add(t);
      return next;
    });
  }

  const vuoto = grafo !== null && grafo.nodi.length === 0;
  const costruzioneAttiva = costruendo || Boolean(stato?.in_corso);
  const progresso = stato?.progresso;

  return (
    <div className="grid gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Grafo della conoscenza</h1>
        <p className="text-sm text-muted-foreground">
          Mappa navigabile di istituti, riferimenti normativi e casi (anonimizzati) ricavata dal
          corpus. È un ausilio alla consultazione, non una fonte di conclusioni.
        </p>
      </div>

      <Card>
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-3 space-y-0">
          <CardTitle className="text-base">
            {grafo ? `${grafo.nodi.length} nodi · ${grafo.archi.length} relazioni` : "Grafo"}
          </CardTitle>
          <div className="flex flex-wrap items-center gap-2">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                centra(query);
              }}
              className="relative"
            >
              <Search className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Cerca un nodo…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="h-9 w-48 pl-8"
              />
            </form>
            <select
              value={scope}
              onChange={(e) => setScope(e.target.value as "tutto" | "corpus" | "fascicoli" | "lavoro")}
              className="h-9 rounded-md border bg-background px-2 text-sm"
              aria-label="Ambito costruzione grafo"
              disabled={costruzioneAttiva}
            >
              <option value="tutto">Tutto</option>
              <option value="corpus">Solo corpus</option>
              <option value="fascicoli">Solo fascicoli</option>
              <option value="lavoro">Singolo fascicolo</option>
            </select>
            {scope === "lavoro" && (
              <Input
                value={lavoroId}
                onChange={(e) => setLavoroId(e.target.value)}
                inputMode="numeric"
                placeholder="ID fascicolo"
                className="h-9 w-28"
                disabled={costruzioneAttiva}
              />
            )}
            {costruzioneAttiva && (
              <Button variant="outline" onClick={annulla}>
                <Ban />
                Interrompi
              </Button>
            )}
            <Button onClick={aggiorna} disabled={costruzioneAttiva}>
              {costruzioneAttiva ? <Loader2 className="animate-spin" /> : <RefreshCw />}
              {costruzioneAttiva ? "Costruzione…" : "Aggiorna grafo"}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="grid gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-muted-foreground">Mostra:</span>
            {(["concetto", "riferimento", "caso"] as const).map((t) => (
              <Toggle
                key={t}
                size="sm"
                pressed={tipiAttivi.has(t)}
                onPressedChange={() => toggleTipo(t)}
              >
                {TIPO_LABEL[t]}
              </Toggle>
            ))}
            <span className="ml-auto text-xs text-muted-foreground">
              Colori = cluster tematici · dimensione = connessioni
            </span>
          </div>

          {costruzioneAttiva && progresso && (
            <div className="grid gap-1 rounded-lg border bg-muted/20 p-3">
              <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
                <span>{progresso.messaggio || "Costruzione del grafo in corso"}</span>
                <span>{progresso.percentuale ?? 0}%</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-primary transition-all"
                  style={{ width: `${Math.max(0, Math.min(100, progresso.percentuale ?? 0))}%` }}
                />
              </div>
            </div>
          )}

          {stato?.changelog && stato.changelog.length > 0 && (
            <div className="rounded-lg border p-3">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Ultimi aggiornamenti
              </p>
              <div className="mt-2 grid gap-1 text-sm">
                {stato.changelog.slice(-6).map((r, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <Badge variant={r.stato === "errore" ? "destructive" : "outline"}>{r.stato}</Badge>
                    <span className="text-muted-foreground">{r.evento}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {vuoto ? (
            <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed py-16 text-center">
              <Network className="size-8 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">
                Grafo vuoto. Popola il <strong>Corpus</strong>, poi premi “Aggiorna grafo”.
              </p>
            </div>
          ) : (
            <div className="grid gap-3 lg:grid-cols-[1fr_18rem]">
              <div ref={container} className="h-[70vh] w-full rounded-lg border bg-muted/20" />
              <div className="grid gap-3">
                {query.trim() && (
                  <div className="rounded-lg border p-3">
                    <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Risultati ricerca
                    </p>
                    {risultatiRicerca.length === 0 ? (
                      <p className="mt-2 text-sm text-muted-foreground">Nessun nodo trovato.</p>
                    ) : (
                      <div className="mt-2 grid gap-1">
                        {risultatiRicerca.map((n) => (
                          <button
                            key={n.id}
                            onClick={() => centraNodo(n)}
                            className={cn(
                              "rounded-md px-2 py-1 text-left text-sm hover:bg-accent",
                              selezionato === n.id && "bg-accent",
                            )}
                          >
                            <span className="block font-medium">{n.etichetta}</span>
                            <span className="text-xs text-muted-foreground">{TIPO_LABEL[n.tipo]}</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}
                {nodoSelezionato ? (
                  <div className="rounded-lg border p-3">
                  <div className="flex items-start justify-between gap-2">
                    <Badge variant="secondary">{TIPO_LABEL[nodoSelezionato.tipo]}</Badge>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-7"
                      aria-label="Chiudi"
                      onClick={() => setSelezionato(null)}
                    >
                      <X className="size-4" />
                    </Button>
                  </div>
                  <p className="mt-2 font-medium">{nodoSelezionato.etichetta}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <Badge variant="outline">{nodoSelezionato.origine}</Badge>
                    {nodoSelezionato.documento_titolo && (
                      <span className="text-xs text-muted-foreground">{nodoSelezionato.documento_titolo}</span>
                    )}
                  </div>
                  {nodoSelezionato.sintesi && (
                    <p className="mt-1 text-sm text-muted-foreground">{nodoSelezionato.sintesi}</p>
                  )}
                  {nodoSelezionato.snippet && nodoSelezionato.snippet !== nodoSelezionato.sintesi && (
                    <p className="mt-2 rounded-md bg-muted/40 p-2 text-xs text-muted-foreground">
                      {nodoSelezionato.snippet}
                    </p>
                  )}
                  {vicini.length > 0 && (
                    <>
                      <Separator className="my-3" />
                      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        Collegamenti
                      </p>
                      <ScrollArea className="mt-1 max-h-48">
                        <div className="grid gap-1 pr-2">
                          {vicini.map((v, i) => (
                            <button
                              key={i}
                              onClick={() => setSelezionato(v.nodo.id)}
                              className="rounded-md px-2 py-1 text-left text-sm hover:bg-accent"
                            >
                              <span className="text-muted-foreground">{ARCO_LABEL[v.relazione]} → </span>
                              {v.nodo.etichetta}
                            </button>
                          ))}
                        </div>
                      </ScrollArea>
                    </>
                  )}
                  <Separator className="my-3" />
                  <Button
                    variant="outline"
                    size="sm"
                    className="w-full text-destructive"
                    onClick={() => elimina(nodoSelezionato.id)}
                  >
                    <Trash2 className="size-4" />
                    Elimina nodo
                  </Button>
                  </div>
                ) : (
                  <div className="hidden rounded-lg border border-dashed p-3 text-sm text-muted-foreground lg:block">
                    Clicca un nodo per vederne il dettaglio e i collegamenti.
                  </div>
                )}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
