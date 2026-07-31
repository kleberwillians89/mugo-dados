import { useEffect, useState, type FormEvent } from "react";
import type { Session } from "@supabase/supabase-js";
import { enableLocalAuth, getSupabaseBootstrapError, isLocalAuthAvailable, supabase } from "../app/supabase";
import { INTEGRATION_REGISTRY } from "../app/integrationRegistry";
import "../styles/Login.css";

const logo = "/mugo_logo1.png";

const AUTH_DEBUG = import.meta.env.DEV && import.meta.env.VITE_AUTH_DEBUG === "true";

const PRODUCT_NAME = "Mugô Dados";
const PANEL_NAME = "Inteligência para decisões mais claras";

function maskEmail(value: string | null | undefined): string {
  const email = String(value || "").trim();
  if (!email) return "";
  const [name, domain = ""] = email.split("@");
  if (!domain) return `${email.slice(0, 2)}***`;
  const prefix = name.length <= 2 ? `${name[0] || ""}*` : `${name.slice(0, 2)}***`;
  return `${prefix}@${domain}`;
}

function authLoginDebug(event: string, payload?: Record<string, unknown>) {
  if (!AUTH_DEBUG) return;
  if (payload) {
    console.info(`[auth-login] ${event}`, payload);
    return;
  }
  console.info(`[auth-login] ${event}`);
}

function toErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === "string" && error.trim()) return error;
  return "Erro inesperado no login.";
}

function withEmailHint(message: string): string {
  const msg = message.toLowerCase();
  if (msg.includes("email not confirmed") || msg.includes("invalid login credentials")) {
    return `${message} Confira se esse e-mail ja foi cadastrado no Supabase Auth.`;
  }
  if (msg.includes("smtp") || msg.includes("email provider")) {
    return [
      message,
      "No Supabase, confirme se o provider de e-mail esta habilitado e se o SMTP esta configurado.",
    ].join(" ");
  }
  return message;
}

type Props = {
  initialError?: string | null;
  authChecking?: boolean;
  onPasswordLoginSuccess?: (session: Session | null) => Promise<void> | void;
  onLocalLogin?: () => void;
};

