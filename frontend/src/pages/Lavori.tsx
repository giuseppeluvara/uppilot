import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronRight, FileUp, FolderOpen, Plus, Search, Sparkles, Trash2 } from "lucide-react";
import { api, ApiError } from "@/api";
import type { Lavoro } from "@/types";
import { statoLavoro } from "@/lib/stato";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export function Lavori() {
  const navigate = useNavigate();
  const [lavori, setLavori] = useState<Lavoro[]>([]);
  const [titolo, setTitolo] = useState("");
  const [filtro, setFiltro] = useState("");
  const [caricamento, setCaricamento] = useState(true);
  const [lavoroDaEliminare, setLavoroDaEliminare] = useState<Lavoro | null>(null);
  const [eliminazione, setEliminazione] = useState(false);
  const cercaRef = useRef<HTMLInputElement>(null);
  const importRef = useRef<HTMLInputElement>(null);

  async function ricarica() {
    setLavori(await api.get<Lavoro[]>("/storico/"));
    setCaricamento(false);
  }
  useEffect(() => {
    ricarica();
  }, []);

  // Scorciatoia: "/" porta il focus sulla ricerca (se non si sta già scrivendo).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement;
      if (e.key === "/" && !["INPUT", "TEXTAREA"].includes(t.tagName)) {
        e.preventDefault();
        cercaRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const lavoriFiltrati = lavori.filter((l) =>
    l.titolo.toLowerCase().includes(filtro.trim().toLowerCase()),
  );

  function apri(id: number) {
    navigate(`/lavori/${id}`);
  }

  async function crea(e: React.FormEvent) {
    e.preventDefault();
    if (!titolo.trim()) return;
    const l = await api.post<Lavoro>("/lavori/", { titolo });
    setTitolo("");
    apri(l.id);
  }

  async function creaDemo(tipo: "civile" | "penale") {
    try {
      const l = await api.post<Lavoro>("/lavori/demo/", { tipo });
      toast.success("Fascicolo demo creato");
      apri(l.id);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Demo non creabile.");
    }
  }

  async function importaBackup(file: File) {
    try {
      const payload = JSON.parse(await file.text());
      const l = await api.post<Lavoro>("/lavori/importa-backup/", payload);
      toast.success("Backup importato");
      apri(l.id);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Backup non valido.");
    }
  }

  async function eliminaConfermato() {
    if (!lavoroDaEliminare) return;
    setEliminazione(true);
    try {
      await api.del(`/lavori/${lavoroDaEliminare.id}/`);
      setLavori((correnti) => correnti.filter((l) => l.id !== lavoroDaEliminare.id));
      toast.success("Lavoro eliminato");
      setLavoroDaEliminare(null);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Eliminazione non riuscita.");
    } finally {
      setEliminazione(false);
    }
  }

  return (
    <div className="grid gap-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Lavori</h1>
          <p className="text-sm text-muted-foreground">
            Crea un nuovo lavoro o riprendi uno dall'archivio.
          </p>
        </div>
        <div className="grid gap-2">
          <form onSubmit={crea} className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <Input
              placeholder="Titolo del nuovo lavoro"
              value={titolo}
              onChange={(e) => setTitolo(e.target.value)}
              className="sm:w-64"
            />
            <Button type="submit">
              <Plus />
              Nuovo lavoro
            </Button>
          </form>
          <div className="flex flex-wrap justify-end gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => creaDemo("civile")}>
              <Sparkles />
              Demo civile
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={() => creaDemo("penale")}>
              <Sparkles />
              Demo penale
            </Button>
            <input
              ref={importRef}
              type="file"
              accept=".json,application/json"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file) void importaBackup(file);
              }}
            />
            <Button type="button" variant="outline" size="sm" onClick={() => importRef.current?.click()}>
              <FileUp />
              Importa backup
            </Button>
          </div>
        </div>
      </div>

      <Card>
        <CardContent className="grid gap-4">
          {!caricamento && lavori.length > 0 && (
            <div className="relative">
              <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                ref={cercaRef}
                placeholder="Cerca per titolo…  ( / )"
                value={filtro}
                onChange={(e) => setFiltro(e.target.value)}
                className="pl-9"
              />
            </div>
          )}
          {caricamento ? (
            <div className="grid gap-3">
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-2/3" />
            </div>
          ) : lavori.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-12 text-center">
              <FolderOpen className="size-8 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">
                Nessun lavoro. Crea il primo per iniziare.
              </p>
            </div>
          ) : lavoriFiltrati.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              Nessun lavoro corrisponde a “{filtro}”.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <Table className="w-max min-w-full">
                <TableHeader>
                  <TableRow>
                    <TableHead>Titolo</TableHead>
                    <TableHead>Stato</TableHead>
                    <TableHead>Aggiornato</TableHead>
                    <TableHead className="w-0">Azioni</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {lavoriFiltrati.map((l) => {
                    const s = statoLavoro(l.stato);
                    return (
                      <TableRow
                        key={l.id}
                        onClick={() => apri(l.id)}
                        tabIndex={0}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            apri(l.id);
                          }
                        }}
                        className="cursor-pointer"
                      >
                        <TableCell className="font-medium">{l.titolo}</TableCell>
                        <TableCell>
                          <Badge variant={s.variant}>{s.label}</Badge>
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {new Date(l.updated_at).toLocaleString("it-IT")}
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-1">
                            <Button
                              variant="ghost"
                              size="icon"
                              aria-label={`Elimina ${l.titolo}`}
                              onClick={(e) => {
                                e.stopPropagation();
                                setLavoroDaEliminare(l);
                              }}
                            >
                              <Trash2 />
                            </Button>
                            <ChevronRight className="size-4 text-muted-foreground" />
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={lavoroDaEliminare !== null} onOpenChange={(o) => !o && setLavoroDaEliminare(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Eliminare il lavoro?</DialogTitle>
            <DialogDescription>
              “{lavoroDaEliminare?.titolo}” e tutti i documenti collegati verranno rimossi definitivamente.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setLavoroDaEliminare(null)} disabled={eliminazione}>
              Annulla
            </Button>
            <Button variant="destructive" onClick={eliminaConfermato} disabled={eliminazione}>
              <Trash2 />
              {eliminazione ? "Eliminazione…" : "Elimina"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
