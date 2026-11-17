import { useState } from "react";
import { BookOpen, CalendarRange, Plug, Swords, Target, UserCog } from "lucide-react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import { navigateToAppRoute, type AppRoute } from "../app/routes";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import SegmentedControl from "../components/data/SegmentedControl";
import BusinessContextPanel from "../components/admin/BusinessContextPanel";
import BrandImport from "../components/brandContext/BrandImport";
import BrandProfileSummary from "../components/brandContext/BrandProfileSummary";
import BrandAgent from "../components/studio/BrandAgent";
import BrandKnowledge from "../components/studio/BrandKnowledge";
import "../styles/studio.css";
import "../styles/companies.css";
import "../styles/brandContext.css";

export type BrandContextTab = "identidade" | "documentos" | "operacao";
const TABS: { id: BrandContextTab; label: string }[] = [
  { id: "identidade", label: "Identidade e estratégia" },
  { id: "documentos", label: "Documentos e conhecimento" },
  { id: "operacao", label: "Configuração operacional" },
];

function tabFromLocation(): BrandContextTab {
  if (typeof window === "undefined") return "identidade";
  const requested = new URLSearchParams(window.location.search).get("aba");
  return TABS.some((t) => t.id === requested) ? (requested as BrandContextTab) : "identidade";
}

/** Troca de tela como o resto do app: muda o endereço e avisa o App pelo popstate. */
function open(route: AppRoute, path?: string) {
  if (path) window.history.pushState({}, document.title, path);
  else navigateToAppRoute(route);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

type Shortcut = { id: string; icon: typeof Plug; title: string; text: string; route: AppRoute; path?: string; manageOnly?: boolean };
const SHORTCUTS: Shortcut[] = [
  { id: "calendario", icon: CalendarRange, title: "Calendário e perfil editorial", route: "campaigns", path: "/social-media#social-calendario",
    text: "Frequência por semana e por canal, formatos, plataformas e datas da marca. É onde as pautas são geradas e aprovadas." },
  { id: "metas", icon: Target, title: "Metas", route: "goals", text: "Objetivos numéricos do mês (vendas, leads, investimento) que a Inteligência acompanha." },
  { id: "benchmark", icon: Swords, title: "Concorrentes", route: "benchmark", text: "Cadastro dos concorrentes acompanhados no Benchmarking." },
  { id: "integracoes", icon: Plug, title: "Integrações", route: "integrations", manageOnly: true, text: "Contas conectadas (Meta, Google, loja) de onde vêm os dados." },
  { id: "usuarios", icon: UserCog, title: "Usuários e acessos", route: "users", manageOnly: true, text: "Quem da empresa pode ver e editar cada módulo." },
];

/**
 * Configurações → Contexto da Marca. Junta, sem duplicar, o que já existia espalhado:
 * A. Identidade e estratégia: Perfil da marca (consulta) + Contexto estratégico (BusinessContextPanel, o mesmo da tela Empresas);
 * B. Documentos e conhecimento: Importar configurações do planejamento (BrandImport, só admin) + BrandKnowledge (envio, lista,
 *    status, memória, correção, tentar de novo) + conversa com a IA da marca;
 * C. Configuração operacional: atalhos para as telas que já mantêm esses dados.
 * Todo mundo da empresa consulta; editar é de admin (client_admin/owner) e da equipe — o backend valida de novo.
 * O endereço antigo /ia-da-marca abre esta mesma tela.
 */
export default function BrandAI({ canManage, isAgency = false }: { canManage: boolean; isAgency?: boolean }) {
  const clientId = getActiveClientId();
  const company = getActiveClientName() || "empresa";
  const [tab, setTab] = useState<BrandContextTab>(tabFromLocation);
  const [version, setVersion] = useState(0);
  // Importação aplicada: o Contexto estratégico recarrega (o Perfil recarrega pelo evento de perfil salvo).
  const [contextVersion, setContextVersion] = useState(0);
  const team = canManage && isAgency;

  function selectTab(next: string) {
    const value = next as BrandContextTab;
    setTab(value);
    const url = new URL(window.location.href);
    url.searchParams.set("aba", value);
    window.history.replaceState({}, document.title, `${url.pathname}${url.search}`);
  }

  return <Shell title="Contexto da Marca" variant="editorial"><div className="ds-page studioPage bcPage">
    <PageHeader company={company} title="Contexto da Marca" />
    <p className="libHint">Tudo o que a plataforma sabe sobre {company}: quem a marca é, o que diz o material enviado e como a operação
      está configurada. A IA usa isso nas pautas, nas legendas, nas respostas e nas análises.
      {canManage ? "" : " Você pode consultar; a edição é dos administradores da empresa."}</p>
    <SegmentedControl ariaLabel="Áreas do Contexto da Marca" options={TABS} value={tab} onSelect={selectTab} />

    {tab === "identidade" ? <div className="bcStack">
      {canManage ? <div className="bcImportCta">
        <p className="libHint">Tem um planejamento ou brand book? Importe as configurações dele em vez de preencher tudo à mão.</p>
        <button type="button" className="ds-button" onClick={() => selectTab("documentos")}>Importar do planejamento</button>
      </div> : null}
      <BrandProfileSummary key={`profile:${clientId}`}
        onEdit={team ? () => open("campaigns", "/social-media?perfil=1#social-calendario") : undefined}
        editHint={team ? undefined : canManage ? "Para ajustar o perfil editorial, fale com a equipe Mugô." : undefined} />
      <BusinessContextPanel key={`business:${clientId}:${contextVersion}`} canEdit={canManage} />
    </div> : null}

    {tab === "documentos" ? <div className="bcStack">
      <p className="libHint"><BookOpen size={14} aria-hidden="true" /> {canManage
        ? "Envie planejamentos, brand books, apresentações e tabelas de produtos. O texto fica guardado (o arquivo original não é armazenado) e a IA aprende com ele."
        : "O que a IA da Mugô aprendeu com os materiais da sua empresa."}</p>
      {canManage ? <BrandImport key={`import:${clientId}:${version}`} onApplied={() => setContextVersion((v) => v + 1)} /> : null}
      <BrandKnowledge key={clientId} canManage={canManage} version={version} />
      <BrandAgent key={`agent:${clientId}`} canManage={canManage} company={company} onLearned={() => setVersion((v) => v + 1)} />
    </div> : null}

    {tab === "operacao" ? <div className="bcShortcuts" role="list">
      {SHORTCUTS.filter((s) => canManage || !s.manageOnly).map((s) => <article key={s.id} className="bcCard bcShortcut" role="listitem">
        <s.icon size={18} aria-hidden="true" />
        <div><h3>{s.title}</h3><p className="libHint">{s.text}</p></div>
        <button type="button" className="ds-button" onClick={() => open(s.route, s.path)}>Abrir</button>
      </article>)}
    </div> : null}
  </div></Shell>;
}
