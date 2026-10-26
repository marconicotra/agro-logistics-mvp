import { useEffect, useState, type FormEvent } from "react";
import { Outlet } from "react-router-dom";

import { supabaseClient } from "./supabase";

export function AuthGate() {
  const [ready, setReady] = useState(!supabaseClient);
  const [signedIn, setSignedIn] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!supabaseClient) return;
    void supabaseClient.auth.getSession().then(({ data }) => {
      setSignedIn(Boolean(data.session));
      setReady(true);
    });
    const { data } = supabaseClient.auth.onAuthStateChange((_event, session) => {
      setSignedIn(Boolean(session));
      setReady(true);
    });
    return () => data.subscription.unsubscribe();
  }, []);

  const signIn = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!supabaseClient) return;
    setBusy(true);
    setError(null);
    const { error: signInError } = await supabaseClient.auth.signInWithPassword({ email, password });
    if (signInError) setError("No se pudo iniciar sesión. Revisá el correo y la contraseña.");
    setBusy(false);
  };

  if (!supabaseClient) {
    return import.meta.env.DEV
      ? <Outlet />
      : <main className="auth-shell"><section className="panel"><h1>Acceso no configurado</h1><p>La autenticación del backoffice todavía no está conectada.</p></section></main>;
  }
  if (!ready) return <main className="auth-shell"><section className="panel">Verificando sesión…</section></main>;
  if (!signedIn) {
    return (
      <main className="auth-shell">
        <form className="panel auth-panel" onSubmit={signIn}>
          <h1>AGRO Logistics</h1>
          <p>Ingresá con tu usuario autorizado.</p>
          <label>Correo<input className="text-input" type="email" autoComplete="username" required value={email} onChange={(event) => setEmail(event.target.value)} /></label>
          <label>Contraseña<input className="text-input" type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} /></label>
          {error ? <div className="state-box error">{error}</div> : null}
          <button className="primary-button" type="submit" disabled={busy}>{busy ? "Ingresando…" : "Ingresar"}</button>
        </form>
      </main>
    );
  }
  return <Outlet />;
}
