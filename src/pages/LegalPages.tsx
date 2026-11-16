import MugoLogo from "../components/MugoLogo";
import { LEGAL_CONTACT } from "../app/legalContact";
import "../styles/LegalPages.css";

/* Minutas para revisão jurídica. Não presumir certificação, prazos de retenção
   nem configurações de treinamento da OpenAI. Não publicar sem revisão. */
type PageName = "privacy" | "terms" | "deletion" | "protection";
type Section = { title: string; paragraphs?: string[]; points?: string[] };
const english = () => typeof window !== "undefined" && window.location.pathname.toLowerCase().startsWith("/en/");
const urls: Record<PageName, [string, string]> = {
  privacy: ["/privacidade", "/en/privacy"], terms: ["/termos-de-uso", "/en/terms"],
  deletion: ["/exclusao-de-dados", "/en/data-deletion"], protection: ["/protecao-de-dados", "/protecao-de-dados"],
};
function LegalHeader({ title, summary, page = "protection", en = false }: { title: string; summary: string; page?: PageName; en?: boolean }) {
  return <>
    <header className="legalHeader">
      <a className="legalBrand" href="/" aria-label="Mugoverso — página inicial"><MugoLogo variant="responsive" /></a>
      <nav aria-label={en ? "Legal documents" : "Documentos legais"}>
        <a href={urls.privacy[en ? 1 : 0]}>{en ? "Privacy" : "Privacidade"}</a>
        <a href={urls.terms[en ? 1 : 0]}>{en ? "Terms of use" : "Termos de uso"}</a>
        <a href="/protecao-de-dados">{en ? "Data protection" : "Proteção de dados"}</a>
        <a href={urls.deletion[en ? 1 : 0]}>{en ? "Data deletion" : "Exclusão de dados"}</a>
      </nav>
      <div className="legalLang" aria-label="Language">
        <a aria-current={!en ? "page" : undefined} href={urls[page][0]}>PT</a>
        <span> / </span><a aria-current={en ? "page" : undefined} href={urls[page][1]}>EN</a>
      </div>
    </header>
    <section className="legalHero">
      <p className="legalEyebrow">Mugoverso</p><h1>{title}</h1><p>{summary}</p>
      <small>{en ? "Last updated: November 16, 2026" : "Última atualização: 16 de novembro de 2026"}</small>
    </section>
  </>;
}
function LegalFooter({ en = false }: { en?: boolean }) {
  return <footer className="legalFooter"><strong>Mugoverso</strong>
    <span>{en ? "Mugô marketing and data intelligence platform." : "Plataforma de dados e inteligência da Mugô."}</span>
    <nav aria-label={en ? "Legal links" : "Links legais do rodapé"}>
      <a href={urls.privacy[en ? 1 : 0]}>{en ? "Privacy" : "Privacidade"}</a>
      <a href={urls.terms[en ? 1 : 0]}>{en ? "Terms" : "Termos de uso"}</a>
      <a href="/protecao-de-dados">{en ? "Data protection" : "Proteção de dados"}</a>
      <a href={urls.deletion[en ? 1 : 0]}>{en ? "Deletion" : "Exclusão de dados"}</a>
    </nav><a href="/">{en ? "Back to Mugoverso" : "Voltar ao acesso do Mugoverso"}</a>
  </footer>;
}
function LegalSections({ sections }: { sections: Section[] }) {
  return <>{sections.map((s, i) => <section key={i}><h2>{s.title}</h2>
    {(s.paragraphs || []).map((p,j) => <p key={j}>{p}</p>)}
    {s.points?.length ? <ul>{s.points.map((p,j) => <li key={j}>{p}</li>)}</ul> : null}
  </section>)}</>;
}
const privacyPT: Section[] = [
  {title:"1. Responsável, contexto e finalidades", paragraphs:[
    "Mugoverso é uma plataforma SaaS B2B da Mugô para análise de marketing, comércio, relacionamento e operações. A pessoa jurídica responsável é [RAZÃO SOCIAL], [CNPJ]. A definição de controlador ou operador depende da relação contratual.",
    "A plataforma processa dados para autenticar pessoas, conectar ativos escolhidos, gerar painéis e relatórios, planejar campanhas, oferecer suporte, manter segurança e, quando solicitado, elaborar análises por IA. A base legal aplicável depende da operação, contrato, obrigação legal ou consentimento quando exigido."
  ]},
  {title:"2. Dados consultados em integrações autorizadas", paragraphs:["As fontes e permissões disponíveis dependem da aprovação de cada provedor e da autorização de cada empresa. A presença de um conector no produto não significa que ele esteja ativo para todos."], points:[
    "Meta / Facebook / Instagram: identificação da conta (public_profile), Páginas (pages_show_list, pages_read_engagement), perfil e conteúdo profissional (instagram_basic, instagram_manage_insights), relatórios de anúncios (ads_read) e seleção de Business Managers (business_management). Com ads_management, o Mídia On pode criar campanhas, conjuntos, criativos e anúncios em estado pausado.",
    "Google: identificação da conta via OAuth; relatórios de Google Analytics 4 (analytics.readonly), Google Ads (adwords) e leitura de eventos do Calendar (calendar.readonly), quando vinculados.",
    "Shopify: pedidos, produtos e clientes (read_orders, read_all_orders quando autorizado, read_products, read_customers). Pedidos podem conter dados pessoais de compradores finais, incluindo nome, contato, endereço e itens comprados, conforme disponibilizados pela loja.",
    "TikTok Ads: contas e relatórios de investimento, impressões, cliques, conversões e outras métricas disponíveis na Marketing API.",
    "TikTok orgânico: dados básicos e estatísticos da conta e vídeos autorizados (user.info.basic, user.info.stats e video.list). O conector de leitura não publica, edita ou remove vídeos.",
    "Pinterest: contas, quadros e pins (user_accounts:read, boards:read e pins:read), com relatórios de publicidade (ads:read).",
    "LinkedIn: contas de publicidade e relatórios (r_ads, r_ads_reporting), páginas de organizações e conteúdo autorizado (r_organization_admin, r_organization_social).",
    "Microsoft Clarity: métricas agregadas de comportamento e navegação fornecidas por token de projeto, incluindo sessões e interações; não pressupõe coleta irrestrita de gravações.",
    "Ferramentas de IA: perguntas e trechos de contexto empresarial autorizado podem ser enviados à API da OpenAI para produzir análises. Pesquisas públicas podem trazer informações e URLs externas identificadas como tais."
  ]},
  {title:"3. Segurança e provedores de infraestrutura", paragraphs:[
    "O acesso é autenticado e associado à empresa autorizada. O backend aplica verificações por tenant e protege credenciais de integração criptografadas, sem expor os segredos de API no navegador.",
    "O serviço utiliza Vercel (frontend), Render (backend), Supabase (autenticação e dados) e OpenAI (processamento de solicitações de IA). Pode haver processamento internacional conforme os contratos aplicáveis. A configuração específica de retenção e eventual uso de dados pela OpenAI para treinamento deve ser confirmada contratualmente; não afirmamos uma garantia que não foi verificada."
  ]},
  {title:"4. Dados das APIs do Google — Limited Use", paragraphs:[
    "O uso e a transferência de informações recebidas das APIs do Google observam a Google API Services User Data Policy, incluindo os requisitos de Limited Use. O uso destina-se às funções solicitadas pelo usuário; não se destina à venda de dados do Google nem à publicidade personalizada baseada nesses dados. O acesso humano a dados do Google deve ficar restrito às hipóteses permitidas pela política, como consentimento afirmativo, segurança, obrigação legal ou operações internas com dados agregados e desidentificados."
  ]},
  {title:"5. Retenção, desconexão e direitos", paragraphs:[
    "Os dados são mantidos conforme a prestação do serviço, obrigações legais e contratos. Prazo de retenção: [PRAZO DE RETENÇÃO — definir com jurídico]. Desconectar uma conta interrompe novas coletas pela autorização local, mas não elimina automaticamente o histórico importado. A empresa pode revogar permissões nas configurações do provedor e solicitar exclusão do histórico pela página de exclusão de dados.",
    "Solicitações de informação, correção, acesso ou exclusão são verificadas para impedir o acesso indevido aos dados de outra empresa. O Mugoverso não vende dados de clientes como produto."
  ]}
];
const privacyEN: Section[] = [
  {title:"1. Operator, context and purposes", paragraphs:[
    "Mugoverso is a B2B marketing, commerce and operations analytics SaaS platform provided by Mugô. The legal entity is [LEGAL ENTITY NAME], [BRAZILIAN TAX ID/CNPJ]. Controller and processor roles depend on the applicable contract.",
    "Data is processed to authenticate users, connect selected accounts, provide dashboards and reports, plan campaigns, support customers, secure the service and, when requested, generate AI-assisted insights. The applicable legal basis depends on the processing activity and may include contract performance, legal obligations, legitimate interests with safeguards, or consent when required."
  ]},
  {title:"2. Data accessed via authorized integrations", paragraphs:["Each feature depends on provider approval, granted permissions and the organization's authorization. A supported connector is not necessarily enabled for every organization."], points:[
    "Meta / Facebook / Instagram: authorized account identity (public_profile), Pages (pages_show_list, pages_read_engagement), professional Instagram content and insights (instagram_basic, instagram_manage_insights), ad reports (ads_read) and Business Manager discovery (business_management). When ads_management is authorized, Media On may create paused campaigns, ad sets, creatives and ads.",
    "Google: OAuth account identity, GA4 reporting (analytics.readonly), Google Ads reporting (adwords), and read-only Google Calendar events (calendar.readonly) when enabled.",
    "Shopify: orders, products and customers (read_orders, read_all_orders when authorized, read_products, read_customers). Orders may include end-customer names, contact information, addresses and purchased items.",
    "TikTok Ads: authorized ad accounts and campaign spend, impressions, clicks, conversions and related metrics from the Marketing API.",
    "TikTok organic: basic account data, profile statistics and authorized videos (user.info.basic, user.info.stats and video.list). This read-only connection does not publish, edit or delete videos.",
    "Pinterest: accounts, boards and pins (user_accounts:read, boards:read and pins:read), plus advertising metrics (ads:read).",
    "LinkedIn: ad accounts and reporting (r_ads, r_ads_reporting), authorized organization page information and content (r_organization_admin, r_organization_social).",
    "Microsoft Clarity: aggregated site interaction metrics obtained with an authorized project token, including session and navigation metrics. This is not unrestricted access to session recordings.",
    "AI and public research: questions and selected authorized business context may be sent to the OpenAI API to generate analyses. Public search results may provide external links and citations."
  ]},
  {title:"3. Security and service providers", paragraphs:[
    "Access is authenticated and restricted to authorized organizations. The backend checks tenant permissions and encrypts stored integration credentials without exposing API secrets to the browser.",
    "Infrastructure providers include Vercel (frontend), Render (backend), Supabase (authentication and database), and OpenAI (AI request processing). International processing may occur under applicable agreements. Specific OpenAI training and retention settings must be confirmed against the actual account configuration; no unverified guarantee is made."
  ]},
  {title:"4. Google API Services User Data Policy — Limited Use", paragraphs:[
    "Use and transfer of information received from Google APIs adhere to the Google API Services User Data Policy, including its Limited Use requirements. Google user data is used to provide user-requested functions, not sold or used for personalized advertising based on that data. Human access must be restricted to policy-permitted circumstances, such as affirmative consent, security, legal obligations, or aggregated and de-identified internal operations."
  ]},
  {title:"5. Retention, disconnection and rights", paragraphs:[
    "Records are retained as needed for service delivery, legal obligations and contracts. Retention period: [RETENTION PERIOD — legal review required]. Disconnecting an account stops further access under the local authorization but does not automatically erase imported historical metrics. Users may revoke permissions through the respective providers and request removal under the Data Deletion instructions.",
    "Access, correction, information and deletion requests are verified to prevent unauthorized changes to another organization's information. Mugoverso does not sell customer data as a product."
  ]}
];
const deletionPT: Section[] = [
  {title:"1. Como solicitar", paragraphs:["Envie um e-mail ao contato abaixo com o assunto 'Exclusão de dados — Mugoverso'. Informe empresa, nome e e-mail profissional da pessoa responsável, provedor afetado e se deseja remover a conexão, o histórico importado ou ambos. Não envie senhas nem tokens."]},
  {title:"2. Verificação e prazo", paragraphs:["Confirmaremos a identidade e o vínculo da pessoa solicitante com a empresa. Prazo de resposta: [PRAZO — definir com jurídico]. Obrigações legais ou contratuais podem exigir retenção limitada de certos registros; eventuais restrições serão explicadas."]},
  {title:"3. Escopo da exclusão", paragraphs:["Após validação, a equipe avaliará a remoção de tokens e credenciais, conexões, dados pessoais relacionados, métricas em channel_daily_metrics e tabelas equivalentes para Meta, Google, Shopify, TikTok, Pinterest, LinkedIn e outros provedores. Excluir dados históricos é diferente de desconectar a conta e requer procedimento específico."]},
  {title:"4. Desconectar e revogar", paragraphs:["Quando disponível, desconecte os canais nas áreas de Integrações ou Mídia do Mugoverso. Revogue também o acesso nas configurações de aplicativos conectados da Meta, Google, TikTok, Pinterest e LinkedIn, ou na área de apps da Shopify. A revogação no provedor não exclui automaticamente métricas previamente importadas."]},
  {title:"5. Confirmação", paragraphs:["Após análise, responderemos com o escopo de exclusão realizado, limitações aplicáveis e eventuais dados retidos por obrigação."]}
];
const deletionEN: Section[] = [
  {title:"1. Requesting deletion", paragraphs:["Email the address below with the subject 'Data deletion — Mugoverso'. Include the business name, authorized requester's name and business email, provider, and whether you want the connection, imported history, or both removed. Do not send passwords or tokens."]},
  {title:"2. Verification and timeframe", paragraphs:["We verify identity and organizational authorization before processing. Response timeframe: [RESPONSE TIME — legal review required]. Legal or contractual obligations may require limited retention of some records; applicable restrictions will be explained."]},
  {title:"3. Data covered", paragraphs:["Following verification, deletion may involve tokens, credentials, connection records, related personal data, metrics in channel_daily_metrics and equivalent Meta, Google, Shopify, TikTok, Pinterest, LinkedIn and other provider tables. Historical deletion is different from disconnecting an account and requires a separate procedure."]},
  {title:"4. Disconnect and revoke access", paragraphs:["Where available, disconnect channels in Mugoverso Integrations or Media. Also revoke access in connected-app settings at Meta, Google, TikTok, Pinterest and LinkedIn, or in Shopify's app settings. Provider revocation does not automatically erase previously imported metrics."]},
  {title:"5. Confirmation", paragraphs:["We will respond confirming the scope of deletion completed, applicable limitations, and any records legally required to be retained."]}
];
const termsPT: Section[] = [
  {title:"1. Prestador e serviço", paragraphs:["O Mugoverso é disponibilizado por [RAZÃO SOCIAL], [CNPJ], como plataforma SaaS B2B de análise de marketing e operações. Esta minuta depende de revisão jurídica antes de produzir efeitos contratuais."]},
  {title:"2. Contas e acesso por empresa", paragraphs:["Cada empresa gerencia os usuários autorizados e deve proteger suas credenciais. A plataforma aplica segregação de acesso entre empresas; o acesso depende do papel e das autorizações atribuídas."]},
  {title:"3. Responsabilidades e uso aceitável", paragraphs:["A empresa deve possuir autorização para conectar contas de terceiros e tratar os dados importados. É proibido acessar informações de outras empresas, contornar controles, distribuir conteúdo ilícito ou utilizar o serviço de forma abusiva."]},
  {title:"4. Integrações e dados", paragraphs:["As integrações Meta, Google, Shopify, TikTok, Pinterest, LinkedIn e outras dependem das políticas, disponibilidade e aprovações dos respectivos fornecedores. Os dados comerciais fornecidos ou conectados pelo cliente permanecem sob sua titularidade, observados os direitos de terceiros."]},
  {title:"5. Inteligência artificial", paragraphs:["Análises e recomendações geradas por IA são auxiliares e podem conter imprecisões. A empresa deve conferir informações antes de tomar decisões sobre anúncios, investimentos, contratos ou tratamento de dados pessoais."]},
  {title:"6. Disponibilidade e responsabilidade", paragraphs:["Níveis de serviço, disponibilidade, limitações e responsabilidade: [DISPONIBILIDADE E RESPONSABILIDADE — definir com jurídico]. Não há promessa de funcionamento ininterrupto ou de resultado comercial garantido."]},
  {title:"7. Encerramento e exclusão", paragraphs:["Condições de encerramento: [REGRAS DE ENCERRAMENTO — definir com jurídico]. A desconexão de um serviço não remove automaticamente o histórico; solicitações de exclusão seguem a Política de Privacidade e a página de Exclusão de Dados."]},
  {title:"8. Alterações, foro e contato", paragraphs:["Alterações destes termos serão informadas conforme procedimento contratual a definir. Foro: [FORO — definir com jurídico]. Entre em contato pelo canal abaixo."]}
];
const termsEN: Section[] = [
  {title:"1. Provider and service", paragraphs:["Mugoverso is provided by [LEGAL ENTITY NAME], [BRAZILIAN TAX ID/CNPJ], as a B2B marketing analytics and operations SaaS platform. This draft requires legal approval before becoming contractually effective."]},
  {title:"2. Organization accounts", paragraphs:["Each business manages its authorized users and protects login credentials. Access is separated by organization and governed by assigned roles and permissions."]},
  {title:"3. Responsibilities and acceptable use", paragraphs:["Customers must be entitled to connect third-party accounts and process imported data. Unauthorized cross-tenant access, bypassing security controls, unlawful content and abusive use are prohibited."]},
  {title:"4. Integrations and data ownership", paragraphs:["Meta, Google, Shopify, TikTok, Pinterest, LinkedIn and other integrations are subject to the respective providers' terms, availability and approvals. Customer-supplied business data remains the customer's data, subject to third-party rights."]},
  {title:"5. Artificial intelligence", paragraphs:["AI-generated insights and recommendations are advisory and may be inaccurate. Customers must verify outputs before making advertising, financial, contractual or personal-data decisions."]},
  {title:"6. Availability and liability", paragraphs:["Service levels, availability and limitations of liability: [SERVICE LEVELS AND LIABILITY — legal review required]. Uninterrupted access and commercial outcomes are not guaranteed."]},
  {title:"7. Termination and deletion", paragraphs:["Termination rules: [TERMINATION RULES — legal review required]. Disconnecting a provider does not automatically erase imported history; deletion requests follow the Privacy Policy and Data Deletion page."]},
  {title:"8. Amendments, venue and contact", paragraphs:["Amendment notice processes remain subject to contract. Venue: [VENUE — legal review required]. Contact us using the address below."]}
];
export function PrivacyPage() {
  const en = english();
  return <main className="legalPage" data-public-route="privacy" data-legal-status="draft-legal-review">
    <LegalHeader title={en ? "Privacy Policy" : "Política de Privacidade"} summary={en ? "How authorized data is processed in the Mugoverso platform." : "Como tratamos os dados autorizados na plataforma Mugoverso."} page="privacy" en={en}/>
    <article className="legalContent"><LegalSections sections={en ? privacyEN : privacyPT}/><section><h2>{en ? "6. Contact" : "6. Contato"}</h2><p data-legal-contact="privacy">{LEGAL_CONTACT}</p>
      <p><a href={urls.deletion[en ? 1 : 0]}>{en ? "Data deletion instructions" : "Instruções de exclusão de dados"}</a></p></section></article><LegalFooter en={en}/>
  </main>;
}
export function DataDeletionPage() {
  const en = english();
  return <main className="legalPage" data-public-route="data-deletion" data-legal-status="draft-legal-review">
    <LegalHeader title={en ? "Data Deletion" : "Exclusão de dados"} summary={en ? "Request deletion of imported data and account authorizations." : "Como solicitar a exclusão de dados importados e autorizações."} page="deletion" en={en}/>
    <article className="legalContent"><LegalSections sections={en ? deletionEN : deletionPT}/><section><h2>{en ? "6. Contact" : "6. Contato"}</h2><p data-legal-contact="data-deletion">{LEGAL_CONTACT}</p></section></article><LegalFooter en={en}/>
  </main>;
}
export function TermsPage() {
  const en = english();
  return <main className="legalPage" data-public-route="terms" data-legal-status="draft-legal-review">
    <LegalHeader title={en ? "Terms of Service" : "Termos de Uso"} summary={en ? "Terms for the B2B Mugoverso service." : "Condições de utilização do serviço B2B Mugoverso."} page="terms" en={en}/>
    {import.meta.env.MODE !== "production" ? <aside className="legalDraftNote" role="note">{en ? "Legal draft — not approved for publication." : "Minuta pendente de revisão jurídica — não publicar."}</aside> : null}
    <article className="legalContent"><LegalSections sections={en ? termsEN : termsPT}/><section><h2>{en ? "9. Contact" : "9. Contato"}</h2><p data-legal-contact="terms">{LEGAL_CONTACT}</p></section></article><LegalFooter en={en}/>
  </main>;
}