export default function Login({
  initialError = null,
  authChecking = false,
  onPasswordLoginSuccess,
  onLocalLogin,
}: Props) {
  const authConfigError = getSupabaseBootstrapError();
  const [passwordLoading, setPasswordLoading] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirmation, setPasswordConfirmation] = useState("");
  const [mode, setMode] = useState<"login" | "recover" | "set-password">(() => {
    const values = `${window.location.search}&${window.location.hash}`;
    return values.includes("type=recovery") || values.includes("type=invite")
      ? "set-password"
      : "login";
  });
  const [info, setInfo] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!initialError) return;
    authLoginDebug("initial_error.updated", { initialError });
    setErr(initialError);
  }, [initialError]);

  async function onPasswordLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (passwordLoading || authChecking) return;

    if (!supabase || authConfigError) {
      setErr(authConfigError || "Supabase Auth nao esta configurado no frontend.");
      return;
    }

    const cleanEmail = email.trim();
    const cleanPassword = password.trim();

    if (!cleanEmail || !cleanPassword) {
      setErr("Informe e-mail e senha para continuar.");
      return;
    }

    setErr(null);
    setInfo(null);
    setPasswordLoading(true);

    try {
      const existing = await supabase.auth.getSession();
      if (existing.error) {
        authLoginDebug("precheck.getSession.error", {
          message: existing.error.message,
        });
      }

      const existingEmail = existing.data.session?.user?.email || null;
      const switchingUser =
        Boolean(existingEmail) &&
        String(existingEmail).toLowerCase() !== cleanEmail.toLowerCase();

      authLoginDebug("sign_in.attempt", {
        email: maskEmail(cleanEmail),
        hasExistingSession: !!existing.data.session,
        existingSessionEmail: maskEmail(existingEmail),
        switchingUser,
      });

      if (switchingUser) {
        const signOutBeforeSwitch = await supabase.auth.signOut();
        authLoginDebug("sign_in.pre_signout_switch_user", {
          email: maskEmail(cleanEmail),
          ok: !signOutBeforeSwitch.error,
          error: signOutBeforeSwitch.error?.message || null,
        });
      }

      const { data, error } = await supabase.auth.signInWithPassword({
        email: cleanEmail,
        password: cleanPassword,
      });

      if (error) {
        authLoginDebug("sign_in.error", {
          email: maskEmail(cleanEmail),
          message: error.message,
        });
        throw error;
      }

      authLoginDebug("sign_in.success", {
        email: maskEmail(cleanEmail),
        hasSession: !!data.session,
        userId: data.session?.user?.id || null,
      });

      setInfo("Login realizado com sucesso. Carregando o painel do cliente ativo...");
      await onPasswordLoginSuccess?.(data.session ?? null);
    } catch (error: unknown) {
      const message = withEmailHint(toErrorMessage(error));
      authLoginDebug("sign_in.catch", {
        email: maskEmail(cleanEmail),
        message,
      });
      setErr(message);
    } finally {
      setPasswordLoading(false);
    }
  }

  async function onRecoverPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!supabase || authConfigError) {
      setErr(authConfigError || "Supabase Auth não está configurado.");
      return;
    }
    const cleanEmail = email.trim();
    if (!cleanEmail) {
      setErr("Informe seu e-mail.");
      return;
    }
    setPasswordLoading(true);
    setErr(null);
    const redirectTo = `${window.location.origin}/?type=recovery`;
    const { error } = await supabase.auth.resetPasswordForEmail(cleanEmail, { redirectTo });
    setPasswordLoading(false);
    if (error) {
      setErr(withEmailHint(error.message));
      return;
    }
    setInfo("Se o e-mail estiver cadastrado, você receberá o link de redefinição.");
  }

  async function onSetPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!supabase || authConfigError) {
      setErr(authConfigError || "Supabase Auth não está configurado.");
      return;
    }
    if (password.length < 10) {
      setErr("A nova senha deve ter ao menos 10 caracteres.");
      return;
    }
    if (password !== passwordConfirmation) {
      setErr("As senhas não coincidem.");
      return;
    }
    setPasswordLoading(true);
    setErr(null);
    const { error } = await supabase.auth.updateUser({ password });
    setPasswordLoading(false);
    if (error) {
      setErr(error.message);
      return;
    }
    window.history.replaceState({}, document.title, "/");
    setInfo("Senha definida com sucesso. Você já pode entrar.");
    setPassword("");
    setPasswordConfirmation("");
    setMode("login");
  }

  const authUnavailable = Boolean(authConfigError);
  const inputDisabled = passwordLoading || authChecking || authUnavailable;
  const visibleError = err || authConfigError;
  const localAuthAvailable = isLocalAuthAvailable();

  function handleLocalLogin() {
    enableLocalAuth();
    setErr(null);
    setInfo("Modo local ativo. Abrindo o painel do cliente ativo...");
    onLocalLogin?.();
  }

  return (
    <div className="loginPage">
      <div className="loginShell">
        <section className="loginBrandPanel" aria-label="Apresentacao da marca Mugô Dados">
          <div className="loginBrandTopLogo">
            <img
              className="loginTopLogo"
              src={logo}
              alt="Mugô Dados"
            />
          </div>

          <div className="loginBrandCopy">
            <div className="loginBrandEyebrow">{PANEL_NAME}</div>
            <h1>{PRODUCT_NAME}</h1>
            <p className="loginBrandLead">
              Performance, mídia e comércio em uma visão confiável para cada empresa.
            </p>
          </div>

          <div className="loginEcosystem" aria-label="Ecossistema de integrações">
            {INTEGRATION_REGISTRY.map((provider) => (
              <div className="loginEcosystemItem" key={provider.id}>
                <span aria-hidden="true">{provider.shortName.slice(0, 2).toUpperCase()}</span>
                <div>
                  <strong>{provider.name}</strong>
                  <small>{provider.resources[0]}</small>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="loginCard">
          <div className="loginCardInner">
            
            <h2 className="loginTitle">Entrar no workspace</h2>
            <p className="loginSubtitle">
              Use seu acesso enviado pela Mugô Dados para abrir o painel privado.
            </p>

            {visibleError ? <div className="loginError">{visibleError}</div> : null}
            {info ? <div className="loginInfo">{info}</div> : null}

            <form
              onSubmit={
                mode === "recover"
                  ? onRecoverPassword
                  : mode === "set-password"
                    ? onSetPassword
                    : onPasswordLogin
              }
            >
              {mode !== "set-password" ? (
              <div>
                <label className="loginFieldLabel" htmlFor="email">
                  E-mail
                </label>
                <input
                  id="email"
                  type="email"
                  placeholder="mugo.agencia@gmail.com"
                  autoComplete="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  disabled={inputDisabled}
                  required
                />
              </div>
              ) : null}

              {mode !== "recover" ? <div>
                <label className="loginFieldLabel" htmlFor="password">
                  {mode === "set-password" ? "Nova senha" : "Senha"}
                </label>
                <input
                  id="password"
                  type="password"
                  placeholder="Sua senha"
                  autoComplete={mode === "set-password" ? "new-password" : "current-password"}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  disabled={inputDisabled}
                  required
                />
              </div> : null}

              {mode === "set-password" ? (
                <div>
                  <label className="loginFieldLabel" htmlFor="password-confirmation">
                    Confirmar nova senha
                  </label>
                  <input
                    id="password-confirmation"
                    type="password"
                    autoComplete="new-password"
                    value={passwordConfirmation}
                    onChange={(event) => setPasswordConfirmation(event.target.value)}
                    disabled={inputDisabled}
                    required
                  />
                </div>
              ) : null}

              <button type="submit" disabled={inputDisabled}>
                {authUnavailable
                  ? "Configuracao pendente"
                  : passwordLoading || authChecking
                    ? "Processando..."
                    : mode === "recover"
                      ? "Enviar link seguro"
                      : mode === "set-password"
                        ? "Definir senha"
                        : "Entrar no painel"}
              </button>
            </form>

            {mode === "login" ? (
              <button className="loginLocalButton" type="button" onClick={() => setMode("recover")}>
                Esqueci minha senha
              </button>
            ) : mode === "recover" ? (
              <button className="loginLocalButton" type="button" onClick={() => setMode("login")}>
                Voltar ao login
              </button>
            ) : null}

            {localAuthAvailable ? (
              <button
                className="loginLocalButton"
                type="button"
                onClick={handleLocalLogin}
                disabled={passwordLoading || authChecking}
              >
                Entrar em modo local
              </button>
            ) : null}

            <div className="loginHint">
              Usuarios e senhas precisam ser provisionados no Supabase Auth antes do
              primeiro acesso.
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
