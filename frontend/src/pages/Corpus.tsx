import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Plus, Search } from "lucide-react";
import { api, ApiError } from "@/api";
import type { DocumentoCorpus, RisultatoCorpus } from "@/types";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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

  const carica = useCallback(async () => {
    try {
      setDocumenti(await api.get<DocumentoCorpus[]>("/corpus/"));
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Errore di caricamento.");
    }
  }, []);

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
                    <TableHead className="text-right">Frammenti</TableHead>
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
                        <TableCell className="text-right">{d.n_frammenti}</TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
