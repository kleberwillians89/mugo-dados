// HARNESS DE REVISÃO VISUAL — índice das telas e estados para revisão.

type Link = { label: string; query: string; note?: string };
type Group = { title: string; links: Link[] };

const GROUPS: Group[] = [
  {
    title: "Login",
    links: [
      { label: "Acesso", query: "tela=login" },
      { label: "Erro de acesso", query: "tela=login&estado=erro" },
      { label: "Esqueci minha senha", query: "tela=login&estado=recuperar" },
      { label: "Definir nova senha", query: "tela=login&estado=definir" },
    ],
  },
  {
    title: "Aceite de convite",
    links: [
      { label: "Convite para 1 empresa (Origami) — aceitar e redirecionar", query: "tela=convite" },
      { label: "Convite para 2 empresas", query: "tela=convite&estado=varias" },
      { label: "Empresa sem nome informado (não inventa marca)", query: "tela=convite&estado=sem-nome" },
      { label: "Carregando (aceite em andamento)", query: "tela=convite&estado=aceitando&abrir=aceitar" },
      { label: "Convite inválido (404)", query: "tela=convite&estado=invalido&abrir=aceitar" },
      { label: "Convite expirado (409)", query: "tela=convite&estado=expirado&abrir=aceitar" },
      { label: "Erro", query: "tela=convite&estado=erro&abrir=aceitar" },
      { label: "Aceito — abrindo a empresa", query: "tela=convite&estado=sucesso&abrir=aceitar" },
    ],
  },
  {
    title: "Shell + Ecommerce",
    links: [
      { label: "Agência — 6 empresas, administração visível", query: "tela=ecommerce&perfil=agencia" },
      { label: "Cliente com 1 empresa — Curavino", query: "tela=ecommerce&perfil=cliente&empresa=vinhos" },
      { label: "Cliente com 1 empresa — Origami", query: "tela=ecommerce&perfil=cliente&empresa=origami" },
      { label: "Cliente com 1 empresa — Roove (Ecommerce via Shopify)", query: "tela=ecommerce&perfil=cliente&empresa=roove" },
      { label: "Cliente com 1 empresa — Ruah Parfums", query: "tela=ecommerce&perfil=cliente&empresa=ruah" },
      { label: "Cliente com 1 empresa — Latina", query: "tela=ecommerce&perfil=cliente&empresa=latina" },
      { label: "Cliente com 1 empresa — Mugô", query: "tela=ecommerce&perfil=cliente&empresa=mugo" },
      { label: "Cliente com 2 empresas", query: "tela=ecommerce&perfil=cliente&empresas=2" },
      { label: "Somente leitura (viewer) — FBITS sem sincronizar", query: "tela=ecommerce&perfil=viewer&empresa=vinhos" },
      { label: "Somente leitura (viewer) — Shopify sem sincronizar", query: "tela=ecommerce&perfil=viewer&empresa=roove" },
    ],
  },
  {
    title: "Estados do Ecommerce",
    links: [
      { label: "Sem base de comparação", query: "tela=ecommerce&perfil=cliente&cenario=sem-comparacao" },
      { label: "Sem vendas", query: "tela=ecommerce&perfil=cliente&cenario=sem-vendas" },
      { label: "Aguardando primeira sincronização", query: "tela=ecommerce&perfil=cliente&cenario=pendente" },
      { label: "Erro", query: "tela=ecommerce&perfil=cliente&cenario=erro" },
      { label: "Carregando", query: "tela=ecommerce&perfil=cliente&cenario=carregando" },
    ],
  },
  {
    title: "Meta",
    links: [
      { label: "Meta Ads + Instagram — com comparação", query: "tela=meta&perfil=cliente&empresa=vinhos" },
      { label: "Agência (IDs dos ativos e diagnóstico)", query: "tela=meta&perfil=agencia&empresa=vinhos" },
      { label: "Somente leitura (sem Atualizar dados)", query: "tela=meta&perfil=viewer&empresa=vinhos" },
      { label: "Roove — com vendas da loja (Shopify) no mesmo período", query: "tela=meta&perfil=cliente&empresa=roove" },
      { label: "Sem base anterior", query: "tela=meta&perfil=cliente&cenario=sem-comparacao" },
      { label: "Sem dados no período", query: "tela=meta&perfil=cliente&cenario=sem-dados" },
      { label: "Desconectado", query: "tela=meta&perfil=cliente&cenario=desconectado" },
      { label: "Autorização expirada", query: "tela=meta&perfil=cliente&cenario=reautorizar" },
      { label: "Erro", query: "tela=meta&perfil=cliente&cenario=erro" },
      { label: "Carregando", query: "tela=meta&perfil=cliente&cenario=carregando" },
    ],
  },
  {
    title: "Google Ads",
    links: [
      { label: "Google Ads — conta via MCC", query: "tela=google-ads&perfil=cliente&empresa=vinhos" },
      { label: "Agência (IDs da conta e da MCC)", query: "tela=google-ads&perfil=agencia&empresa=vinhos" },
      { label: "Roove — com vendas da loja e bloco Hoje", query: "tela=google-ads&perfil=cliente&empresa=roove" },
      { label: "Sem dados no período", query: "tela=google-ads&perfil=cliente&cenario=sem-dados" },
      { label: "Desconectado", query: "tela=google-ads&perfil=cliente&cenario=desconectado" },
      { label: "Autorização expirada", query: "tela=google-ads&perfil=cliente&cenario=reautorizar" },
      { label: "Erro", query: "tela=google-ads&perfil=cliente&cenario=erro" },
      { label: "Carregando", query: "tela=google-ads&perfil=cliente&cenario=carregando" },
    ],
  },
  {
    title: "Google Analytics (GA4)",
    links: [
      { label: "GA4 — aquisição, comportamento e conversão", query: "tela=ga4&perfil=cliente&empresa=vinhos" },
      { label: "Somente leitura", query: "tela=ga4&perfil=viewer&empresa=vinhos" },
      { label: "Sem dados no período", query: "tela=ga4&perfil=cliente&cenario=sem-dados" },
      { label: "Desconectado", query: "tela=ga4&perfil=cliente&cenario=desconectado" },
      { label: "Erro", query: "tela=ga4&perfil=cliente&cenario=erro" },
      { label: "Carregando", query: "tela=ga4&perfil=cliente&cenario=carregando" },
    ],
  },
  {
    title: "Integrações",
    links: [
      { label: "Administrador do cliente", query: "tela=integracoes&perfil=cliente&empresa=vinhos" },
      { label: "Agência (com diagnóstico técnico)", query: "tela=integracoes&perfil=agencia" },
      {
        label: "Retorno do OAuth Meta — ativos agrupados por Business",
        query: "tela=integracoes&perfil=cliente&empresa=vinhos&onboarding=1&client_id=vinhos&meta_oauth=success&handoff=revisao-meta&connection_id=exemplo-meta",
      },
    ],
  },
  {
    title: "Páginas legais (rotas reais)",
    links: [
      { label: "Política de Privacidade (revisão jurídica pendente)", query: "", note: "/privacidade" },
      { label: "Exclusão de dados (revisão jurídica pendente)", query: "", note: "/exclusao-de-dados" },
      { label: "Proteção de dados (revisão jurídica pendente)", query: "", note: "/protecao-de-dados" },
      { label: "Termos de Uso (pendente)", query: "", note: "/termos-de-uso" },
    ],
  },
];

export default function ReviewIndex() {
  return (
    <main className="reviewIndex">
      <p className="reviewIndexEyebrow">Mugô Dados · revisão visual</p>
      <h1>Telas para revisão</h1>
      <p className="reviewIndexLead">
        Dados, empresas e pessoas de exemplo — nada aqui vem de clientes reais. Para mobile,
        abra a mesma URL com a janela estreita (390 px) ou no celular.
      </p>
      {GROUPS.map((group) => (
        <section key={group.title}>
          <h2>{group.title}</h2>
          <ul>
            {group.links.map((link) => {
              const href = link.note ? link.note : `?${link.query}`;
              return (
                <li key={link.label}>
                  <a href={href}>{link.label}</a>
                  <code>{link.note ? link.note : `design-review.html?${link.query}`}</code>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </main>
  );
}
