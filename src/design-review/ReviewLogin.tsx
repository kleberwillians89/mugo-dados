// HARNESS DE REVISÃO VISUAL — somente desenvolvimento (fora do build).
// Renderiza a apresentação real do login (LoginView) sem Supabase: nenhum
// dado é enviado; o envio só mostra um aviso de revisão.

import { useState } from "react";
import { LoginView, type LoginMode } from "../pages/Login";

type Props = { initialMode: LoginMode; initialError: string | null };

export default function ReviewLogin({ initialMode, initialError }: Props) {
  const [mode, setMode] = useState<LoginMode>(initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirmation, setPasswordConfirmation] = useState("");
  const [info, setInfo] = useState<string | null>(null);

  return (
    <LoginView
      mode={mode}
      email={email}
      password={password}
      passwordConfirmation={passwordConfirmation}
      onEmailChange={setEmail}
      onPasswordChange={setPassword}
      onPasswordConfirmationChange={setPasswordConfirmation}
      onSubmit={(event) => {
        event.preventDefault();
        setInfo("Revisão visual: nenhum acesso é enviado.");
      }}
      onModeChange={(next) => {
        setInfo(null);
        setMode(next);
      }}
      error={info ? null : initialError}
      info={info}
      busy={false}
      inputDisabled={false}
      authUnavailable={false}
      localAuthAvailable={false}
      onLocalLogin={() => undefined}
    />
  );
}
