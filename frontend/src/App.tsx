import { Suspense, lazy, useEffect, useState, type ReactNode } from "react";
import { Link, Navigate, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom";
import { Moon, ShieldAlert, Sun } from "lucide-react";
import { api } from "@/api";
import type { HealthAi, Utente } from "@/types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

const Login = lazy(() => import("@/pages/Login").then((m) => ({ default: m.Login })));
const Lavori = lazy(() => import("@/pages/Lavori").then((m) => ({ default: m.Lavori })));
const LavoroDettaglio = lazy(() =>
  import("@/pages/LavoroDettaglio").then((m) => ({ default: m.LavoroDettaglio })),
);
const Corpus = lazy(() => import("@/pages/Corpus").then((m) => ({ default: m.Corpus })));
const Conoscenza = lazy(() =>
  import("@/pages/Conoscenza").then((m) => ({ default: m.Conoscenza })),
);

const WARNING_GDPR =
  "Il Privacy Filter esegue pseudonimizzazione, non anonimizzazione: ai fini del GDPR il dato " +
  "pseudonimizzato resta dato personale. Non è una garanzia di conformità.";

function NavLink({ to, children }: { to: string; children: ReactNode }) {
  const { pathname } = useLocation();
  const attivo = to === "/" ? pathname === "/" : pathname.startsWith(to);
  return (
    <Button asChild variant={attivo ? "secondary" : "ghost"} size="sm">
      <Link to={to}>{children}</Link>
    </Button>
  );
}

function DettaglioRoute() {
  const { id } = useParams();
  const navigate = useNavigate();
  return <LavoroDettaglio id={Number(id)} onIndietro={() => navigate("/")} />;
}

function TemaToggle() {
  const [scuro, setScuro] = useState(() => localStorage.getItem("tema") === "dark");
  useEffect(() => {
    document.documentElement.classList.toggle("dark", scuro);
    localStorage.setItem("tema", scuro ? "dark" : "light");
  }, [scuro]);
  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={() => setScuro((s) => !s)}
      aria-label={scuro ? "Passa al tema chiaro" : "Passa al tema scuro"}
    >
      {scuro ? <Sun /> : <Moon />}
    </Button>
  );
}

export function App() {
  const [utente, setUtente] = useState<Utente | null>(null);
  const [health, setHealth] = useState<HealthAi | null>(null);
  const [pronto, setPronto] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    api
      .get<Utente>("/auth/me/")
      .then(setUtente)
      .catch(() => setUtente(null))
      .finally(() => setPronto(true));
  }, []);

  useEffect(() => {
    if (!utente) {
      setHealth(null);
      return;
    }
    api
      .get<HealthAi>("/health/ai/")
      .then(setHealth)
      .catch(() => setHealth(null));
  }, [utente]);

  async function logout() {
    await api.post("/auth/logout/");
    setUtente(null);
    navigate("/");
  }

  if (!pronto) return null;

  return (
    <TooltipProvider>
      <div className="min-h-dvh bg-background text-foreground">
        <header className="border-b">
          <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-3 px-4 py-3">
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-3 sm:gap-6">
              <Link to="/" className="shrink-0 text-xl tracking-tight">
                <span className="font-bold">UPP</span>
                <span className="font-light">ilot</span>
              </Link>
              {utente && (
                <nav className="order-last flex w-full items-center gap-1 overflow-x-auto sm:order-none sm:w-auto">
                  <NavLink to="/">Lavori</NavLink>
                  <NavLink to="/corpus">Corpus</NavLink>
                  <NavLink to="/conoscenza">Conoscenza</NavLink>
                </nav>
              )}
            </div>
            <div className="ml-auto flex shrink-0 items-center gap-2">
              <TemaToggle />
              {utente && (
                <>
                  <span className="hidden text-sm text-muted-foreground sm:inline">{utente.username}</span>
                  <Button variant="ghost" size="sm" onClick={logout}>
                    Esci
                  </Button>
                </>
              )}
            </div>
          </div>
        </header>

        <main className="mx-auto max-w-5xl px-4 py-8">
          <Alert className="mb-8">
            <ShieldAlert />
            <AlertTitle>Trattamento dati personali</AlertTitle>
            <AlertDescription>{WARNING_GDPR}</AlertDescription>
          </Alert>

          {utente && health && !health.ok && (
            <Alert variant="destructive" className="mb-8">
              <ShieldAlert />
              <AlertTitle>Ambiente locale da verificare</AlertTitle>
              <AlertDescription>
                {Object.entries(health.checks)
                  .filter(([, c]) => !c.ok)
                  .map(([nome, c]) => `${nome}: ${c.detail}`)
                  .join(" · ")}
                {health.hint ? ` ${health.hint}` : ""}
              </AlertDescription>
            </Alert>
          )}

          <Suspense fallback={<div className="h-32 animate-pulse rounded-md bg-muted" />}>
            {!utente ? (
              <Login onLogin={setUtente} />
            ) : (
              <Routes>
                <Route path="/" element={<Lavori />} />
                <Route path="/lavori/:id" element={<DettaglioRoute />} />
                <Route path="/corpus" element={<Corpus />} />
                <Route path="/conoscenza" element={<Conoscenza />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            )}
          </Suspense>
        </main>
      </div>
      <Toaster richColors />
    </TooltipProvider>
  );
}
