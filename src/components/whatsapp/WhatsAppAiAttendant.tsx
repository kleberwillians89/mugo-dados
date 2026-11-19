import { useEffect, useState, type FormEvent } from "react";
import { getActiveClientId } from "../../app/activeClient";
import { formatCurrency } from "../../app/dataFormat";
import {
  WA_CLAUDE_MODELS, getWhatsAppAiCatalog, getWhatsAppAiSettings, removeWhatsAppAiClaudeKey, saveWhatsAppAiClaudeKey,
  saveWhatsAppAiSettings, simulateWhatsAppAi,
  type WaAiCatalogStatus, type WaAiMode, type WaAiSettings, type WaAiSimulation, type WaClaudeModel,
} from "../../app/whatsapp";

const MODES: { key: WaAiMode; label: string; hint: string }[] = [
  { key: "off", label: "Desligada", hint: "A IA não lê nem responde as conversas." },
  { key: "suggest", label: "Sugere, a equipe aprova", hint: "A IA escreve a resposta (com botões e produtos) e espera alguém aprovar na conversa." },
  { key: "auto", label: "Responde sozinha", hint: "A IA responde na hora e passa para a equipe quando precisa." },
];
const lines = (text: string) => text.split("\n").map((line) => line.trim()).filter(Boolean);
const error = (cause: unknown, fallback: string) => (cause instanceof Error && cause.message ? cause.message : fallback);

type Turn = { role: "cliente" | "marca"; text: string };

/**
 * Atendente de IA do WhatsApp da marca: diretrizes, condições vigentes, seleção em destaque, botões de boas-vindas,
 * cartões do catálogo da Meta e um teste que não envia nada. Ligar em "Responde sozinha" pede confirmação.
 */