export function DataProtectionPage() {
  return (
    <main className="legalPage" data-public-route="data-protection" data-legal-status="review-pending">
      <LegalHeader
        title="Proteção de dados"
        summary="Conheça as práticas aplicadas pelo Mugoverso para limitar acessos e proteger informações das empresas usuárias."
      />
      <article className="legalContent">
        <section>
          <h2>Controles de acesso</h2>
          <p>
            O acesso ao Mugoverso exige autenticação. As permissões são definidas por papéis, e cada pessoa
            acessa somente as funções e empresas para as quais possui autorização. Operações administrativas
            sensíveis possuem verificações adicionais no backend.
          </p>
        </section>

        <section>
          <h2>Isolamento entre empresas</h2>
          <p>
            Registros, conexões e métricas são associados a um identificador de empresa. A API valida esse
            vínculo antes de autorizar leituras ou alterações, reduzindo o risco de acesso aos dados de outro
            tenant.
          </p>
        </section>

        <section>
          <h2>Proteção de credenciais</h2>
          <p>
            Tokens de integrações são tratados e criptografados no backend antes da persistência. Credenciais
            privilegiadas não são enviadas ao navegador. O acesso técnico segue o princípio do menor privilégio
            compatível com cada operação.
          </p>
        </section>

        <section>
          <h2>Auditoria e operação segura</h2>
          <p>
            A plataforma registra eventos relevantes de administração, acesso de suporte e conexões para apoiar
            rastreabilidade e investigação. Esses registros não devem conter tokens, senhas ou chaves privadas.
            Rotinas de sincronização também mantêm informações operacionais de execução e falha.
          </p>
        </section>

        <section>
          <h2>Solicitações e incidentes</h2>
          <p>
            Para comunicar uma preocupação de segurança ou fazer uma solicitação sobre dados, utilize o canal
            de atendimento informado no contrato, proposta ou onboarding da sua empresa. Informe o nome da
            empresa e mencione “Proteção de dados — Mugoverso”.
          </p>
          <p>
            Consulte também a <a href="/privacidade">Política de Privacidade</a> e as instruções de
            <a href="/exclusao-de-dados"> exclusão de dados</a>.
          </p>
        </section>
      </article>
      <LegalFooter />
    </main>
  );
}

