import { useEffect, useState, type FormEvent } from "react";
import type { Session } from "@supabase/supabase-js";
import { enableLocalAuth, getSupabaseBootstrapError, isLocalAuthAvailable, supabase } from "../app/supabase";
import AuthFrame from "../components/auth/AuthFrame";

const AUTH_DEBUG = import.meta.env.DEV && import.meta.env.VITE_AUTH_DEBUG === "true";

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

/**
 * Mensagem para quem está entrando: em português e sem nomes internos de
 * infraestrutura. Mesmas condições de antes; só o texto exibido mudou.
 */
function withEmailHint(message: string): string {
  const msg = message.toLowerCase();
  if (msg.includes("invalid login credentials")) return "E-mail ou senha incorretos.";
  if (msg.includes("email not confirmed")) return "Confirme seu e-mail antes de entrar.";
  if (msg.includes("smtp") || msg.includes("email provider")) {
    return "Não foi possível enviar o e-mail agora. Tente novamente em alguns minutos.";
  }
  return message;
}

export type LoginMode = "login" | "recover" | "set-password";

export type LoginViewProps = {
  mode: LoginMode;
  email: string;
  password: string;
  passwordConfirmation: string;
  onEmailChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
  onPasswordConfirmationChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onModeChange: (mode: LoginMode) => void;
  error: string | null;
  info: string | null;
  busy: boolean;
  inputDisabled: boolean;
  authUnavailable: boolean;
  localAuthAvailable: boolean;
  onLocalLogin: () => void;
};

const MODE_TITLE: Record<LoginMode, string> = {
  login: "Acesse sua conta",
  recover: "Redefinir senha",
  "set-password": "Defina sua senha",
};

const MODE_SUBMIT: Record<LoginMode, { idle: string; busy: string }> = {
  login: { idle: "Entrar", busy: "Entrando..." },
  recover: { idle: "Enviar link de redefinição", busy: "Enviando..." },
  "set-password": { idle: "Definir senha", busy: "Salvando..." },
};

/** Tela de acesso: o produto, uma frase e o formulário. Nada de clientes, logos de terceiros ou ilustrações. */
export function LoginView({
  mode,
  email,
  password,
  passwordConfirmation,
  onEmailChange,
  onPasswordChange,
  onPasswordConfirmationChange,
  onSubmit,
  onModeChange,
  error,
  info,
  busy,
  inputDisabled,
  authUnavailable,
  localAuthAvailable,
  onLocalLogin,
}: LoginViewProps) {
  const submitLabel = authUnavailable ? "Configuração pendente" : busy ? MODE_SUBMIT[mode].busy : MODE_SUBMIT[mode].idle;

  return (
    <AuthFrame labelledBy="login-title">
      <h1 id="login-title" className="loginTitle">{MODE_TITLE[mode]}</h1>
      {mode === "recover" ? (
        <p className="loginLead">Informe o e-mail da sua conta para receber o link de redefinição.</p>
      ) : null}

      {error ? <p className="loginMessage is-error" role="alert">{error}</p> : null}
      {info ? <p className="loginMessage" role="status">{info}</p> : null}

      <form className="loginForm" onSubmit={onSubmit}>
        {mode !== "set-password" ? (
          <div className="loginField">
            <label htmlFor="email">E-mail</label>
            <input
              id="email"
              type="email"
              placeholder="nome@empresa.com.br"
              autoComplete="email"
              value={email}
              onChange={(event) => onEmailChange(event.target.value)}
              disabled={inputDisabled}
              required
            />
          </div>
        ) : null}

        {mode !== "recover" ? (
          <div className="loginField">
            <label htmlFor="password">{mode === "set-password" ? "Nova senha" : "Senha"}</label>
            <input
              id="password"
              type="password"
              autoComplete={mode === "set-password" ? "new-password" : "current-password"}
              value={password}
              onChange={(event) => onPasswordChange(event.target.value)}
              disabled={inputDisabled}
              required
            />
          </div>
        ) : null}

        {mode === "set-password" ? (
          <div className="loginField">
            <label htmlFor="password-confirmation">Confirmar nova senha</label>
            <input
              id="password-confirmation"
              type="password"
              autoComplete="new-password"
              value={passwordConfirmation}
              onChange={(event) => onPasswordConfirmationChange(event.target.value)}
              disabled={inputDisabled}
              required
            />
          </div>
        ) : null}

        <button className="loginSubmit" type="submit" disabled={inputDisabled}>
          {submitLabel}
        </button>
      </form>

      <div className="loginSecondary">
        {mode === "login" ? (
          <button className="loginTextButton" type="button" onClick={() => onModeChange("recover")}>
            Esqueci minha senha
          </button>
        ) : mode === "recover" ? (
          <button className="loginTextButton" type="button" onClick={() => onModeChange("login")}>
            Voltar para o acesso
          </button>
        ) : null}
        {localAuthAvailable ? (
          <button className="loginTextButton" type="button" onClick={onLocalLogin} disabled={busy}>
            Entrar em modo local
          </button>
        ) : null}
      </div>

      {/* Redação pendente de validação jurídica: os Termos de Uso ainda não foram publicados. */}
      <p className="loginConsent" data-legal-status="review-pending">
        Ao continuar, você concorda com os <a href="/termos-de-uso">Termos de Uso</a> e a{" "}
        <a href="/privacidade">Política de Privacidade</a>.
      </p>
    </AuthFrame>
  );
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
  const [mode, setMode] = useState<LoginMode>(() => {
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

      setInfo("Acesso confirmado. Carregando...");
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

  function handleLocalLogin() {
    enableLocalAuth();
    setErr(null);
    setInfo("Modo local ativo. Carregando...");
    onLocalLogin?.();
  }

  return (
    <LoginView
      mode={mode}
      email={email}
      password={password}
      passwordConfirmation={passwordConfirmation}
      onEmailChange={setEmail}
      onPasswordChange={setPassword}
      onPasswordConfirmationChange={setPasswordConfirmation}
      onSubmit={mode === "recover" ? onRecoverPassword : mode === "set-password" ? onSetPassword : onPasswordLogin}
      onModeChange={setMode}
      error={visibleError}
      info={info}
      busy={passwordLoading || authChecking}
      inputDisabled={inputDisabled}
      authUnavailable={authUnavailable}
      localAuthAvailable={isLocalAuthAvailable()}
      onLocalLogin={handleLocalLogin}
    />
  );
}
