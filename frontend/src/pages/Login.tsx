import { useState } from "react";
import { api, ensureCsrf, ApiError } from "@/api";
import type { Utente } from "@/types";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function Login({ onLogin }: { onLogin: (u: Utente) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [errore, setErrore] = useState("");
  const [attesa, setAttesa] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErrore("");
    setAttesa(true);
    try {
      await ensureCsrf();
      onLogin(await api.post<Utente>("/auth/login/", { username, password }));
    } catch (err) {
      setErrore(err instanceof ApiError ? err.message : "Errore di accesso.");
    } finally {
      setAttesa(false);
    }
  }

  return (
    <Card className="mx-auto w-full max-w-sm">
      <CardHeader>
        <CardTitle>Accedi</CardTitle>
        <CardDescription>Entra con le tue credenziali per iniziare.</CardDescription>
      </CardHeader>
      <form onSubmit={submit}>
        <CardContent className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="username">Utente</Label>
            <Input
              id="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
              autoComplete="username"
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </div>
          {errore && (
            <Alert variant="destructive">
              <AlertDescription>{errore}</AlertDescription>
            </Alert>
          )}
        </CardContent>
        <CardFooter className="mt-6">
          <Button type="submit" className="w-full" disabled={attesa}>
            {attesa ? "Accesso…" : "Entra"}
          </Button>
        </CardFooter>
      </form>
    </Card>
  );
}
