import { useEffect, useState } from "react";
import { Check, Sparkles, X } from "lucide-react";
import { getActiveClient, getActiveClientName } from "../app/activeClient";
import { ACTION_LABEL, ACTION_STATUS, decideAiAction, generateAiActions, listAiActions, type AiAction } from "../app/aiActions";
import { formatDateTimeSaoPaulo } from "../app/dataFormat";
import PageHeader from "../components/data/PageHeader";
import Shell from "../components/Shell";
import "../styles/aiActions.css";

const EVIDENCE_LABEL: Record<string, string> = {
  inactive_with_consent: "Clientes sem comprar (com consentimento)", days: "Dias sem comprar", avg_ticket: "Ticket médio",
  repeat_rate: "Recompra (%)", customers: "Clientes", median_days_to_second: "Dias até a 2ª compra (mediana)",
  orders_30d: "Pedidos em 30 dias", carts_30d: "Carrinhos abandonados em 30 dias", cac_last_month: "CAC do último mês",
  cac_avg_prev: "CAC médio anterior", increase_pct: "Aumento (%)",
};
const MONEY_KEYS = new Set(["avg_ticket", "cac_last_month", "cac_avg_prev"]);
const fmt = (key: string, value: number | null) =>
  value == null ? "—" : MONEY_KEYS.has(key) ? value.toLocaleString("pt-BR", { style: "currency", currency: "BRL" }) : value.toLocaleString("pt-BR");

function Measurement({ action }: { action: AiAction }) {
  const m = action.measurement;
  if (!m) return null;
  const parts: string[] = [];
  if (m.sent != null) parts.push(`${m.sent.toLocaleString("pt-BR")} enviados`);
  if (m.open_rate != null) parts.push(`${m.open_rate.toLocaleString("pt-BR")}% abriram`);
  if (m.buyers != null) parts.push(`${m.buyers.toLocaleString("pt-BR")} compraram`);
  if (m.revenue != null) parts.push(m.revenue.toLocaleString("pt-BR", { style: "currency", currency: "BRL" }));
  return parts.length ? <p className="aiResult"><strong>Resultado até agora:</strong> {parts.join(" · ")}</p> : null;
}

