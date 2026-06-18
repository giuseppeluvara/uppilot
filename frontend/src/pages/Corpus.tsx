import { useCallback, useEffect, useRef, useState } from "react";
import { Layers, Loader2, Plus, Search, Trash2 } from "lucide-react";
import { api, ApiError } from "@/api";
import type { DocumentoCorpus, FrammentoCorpus, RisultatoCorpus } from "@/types";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

type BadgeVariant = "default" | "secondary" | "destructive" | "outline";

const STATO: Record<DocumentoCorpus["stato"], { label: string; variant: BadgeVariant }> = {
  in_attesa: { label: "In attesa", variant: "secondary" },
  in_corso: { label: "Indicizzazione…", variant: "secondary" },
  completato: { label: "Indicizzato", variant: "outline" },
  errore: { label: "Errore", variant: "destructive" },
};

export function Corpus() {
  const [documenti, setDocumenti] = useState<DocumentoCorpus[]>([]);
  const [titolo, setTitolo] = useState("");
  const [fonte, setFonte] = useState("");
  const [categoria, setCategoria] = useState("");
  const [testo, setTesto] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [filtroCat, setFiltroCat] = useState("");
  const [query, setQuery] = useState("");
  const [risultati, setRisultati] = useState<RisultatoCorpus[] | null>(null);
  const [cercando, setCercando] = useState(false);
  // Vista frammenti di un documento del corpus.
  const [frammentiDi, setFrammentiDi] = useState<DocumentoCorpus | null>(null);
  const [frammenti, setFrammenti] = useState<FrammentoCorpus[] | null>(null);

  const carica = useCallback(async () => {
    try {
      setDocumenti(await api.get<DocumentoCorpus[]>("/corpus/"));
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Errore di caricamento.");
    }
  }, []);

  async function apriFrammenti(d: DocumentoCorpus) {
    setFrammentiDi(d);
    setFrammenti(null);
    try {
      setFrammenti(await api.get<FrammentoCorpus[]>(`/corpus/${d.id}/frammenti/`));
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Errore di caricamento.");
    }
  }

  async function eliminaFrammento(id: number) {
    try {
      await api.del(`/corpus/frammenti/${id}/`);
      setFrammenti((f) => (f ? f.filter((x) => x.id !== id) : f));
      toast.success("Frammento eliminato");
      await carica();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Operazione non riuscita.");
    }
  }

  async function eliminaDocumento(d: DocumentoCorpus) {
    if (!confirm(`Eliminare "${d.titolo}" e tutti i suoi frammenti?`)) return;
    try {
      await api.del(`/corpus/${d.id}/`);
      toast.success("Documento eliminato dal corpus");
      await carica();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Operazione non riuscita.");
    }
  }

  useEffect(() => {
    carica();
  }, [carica]);

  // Polling mentre un documento è in indicizzazione.
  const timer = useRef<number>(undefined);
  useEffect(() => {
    if (documenti.some((d) => d.stato === "in_attesa" || d.stato === "in_corso")) {
      timer.current = window.setTimeout(carica, 3000);
      return () => window.clearTimeout(timer.current);
    }
  }, [documenti, carica]);

  async function aggiungi(e: React.FormEvent) {
    e.preventDefault();
    if (!testo.trim() && !file) return;
    try {
      const form = new FormData();
      if (titolo) form.append("titolo", titolo);
      if (fonte) form.append("fonte", fonte);
      if (categoria) form.append("categoria", categoria);
      if (file) form.append("file", file);
      else form.append("testo", testo);
      await api.upload("/corpus/ingest/", form);
      setTitolo("");
      setFonte("");
      setCategoria("");
      setTesto("");
      setFile(null);
      toast.success("Documento aggiunto al corpus");
      await carica();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Operazione non riuscita.");
    }
  }

  const documentiFiltrati = filtroCat.trim()
    ? documenti.filter((d) => d.categoria.toLowerCase().includes(filtroCat.trim().toLowerCase()))
    : documenti;

  async function cerca(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setCercando(true);
    try {
      const params = new URLSearchParams({ q: query, k: "5" });
      setRisultati(await api.get<RisultatoCorpus[]>(`/corpus/cerca/?${params}`));
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Ricerca non riuscita.");
    } finally {
      setCercando(false);
    }
  }

  return (
    <div className="grid gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Corpus di riferimento</h1>
        <p className="text-sm text-muted-foreground">
          Base di conoscenza locale (giurisprudenza, normativa) per la ricerca semantica a supporto
          dell'analisi. Resta tutto in locale.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Aggiungi un documento</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={aggiungi} className="grid gap-3">
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="grid gap-2">
                <Label htmlFor="titolo">Titolo</Label>
                <Input id="titolo" value={titolo} onChange={(e) => setTitolo(e.target.value)} />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="fonte">Fonte (facoltativo)</Label>
                <Input id="fonte" value={fonte} onChange={(e) => setFonte(e.target.value)} />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="categoria">Categoria (facoltativo)</Label>
                <Input
                  id="categoria"
                  placeholder="es. giurisprudenza, codice civile…"
                  value={categoria}
                  onChange={(e) => setCategoria(e.target.value)}
                />
              </div>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="testo">Testo {file && <span className="text-muted-foreground">(ignorato: caricato un file)</span>}</Label>
              <Textarea
                id="testo"
                value={testo}
                onChange={(e) => setTesto(e.target.value)}
                disabled={!!file}
                className="min-h-32"
              />
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Input
                type="file"
                accept=".pdf,.txt,.md"
                className="w-auto"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
              <Button type="submit" disabled={!testo.trim() && !file}>
                <Plus />
                Aggiungi al corpus
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Ricerca semantica</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          <form onSubmit={cerca} className="flex items-center gap-2">
            <Input
              placeholder="Cerca per concetto, non per parola esatta…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <Button type="submit" disabled={cercando || !query.trim()}>
              {cercando ? <Loader2 className="animate-spin" /> : <Search />}
              Cerca
            </Button>
          </form>

          {risultati !== null &&
            (risultati.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nessun risultato.</p>
            ) : (
              <div className="grid gap-2">
                {risultati.map((r, i) => (
                  <div key={i} className="rounded-lg border p-3">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline">distanza {r.distanza.toFixed(3)}</Badge>
                      <span className="text-sm font-medium">{r.titolo}</span>
                    </div>
                    <p className="mt-2 text-sm text-muted-foreground">{r.testo}</p>
                  </div>
                ))}
              </div>
            ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Documenti nel corpus</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          {documenti.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Il corpus è vuoto. Aggiungi il primo documento per iniziare.
            </p>
          ) : (
            <>
              <Input
                placeholder="Filtra per categoria…"
                value={filtroCat}
                onChange={(e) => setFiltroCat(e.target.value)}
                className="sm:w-72"
              />
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Titolo</TableHead>
                    <TableHead>Categoria</TableHead>
                    <TableHead>Fonte</TableHead>
                    <TableHead>Stato</TableHead>
                    <TableHead>Frammenti</TableHead>
                    <TableHead className="w-0" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {documentiFiltrati.map((d) => {
                    const st = STATO[d.stato];
                    return (
                      <TableRow key={d.id}>
                        <TableCell className="font-medium">{d.titolo}</TableCell>
                        <TableCell>
                          {d.categoria ? <Badge variant="outline">{d.categoria}</Badge> : "—"}
                        </TableCell>
                        <TableCell className="text-muted-foreground">{d.fonte || "—"}</TableCell>
                        <TableCell>
                          <Badge variant={st.variant}>{st.label}</Badge>
                        </TableCell>
                        <TableCell>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 gap-1"
                            disabled={!d.n_frammenti}
                            onClick={() => apriFrammenti(d)}
                          >
                            <Layers className="size-3.5" />
                            {d.n_frammenti}
                          </Button>
                        </TableCell>
                        <TableCell className="text-right">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="size-7 text-destructive"
                            aria-label="Elimina documento"
                            onClick={() => eliminaDocumento(d)}
                          >
                            <Trash2 className="size-4" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </>
          )}
        </CardContent>
      </Card>

      <Dialog open={frammentiDi !== null} onOpenChange={(o) => !o && setFrammentiDi(null)}>
        <DialogContent className="flex max-h-[85vh] w-[95vw] flex-col gap-3 sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle className="truncate pr-8">Frammenti — {frammentiDi?.titolo}</DialogTitle>
          </DialogHeader>
          {frammenti === null ? (
            <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              Caricamento…
            </div>
          ) : frammenti.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              Nessun frammento (eliminati tutti o non ancora indicizzato).
            </p>
          ) : (
            <ScrollArea className="min-h-0 flex-1">
              <div className="grid gap-2 pr-3">
                {frammenti.map((f) => (
                  <div key={f.id} className="rounded-lg border p-3">
                    <div className="flex items-center justify-between gap-2">
                      <Badge variant="secondary">#{f.ordine + 1}</Badge>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-7 text-destructive"
                        aria-label="Elimina frammento"
                        onClick={() => eliminaFrammento(f.id)}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                    <p className="mt-1 whitespace-pre-wrap text-sm text-muted-foreground">{f.testo}</p>
                  </div>
                ))}
              </div>
            </ScrollArea>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
