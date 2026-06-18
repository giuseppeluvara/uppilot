import { useEffect, useState, type ReactNode } from "react";
import { Link, Navigate, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom";
import { Moon, ShieldAlert, Sun } from "lucide-react";
import { api } from "@/api";
import type { Utente } from "@/types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Login } from "@/pages/Login";
import { Lavori } from "@/pages/Lavori";
import { LavoroDettaglio } from "@/pages/LavoroDettaglio";
import { Corpus } from "@/pages/Corpus";
import { Conoscenza } from "@/pages/Conoscenza";

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
  const [pronto, setPronto] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    api
      .get<Utente>("/auth/me/")
      .then(setUtente)
      .catch(() => setUtente(null))
      .finally(() => setPronto(true));
  }, []);

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
          <div className="mx-auto flex max-w-4xl items-center justify-between px-4 py-3">
            <div className="flex items-center gap-6">
              <Link to="/" className="text-xl tracking-tight">
                <span className="font-bold">UPP</span>
                <span className="font-light">ilot</span>
              </Link>
              {utente && (
                <nav className="flex items-center gap-1">
                  <NavLink to="/">Lavori</NavLink>
                  <NavLink to="/corpus">Corpus</NavLink>
                  <NavLink to="/conoscenza">Conoscenza</NavLink>
                </nav>
              )}
            </div>
            <div className="flex items-center gap-2">
              <TemaToggle />
              {utente && (
                <>
                  <span className="text-sm text-muted-foreground">{utente.username}</span>
                  <Button variant="ghost" size="sm" onClick={logout}>
                    Esci
                  </Button>
                </>
              )}
            </div>
          </div>
        </header>

        <main className="mx-auto max-w-4xl px-4 py-8">
          <Alert className="mb-8">
            <ShieldAlert />
            <AlertTitle>Trattamento dati personali</AlertTitle>
            <AlertDescription>{WARNING_GDPR}</AlertDescription>
          </Alert>

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
        </main>
      </div>
      <Toaster richColors />
    </TooltipProvider>
  );
}