/** A IA olha os números da marca e propõe ações concretas. Nada roda sem aprovação; depois de rodar, mostra o resultado. */
export default function AiActions() {
  const [actions, setActions] = useState<AiAction[] | null>(null);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const role = String(getActiveClient()?.role || "").toLowerCase();
  const canDecide = ["agency_admin", "platform_admin", "client_admin", "owner", "admin", "account_manager"].includes(role);

  useEffect(() => {
    listAiActions().then((out) => setActions(out.actions)).catch((cause) => setError(cause instanceof Error ? cause.message : "Não foi possível ler as ações."));
  }, []);

  async function run(label: string, fn: () => Promise<void>) {
    setBusy(label); setError(""); setMessage("");
    try { await fn(); } catch (cause) { setError(cause instanceof Error ? cause.message : "Não foi possível concluir."); } finally { setBusy(""); }
  }
  const replace = (next: AiAction) => setActions((list) => (list || []).map((a) => (a.id === next.id ? { ...a, ...next } : a)));
  const open = (actions || []).filter((a) => a.status === "proposta");
  const done = (actions || []).filter((a) => a.status !== "proposta");

  return (
    <Shell title="O que a IA fez" variant="editorial">
      <div className="ds-page aiPage">
        <PageHeader company={getActiveClientName()} title="O que a IA fez"
          dateline={<span>Com tudo conectado, a IA lê os números da marca e já executa: liga fluxos e o carrinho abandonado e agenda a reativação. Aqui fica o que ela fez e o resultado.</span>}
          controls={canDecide ? (
            <button type="button" className="ds-button is-primary" disabled={!!busy}
              onClick={() => void run("gen", async () => {
                const out = await generateAiActions();
                setActions(out.actions);
                setMessage(out.created ? `${out.created} ${out.created === 1 ? "ação nova" : "ações novas"}${out.executed ? `, ${out.executed} já ${out.executed === 1 ? "executada" : "executadas"}` : ""}.` : "Nada novo: os números não pedem ação agora.");
              })}><Sparkles size={15} aria-hidden="true" /> {busy === "gen" ? "Analisando…" : "Analisar agora"}</button>
          ) : null} />
        {error ? <p className="aiError" role="alert">{error}</p> : null}
        {message ? <p className="aiOk">{message}</p> : null}
        {!actions && !error ? <p className="aiMuted">Carregando…</p> : null}

        {actions ? (
          <>
            {open.length ? <h2 className="aiSection">Para aprovar <span className="aiCount">{open.length}</span></h2> : null}
            {open.length === 0 && done.length === 0 ? <p className="aiEmpty">A IA ainda não precisou agir. Ela analisa toda segunda-feira e executa sozinha quando os números pedem; ou clique em “Analisar agora”.</p> : null}
            <div className="aiList">
              {open.map((a) => (
                <article key={a.id} className="aiCard is-open">
                  <header className="aiCardHead">
                    <span className={`aiTag is-${a.kind}`}>{ACTION_LABEL[a.kind].tag}</span>
                    <time>{formatDateTimeSaoPaulo(a.proposed_at)}</time>
                  </header>
                  <h3>{a.title}</h3>
                  <p className="aiRationale">{a.rationale}</p>
                  <dl className="aiEvidence">
                    {Object.entries(a.evidence).filter(([k]) => EVIDENCE_LABEL[k]).map(([k, v]) => (
                      <div key={k}><dt>{EVIDENCE_LABEL[k]}</dt><dd>{fmt(k, v)}</dd></div>
                    ))}
                  </dl>
                  {a.kind === "campanha_reativacao" && a.payload.subject ? (
                    <p className="aiPreview"><span>Assunto proposto</span>{String(a.payload.subject)}<br /><span>Texto</span>{String(a.payload.text || "")}</p>
                  ) : null}
                  <p className="aiDoes">{ACTION_LABEL[a.kind].does}</p>
                  {canDecide ? (
                    <div className="aiActionsRow">
                      <button type="button" className="ds-button" disabled={!!busy}
                        onClick={() => void run(a.id, async () => replace((await decideAiAction(a.id, "rejeitar")).action))}><X size={15} aria-hidden="true" /> Rejeitar</button>
                      <button type="button" className="ds-button is-primary" disabled={!!busy}
                        onClick={() => void run(a.id, async () => {
                          const out = await decideAiAction(a.id, "aprovar");
                          replace(out.action);
                          setMessage(out.action.status === "falhou" ? `Não executou: ${out.action.error}` : "Aprovada e executada.");
                        })}><Check size={15} aria-hidden="true" /> {busy === a.id ? "Executando…" : a.kind === "alerta_cac" ? "Ciente" : "Aprovar e executar"}</button>
                    </div>
                  ) : <p className="aiMuted">Só a equipe Mugô ou o admin da marca aprova.</p>}
                </article>
              ))}
            </div>

            {done.length ? (
              <>
                <h2 className="aiSection">O que a IA fez</h2>
                <div className="aiList">
                  {done.map((a) => (
                    <article key={a.id} className={`aiCard is-${a.status}`}>
                      <header className="aiCardHead">
                        <span className={`aiTag is-${a.kind}`}>{ACTION_LABEL[a.kind].tag}</span>
                        <span className={`aiStatus is-${a.status}`}>{ACTION_STATUS[a.status]}</span>
                        <time>{formatDateTimeSaoPaulo(a.decided_at || a.proposed_at)}</time>
                      </header>
                      <h3>{a.title}</h3>
                      {a.error ? <p className="aiError">{a.error}</p> : null}
                      {a.result?.scheduled_at ? <p className="aiMuted">Envio agendado para {formatDateTimeSaoPaulo(String(a.result.scheduled_at))}. Para desistir, cancele a campanha em E-mail marketing antes desse horário.</p> : null}
                      <Measurement action={a} />
                    </article>
                  ))}
                </div>
              </>
            ) : null}
          </>
        ) : null}
      </div>
    </Shell>
  );
}
