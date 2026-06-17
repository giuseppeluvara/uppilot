import type { Lavoro } from "@/types";

type BadgeVariant = "default" | "secondary" | "destructive" | "outline";

// Etichette e varianti per lo stato del lavoro (nomi riconoscibili dall'operatore).
const STATO_LAVORO: Record<string, { label: string; variant: BadgeVariant }> = {
  bozza_in_corso: { label: "Bozza in corso", variant: "secondary" },
  analizzato: { label: "Analizzato", variant: "secondary" },
  bozza_generata: { label: "Bozza generata", variant: "default" },
  in_revisione: { label: "In revisione", variant: "default" },
  completato: { label: "Completato", variant: "outline" },
};

export function statoLavoro(stato: Lavoro["stato"]) {
  return STATO_LAVORO[stato] ?? { label: stato, variant: "secondary" as const };
}