export default function WhatsAppAiAttendant() {
  const clientId = getActiveClientId();
  const [settings, setSettings] = useState<WaAiSettings | null>(null);
  const [form, setForm] = useState({ instructions: "", offers: "", buttons: "", featured: "", catalog: "", cards: true, pause: 240, groupLink: "", groupMessage: "" });
  const [claude, setClaude] = useState<{ key: string; model: WaClaudeModel; busy: boolean; note: { ok: boolean; text: string } | null }>({ key: "", model: "claude-sonnet-5-5", busy: false, note: null });
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [catalog, setCatalog] = useState<{ data: WaAiCatalogStatus | null; loading: boolean; error: string | null }>({ data: null, loading: false, error: null });
  const [turns, setTurns] = useState<Turn[]>([]);
  const [simText, setSimText] = useState("");
  const [sim, setSim] = useState<{ data: WaAiSimulation | null; loading: boolean; error: string | null }>({ data: null, loading: false, error: null });

  function fill(next: WaAiSettings) {
    setSettings(next);
    setForm({
      instructions: next.instructions, offers: next.offers, buttons: next.welcome_buttons.join("\n"),
      featured: next.featured_products.join("\n"), catalog: next.catalog_id || "", cards: next.product_cards, pause: next.human_pause_minutes,
      groupLink: next.ad_group_link || "", groupMessage: next.ad_group_message || "",
    });
    setClaude((c) => ({ ...c, model: next.claude_model || "claude-sonnet-5-5" }));
  }

  useEffect(() => {
    if (!clientId) return;
    let alive = true;
    getWhatsAppAiSettings()
      .then((res) => { if (alive) fill(res.settings); })
      .catch((cause) => { if (alive) setLoadError(error(cause, "Não foi possível carregar o atendente agora.")); });
    return () => { alive = false; };
  }, [clientId]);

  async function save(changes: Partial<WaAiSettings>, okText = "Salvo.") {
    setSaving(true); setNote(null);
    try {
      const res = await saveWhatsAppAiSettings(changes);
      fill(res.settings);
      setNote({ ok: true, text: okText });
    } catch (cause) {
      setNote({ ok: false, text: error(cause, "Não foi possível salvar agora.") });
    } finally {
      setSaving(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void save({
      instructions: form.instructions, offers: form.offers, welcome_buttons: lines(form.buttons).slice(0, 3),
      featured_products: lines(form.featured), catalog_id: form.catalog.trim() || null, product_cards: form.cards,
      human_pause_minutes: Math.max(0, Math.round(Number(form.pause) || 0)),
      ad_group_link: form.groupLink.trim() || null, ad_group_message: form.groupMessage.trim(),
    });
  }

  async function saveClaude(event: FormEvent) {
    event.preventDefault();
    if (!claude.key.trim()) return;
    setClaude((c) => ({ ...c, busy: true, note: null }));
    try {
      const res = await saveWhatsAppAiClaudeKey(claude.key.trim(), claude.model);
      fill(res.settings);
      setClaude((c) => ({ ...c, key: "", busy: false, note: { ok: true, text: "Chave conferida. O atendente passa a responder com o Claude da marca." } }));
    } catch (cause) {
      setClaude((c) => ({ ...c, busy: false, note: { ok: false, text: error(cause, "Não foi possível conferir a chave agora.") } }));
    }
  }

  async function dropClaude() {
    if (!window.confirm("Tirar a chave do Claude? O atendente volta a usar a IA da plataforma.")) return;
    setClaude((c) => ({ ...c, busy: true, note: null }));
    try { fill((await removeWhatsAppAiClaudeKey()).settings); setClaude((c) => ({ ...c, busy: false, note: { ok: true, text: "Chave removida." } })); }
    catch (cause) { setClaude((c) => ({ ...c, busy: false, note: { ok: false, text: error(cause, "Não foi possível remover agora.") } })); }
  }

  function changeMode(mode: WaAiMode) {
    if (mode === "auto" && !window.confirm("A IA vai responder sozinha as clientes no WhatsApp da marca. As diretrizes já foram aprovadas pela marca?")) return;
    void save({ mode }, mode === "off" ? "IA desligada." : mode === "auto" ? "IA respondendo sozinha." : "IA sugerindo respostas para a equipe aprovar.");
  }

  async function checkCatalog() {
    setCatalog({ data: null, loading: true, error: null });
    try {
      setCatalog({ data: await getWhatsAppAiCatalog(), loading: false, error: null });
    } catch (cause) {
      setCatalog({ data: null, loading: false, error: error(cause, "Não foi possível ler o catálogo agora.") });
    }
  }

  async function simulate(event: FormEvent) {
    event.preventDefault();
    const text = simText.trim();
    if (!text) return;
    const next: Turn[] = [...turns, { role: "cliente", text }];
    setTurns(next); setSimText(""); setSim({ data: null, loading: true, error: null });
    try {
      const data = await simulateWhatsAppAi(next);
      setSim({ data, loading: false, error: null });
      setTurns([...next, { role: "marca", text: data.reply }]);
    } catch (cause) {
      setSim({ data: null, loading: false, error: error(cause, "A IA não respondeu agora.") });
    }
  }

  if (loadError) return <p className="waMuted waPad" role="alert">{loadError}</p>;
  if (!settings) return <p className="waMuted waPad" role="status">Carregando o atendente…</p>;
  const buttonsTooLong = lines(form.buttons).some((b) => b.length > 20);

  return (
    <div className="waAi">
      <section className="waCard" aria-labelledby="wa-ai-mode">
        <div className="waCardHead"><h2 id="wa-ai-mode">Como a IA atende</h2>
          <span className={`waTag${settings.mode === "auto" ? " is-bought" : settings.mode === "suggest" ? " is-link" : ""}`}>
            {MODES.find((m) => m.key === settings.mode)?.label}</span></div>
        <div className="waAiModes" role="radiogroup" aria-label="Modo do atendente de IA">
          {MODES.map((mode) => (
            <button key={mode.key} type="button" role="radio" aria-checked={settings.mode === mode.key} disabled={saving}
              className={settings.mode === mode.key ? "is-active" : ""} onClick={() => changeMode(mode.key)}>
              <b>{mode.label}</b><small>{mode.hint}</small>
            </button>
          ))}
        </div>
        <p className="waMuted waSmall">Preço, estoque, tamanhos e links vêm da Shopify na hora. Reclamação, troca, pagamento ou pedido de pessoa: a IA passa para a equipe e fica quieta na conversa.</p>
      </section>

      <form className="waCard waAiForm" onSubmit={submit} aria-labelledby="wa-ai-rules">
        <h2 id="wa-ai-rules">Diretrizes e vendas</h2>
        <label>Diretrizes da marca (tom, o que fazer e o que evitar, exemplos)
          <textarea rows={14} maxLength={12000} value={form.instructions} onChange={(e) => setForm({ ...form, instructions: e.target.value })} />
        </label>
        <label>Condições vigentes (desconto, cupom, frete, First Access, links oficiais). A IA só fala do que estiver aqui.
          <textarea rows={4} maxLength={4000} value={form.offers} placeholder="Ex.: Black Friday: 20% off na seleção até 30/11. Roove Circle: https://…"
            onChange={(e) => setForm({ ...form, offers: e.target.value })} />
        </label>
        <div className="waAiCols">
          <label>Botões de boas-vindas (até 3, um por linha, até 20 letras)
            <textarea rows={3} value={form.buttons} onChange={(e) => setForm({ ...form, buttons: e.target.value })} aria-invalid={buttonsTooLong} />
            {buttonsTooLong ? <small className="waAiWarn">O WhatsApp corta botões com mais de 20 letras.</small> : null}
          </label>
          <label>Seleção em destaque (nome da peça, uma por linha)
            <textarea rows={3} value={form.featured} onChange={(e) => setForm({ ...form, featured: e.target.value })} />
          </label>
        </div>
        <div className="waAiCols">
          <label>Catálogo da Meta (ID; vazio = o catálogo ligado à WABA)
            <input inputMode="numeric" value={form.catalog} onChange={(e) => setForm({ ...form, catalog: e.target.value.replace(/\D/g, "") })} />
          </label>
          <label>IA quieta depois que a equipe responde (minutos)
            <input type="number" min={0} max={10080} value={form.pause} onChange={(e) => setForm({ ...form, pause: Number(e.target.value) })} />
          </label>
        </div>
        <fieldset className="waAiGroup">
          <legend>Quem chega por anúncio</legend>
          <p className="waMuted waSmall">Quando a pessoa chama pelo botão de WhatsApp de um anúncio da Meta, ela recebe o convite do grupo uma vez, numa mensagem logo depois da resposta da IA (mesmo se a conversa passar para a equipe).</p>
          <div className="waAiCols">
            <label>Link do grupo
              <input type="url" placeholder="https://chat.whatsapp.com/…" value={form.groupLink} onChange={(e) => setForm({ ...form, groupLink: e.target.value })} />
            </label>
            <label>Mensagem do convite (use {"{link}"} onde o link entra)
              <textarea rows={3} maxLength={1000} value={form.groupMessage} placeholder="Que bom te ver por aqui! Entra no nosso grupo para receber o acesso antecipado da Black Friday: {link}"
                onChange={(e) => setForm({ ...form, groupMessage: e.target.value })} />
            </label>
          </div>
        </fieldset>
        <label className="waAiCheck"><input type="checkbox" checked={form.cards} onChange={(e) => setForm({ ...form, cards: e.target.checked })} />
          Mostrar as peças como cartões do catálogo (foto, preço e carrinho no WhatsApp). Sem catálogo, vão como link da loja.</label>
        <div className="waFormActions">
          <button type="submit" className="ds-button is-primary" disabled={saving}>{saving ? "Salvando…" : "Salvar"}</button>
          <button type="button" className="ds-button" onClick={() => void checkCatalog()} disabled={catalog.loading}>{catalog.loading ? "Conferindo…" : "Conferir Shopify e catálogo"}</button>
          {note ? <span className="waMuted waSmall" role={note.ok ? "status" : "alert"}>{note.text}</span> : null}
        </div>
        {catalog.error ? <p className="waMuted waSmall" role="alert">{catalog.error}</p> : null}
        {catalog.data ? (
          <ul className="waAiChecks">
            <li className={catalog.data.shopify.ok ? "is-ok" : "is-bad"}>{catalog.data.shopify.ok
              ? `Shopify (${catalog.data.shopify.domain}): ${catalog.data.shopify.products} peças publicadas, ${catalog.data.shopify.available} com estoque.`
              : "Shopify: a IA não está conseguindo ler os produtos (confira a conexão e a permissão read_products)."}</li>
            <li className={catalog.data.meta.ok ? "is-ok" : "is-bad"}>{catalog.data.meta.ok
              ? `Catálogo da Meta ${catalog.data.meta.catalog_id}: ${catalog.data.meta.items} itens, ${catalog.data.meta.matched_products} peças ligadas à Shopify.`
              : "Catálogo da Meta: nenhum ligado à WABA (ou sem permissão catalog_management). As peças vão como link da loja."}</li>
            {catalog.data.featured.map((item) => (
              <li key={item.name} className={item.found.some((f) => f.available) ? "is-ok" : "is-bad"}>
                {item.name}: {item.found.length ? item.found.map((f) => `${f.title}${f.available ? "" : " (esgotado)"}`).join(", ") : "não encontrada na Shopify"}
              </li>
            ))}
          </ul>
        ) : null}
      </form>

      <form className="waCard waAiForm" onSubmit={(e) => void saveClaude(e)} aria-labelledby="wa-ai-claude">
        <div className="waCardHead"><h2 id="wa-ai-claude">Claude da marca</h2>
          <span className={`waTag${settings.has_claude_key ? " is-bought" : ""}`}>{settings.has_claude_key ? `Ativo · …${settings.claude_key_hint || ""}` : "Usando a IA da plataforma"}</span></div>
        <p className="waMuted waSmall">Com a chave de API do Claude da própria marca, o atendente responde com o Claude e o custo vai para a conta dela. Se o Claude ficar sem crédito ou fora do ar, a IA da plataforma responde no lugar, sem deixar a cliente sem resposta.
          A chave é criada em console.anthropic.com → API Keys (é diferente da assinatura do app Claude) e fica guardada criptografada: depois de salva, só aparece o final dela.</p>
        <div className="waAiCols">
          <label>Chave de API do Claude
            <input type="password" autoComplete="off" spellCheck={false} placeholder={settings.has_claude_key ? "Colar outra chave para trocar" : "sk-ant-…"}
              value={claude.key} onChange={(e) => setClaude({ ...claude, key: e.target.value })} />
          </label>
          <label>Modelo
            <select value={claude.model} onChange={(e) => setClaude({ ...claude, model: e.target.value as WaClaudeModel })}>
              {WA_CLAUDE_MODELS.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
          </label>
        </div>
        <div className="waFormActions">
          <button type="submit" className="ds-button is-primary" disabled={claude.busy || !claude.key.trim()}>{claude.busy ? "Conferindo…" : settings.has_claude_key ? "Trocar chave" : "Conferir e salvar"}</button>
          {settings.has_claude_key ? <>
            <button type="button" className="ds-button" disabled={claude.busy || claude.model === settings.claude_model}
              onClick={() => void save({ claude_model: claude.model }, "Modelo do Claude atualizado.")}>Salvar só o modelo</button>
            <button type="button" className="ds-link is-quiet" disabled={claude.busy} onClick={() => void dropClaude()}>Tirar a chave</button>
          </> : null}
          {claude.note ? <span className="waMuted waSmall" role={claude.note.ok ? "status" : "alert"}>{claude.note.text}</span> : null}
        </div>
      </form>

      <section className="waCard" aria-labelledby="wa-ai-test">
        <div className="waCardHead"><h2 id="wa-ai-test">Testar a conversa</h2>
          {turns.length ? <button type="button" className="ds-button" onClick={() => { setTurns([]); setSim({ data: null, loading: false, error: null }); }}>Recomeçar</button> : null}</div>
        <p className="waMuted waSmall">Escreva como uma cliente. Usa as diretrizes salvas e a Shopify de agora; nada é enviado no WhatsApp.</p>
        <ol className="waMessages waAiSim">
          {turns.map((turn, index) => (
            <li key={index} className={`waBubble${turn.role === "marca" ? " is-out" : ""}`}><p>{turn.text}</p></li>
          ))}
          {sim.loading ? <li className="waEvent is-plain">A IA está escrevendo…</li> : null}
        </ol>
        {sim.data ? <AiExtras buttons={sim.data.buttons} products={sim.data.products} handoff={sim.data.handoff ? sim.data.handoff_reason || "passaria para a equipe" : null}
          onButton={(text) => setSimText(text)} /> : null}
        {sim.data && !sim.data.catalog_loaded ? <p className="waMuted waSmall" role="alert">A Shopify não respondeu: a IA ficou sem preço e estoque neste teste.</p> : null}
        {sim.error ? <p className="waMuted waSmall" role="alert">{sim.error}</p> : null}
        <form className="waComposer" onSubmit={simulate}>
          <label className="waSrOnly" htmlFor="wa-ai-sim">Mensagem da cliente</label>
          <textarea id="wa-ai-sim" rows={2} maxLength={1000} value={simText} placeholder="Oi! Vi a Black Friday, o que vocês indicam para treinar?"
            onChange={(e) => setSimText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); e.currentTarget.form?.requestSubmit(); } }} />
          <button type="submit" className="ds-button is-primary" disabled={sim.loading || !simText.trim()}>Enviar como cliente</button>
        </form>
      </section>
    </div>
  );
}

/** Botões e peças que acompanham a resposta da IA (no teste, na sugestão e nas mensagens enviadas). */
export function AiExtras({ buttons, products, handoff, onButton }: {
  buttons: string[]; products: { handle: string; title: string; price: number; url: string; image: string | null }[];
  handoff?: string | null; onButton?: (text: string) => void;
}) {
  if (!buttons.length && !products.length && !handoff) return null;
  return (
    <div className="waAiExtras">
      {buttons.length ? (
        <div className="waAiButtons">{buttons.map((b) => onButton
          ? <button type="button" key={b} onClick={() => onButton(b)}>{b}</button>
          : <span key={b}>{b}</span>)}</div>
      ) : null}
      {products.length ? (
        <ul className="waAiProducts">
          {products.map((p) => (
            <li key={p.handle}>
              {p.image ? <img src={p.image} alt="" loading="lazy" /> : null}
              <a href={p.url} target="_blank" rel="noreferrer">{p.title}</a>
              <small>{formatCurrency(p.price)}</small>
            </li>
          ))}
        </ul>
      ) : null}
      {handoff ? <p className="waMuted waSmall">Passa para a equipe: {handoff}</p> : null}
    </div>
  );
}
