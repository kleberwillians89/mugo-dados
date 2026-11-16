import MugoLogo from "../components/MugoLogo";
import { LEGAL_CONTACT } from "../app/legalContact";
import "../styles/LegalPages.css";

/* Textos legais da AURUM INTELLIGENCE LTDA (marca Mugô). Ainda passam por revisão jurídica final:
   ficam pendentes só o nome do Encarregado (DPO), o foro e os níveis de serviço. Não afirmar
   certificação nem configuração de treinamento da OpenAI que não esteja contratada. */
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
const COMPANY = "AURUM INTELLIGENCE LTDA";
const CNPJ = "63.072.471/0001-25";
const RETENTION_DAYS = 90;

const privacyPT: Section[] = [
  {title:"1. Quem somos e papéis na LGPD", paragraphs:[
    `O Mugoverso é uma plataforma SaaS B2B da marca Mugô, operada por ${COMPANY}, CNPJ ${CNPJ} ("nós"), para análise de marketing, comércio, relacionamento e operações de empresas clientes.`,
    "Somos CONTROLADORES dos dados das pessoas que usam a plataforma (cadastro, login, papéis, registros de uso e suporte). Somos OPERADORES dos dados que cada empresa cliente conecta ou envia (contas de anúncios, redes sociais, loja, documentos e dados de compradores finais): nesses casos a empresa cliente é a controladora e nós tratamos os dados somente para prestar o serviço contratado, conforme as instruções dela.",
  ]},
  {title:"2. Dados que tratamos", points:[
    "Usuários da plataforma: nome, e-mail profissional, empresa, papel e permissões, registros de acesso (data, hora, IP) e preferências da interface.",
    "Dados das integrações autorizadas por cada empresa: métricas de anúncios, redes sociais, site e loja; conteúdos publicados; comentários e mensagens recebidas nos canais conectados; pedidos e produtos. Pedidos da loja (Shopify, FBits) podem conter nome, contato, endereço e itens comprados de compradores finais.",
    "Materiais enviados pela empresa (apresentações, briefings, tabelas) e informações de negócio cadastradas (perfil da marca, metas, fornecedores, concorrentes monitorados).",
    "Não tratamos dados pessoais sensíveis (art. 5º, II, LGPD) de forma intencional nem dados de crianças e adolescentes. A empresa cliente não deve enviar esse tipo de dado.",
  ]},
  {title:"3. Para que usamos e bases legais (art. 7º da LGPD)", points:[
    "Prestar o serviço contratado: autenticar, conectar contas, gerar painéis, relatórios, calendários e campanhas (execução de contrato, art. 7º, V).",
    "Análises e recomendações por IA solicitadas pela empresa (execução de contrato; para dados de compradores finais, conforme instruções do controlador).",
    "Segurança, prevenção a fraudes, auditoria e melhoria da plataforma com dados agregados (legítimo interesse, art. 7º, IX, com avaliação de impacto e medidas de proteção).",
    "Guarda de registros de acesso e cumprimento de obrigações legais e regulatórias (art. 7º, II; Marco Civil da Internet, art. 15).",
    "E-mail marketing e mensagens promocionais enviadas pela empresa cliente aos seus contatos: base legal definida pela empresa controladora, em regra o consentimento, com descadastro em 1 clique em cada envio.",
  ]},
  {title:"4. Integrações autorizadas", paragraphs:["Cada conector só funciona depois que a empresa autoriza a conta no provedor, e só com as permissões concedidas."], points:[
    "Meta / Facebook / Instagram: identificação da conta (public_profile), Páginas (pages_show_list, pages_read_engagement), conteúdo profissional e insights (instagram_basic, instagram_manage_insights), comentários e mensagens recebidas para resposta pela equipe, relatórios de anúncios (ads_read) e Business Managers (business_management). Com ads_management, o Mídia On cria campanhas, conjuntos, criativos e anúncios em estado pausado.",
    "Google: identificação via OAuth; Google Analytics 4 (analytics.readonly), Google Ads (adwords) e eventos do Calendar (calendar.readonly), quando vinculados.",
    "Shopify e FBits: pedidos, produtos e clientes da loja, inclusive dados de compradores finais.",
    "TikTok (anúncios e orgânico, somente leitura), Pinterest, LinkedIn, Microsoft Clarity (métricas agregadas) e WhatsApp (mensagens da equipe e do canal conectado).",
  ]},
  {title:"5. Inteligência artificial e pesquisa pública", paragraphs:[
    "As funções de IA (Tira-dúvidas, criação de conteúdo, briefing, esteira de agentes, clipping) enviam à API da OpenAI a pergunta e o contexto de negócio autorizado daquela empresa. Antes do envio, aplicamos minimização: textos com padrão de e-mail, telefone, CPF ou CNPJ são removidos, dados de compradores vão apenas agregados (totais, nunca a pessoa) e telefone, e-mail e nome de contato de fornecedores não são enviados.",
    "A pesquisa pública na web (Brave Search) recebe apenas termos públicos, como o nome da marca, o segmento e os concorrentes monitorados; nunca perguntas, métricas, documentos ou dados pessoais.",
    "Conteúdo gerado por IA é uma sugestão e passa por revisão humana da equipe antes de ser publicado ou enviado ao cliente.",
  ]},
  {title:"6. Com quem compartilhamos (operadores e suboperadores)", points:[
    "Vercel (hospedagem do site), Render (servidor de aplicação), Supabase (autenticação e banco de dados), GitHub (execução de rotinas automáticas), OpenAI (processamento de IA) e Brave Search (pesquisa pública).",
    "Os provedores das integrações (Meta, Google, Shopify, FBits, TikTok, Pinterest, LinkedIn, Microsoft) quando a empresa conecta ou age por eles.",
    "Autoridades, quando houver obrigação legal ou ordem judicial. Não vendemos dados pessoais.",
  ]},
  {title:"7. Transferência internacional", paragraphs:[
    "Parte dos provedores processa dados fora do Brasil (por exemplo, Estados Unidos). Essas transferências seguem o art. 33 da LGPD, com cláusulas contratuais e garantias de proteção oferecidas pelos provedores.",
  ]},
  {title:"8. Por quanto tempo guardamos", paragraphs:[
    `Enquanto o contrato estiver ativo, os dados ficam disponíveis para a prestação do serviço. Após o encerramento do contrato ou o pedido de exclusão de uma conexão, os dados da empresa e os importados das integrações são eliminados ou anonimizados em até ${RETENTION_DAYS} dias, prazo em que a empresa pode solicitar exportação.`,
    "Mantemos por mais tempo apenas o que a lei exige: registros de acesso por 6 meses (Marco Civil da Internet, art. 15) e documentos fiscais e contratuais pelos prazos legais.",
    "Desconectar uma conta interrompe novas coletas imediatamente; a eliminação do histórico já importado segue o prazo acima ou ocorre antes, a pedido.",
    "Cópias de segurança: mantemos backups criptografados (AES-256) do banco e dos arquivos, apenas para recuperação em caso de falha, por até 30 dias, em armazenamento privado. Um dado excluído a seu pedido sai da plataforma na hora e desaparece das cópias quando elas expiram, em até 30 dias; nesse período as cópias não são consultadas e, se houver restauração, os pedidos de exclusão já atendidos são reaplicados.",
  ]},
  {title:"9. Seus direitos (art. 18 da LGPD)", paragraphs:["O titular pode pedir, a qualquer momento:"], points:[
    "confirmação de que tratamos seus dados e acesso a eles;",
    "correção de dados incompletos, inexatos ou desatualizados;",
    "anonimização, bloqueio ou eliminação de dados desnecessários ou tratados em desconformidade;",
    "portabilidade a outro fornecedor;",
    "eliminação dos dados tratados com consentimento e informação sobre a possibilidade de não consentir;",
    "informação sobre com quem compartilhamos os dados;",
    "revogação do consentimento e revisão de decisões automatizadas.",
  ]},
  {title:"10. Como exercer e prazo de resposta", paragraphs:[
    "Pedidos de usuários da plataforma são respondidos por nós. Pedidos de compradores finais de uma loja cliente são encaminhados à empresa controladora, e nós a apoiamos no atendimento.",
    "Respondemos em até 15 dias (art. 19, II, LGPD), após confirmar a identidade e o vínculo do solicitante, para impedir acesso indevido a dados de outra pessoa ou empresa.",
  ]},
  {title:"11. Segurança e incidentes", paragraphs:[
    "Acesso autenticado e por papel, isolamento entre empresas validado no servidor, credenciais de integração criptografadas, registros de auditoria sem senhas ou tokens e menor privilégio para a equipe.",
    "Em incidente de segurança com risco relevante, comunicamos a ANPD e os titulares afetados em prazo razoável (art. 48 da LGPD) e as empresas clientes envolvidas.",
  ]},
  {title:"12. Cookies e armazenamento local", paragraphs:[
    "A plataforma usa apenas armazenamento essencial: a sessão de login e preferências da interface (por exemplo, menu recolhido). Não usamos cookies de publicidade nem rastreadores de terceiros no Mugoverso.",
  ]},
  {title:"13. Dados das APIs do Google — Limited Use", paragraphs:[
    "O uso e a transferência de informações recebidas das APIs do Google observam a Google API Services User Data Policy, incluindo os requisitos de Limited Use. Esses dados servem só às funções solicitadas pelo usuário, não são vendidos nem usados para publicidade personalizada, e o acesso humano fica restrito a consentimento afirmativo, segurança, obrigação legal ou operações internas com dados agregados e desidentificados.",
  ]},
  {title:"14. Encarregado (DPO) e alterações", paragraphs:[
    `Encarregado pelo tratamento de dados pessoais de ${COMPANY}: [NOME DO ENCARREGADO], pelo e-mail informado em Contato. Mudanças relevantes nesta política serão avisadas na plataforma.`,
  ]},
];
const privacyEN: Section[] = [
  {title:"1. Who we are and roles under the LGPD", paragraphs:[
    `Mugoverso is a B2B SaaS platform under the Mugô brand, operated by ${COMPANY}, Brazilian CNPJ ${CNPJ} ("we"), for marketing, commerce, relationship and operations analytics.`,
    "We are the CONTROLLER of platform users' data (registration, login, roles, usage logs and support). We are a PROCESSOR of data each customer connects or uploads (ad accounts, social media, store, documents and end-buyer data): the customer is the controller and we process it only to provide the contracted service, following its instructions.",
  ]},
  {title:"2. Data we process", points:[
    "Platform users: name, business email, company, role and permissions, access logs (date, time, IP) and interface preferences.",
    "Data from authorized integrations: ad, social, website and store metrics; published content; comments and messages received on connected channels; orders and products. Store orders (Shopify, FBits) may include end-buyer names, contact details, addresses and items.",
    "Materials uploaded by the customer and business information (brand profile, goals, suppliers, monitored competitors).",
    "We do not intentionally process sensitive personal data or data of children and adolescents. Customers must not upload such data.",
  ]},
  {title:"3. Purposes and legal bases (LGPD art. 7)", points:[
    "Providing the contracted service (contract performance, art. 7, V).",
    "AI analyses and recommendations requested by the customer (contract performance; for end-buyer data, per the controller's instructions).",
    "Security, fraud prevention, auditing and improvement using aggregated data (legitimate interest, art. 7, IX, with safeguards).",
    "Retention of access logs and compliance with legal obligations (art. 7, II; Brazilian Internet Civil Framework, art. 15).",
    "Email marketing sent by the customer to its contacts: legal basis defined by the customer as controller, usually consent, with one-click unsubscribe in every message.",
  ]},
  {title:"4. Authorized integrations", paragraphs:["Each connector only works after the customer authorizes the account at the provider, and only with the granted permissions."], points:[
    "Meta / Facebook / Instagram: account identity (public_profile), Pages (pages_show_list, pages_read_engagement), professional content and insights (instagram_basic, instagram_manage_insights), comments and messages received for team replies, ad reports (ads_read) and Business Managers (business_management). With ads_management, Media On creates paused campaigns, ad sets, creatives and ads.",
    "Google: OAuth identity; GA4 (analytics.readonly), Google Ads (adwords) and Calendar events (calendar.readonly) when enabled.",
    "Shopify and FBits: store orders, products and customers, including end-buyer data.",
    "TikTok (ads and organic, read-only), Pinterest, LinkedIn, Microsoft Clarity (aggregated metrics) and WhatsApp (team and connected channel messages).",
  ]},
  {title:"5. Artificial intelligence and public search", paragraphs:[
    "AI features send the question and the authorized business context of that customer to the OpenAI API. Before sending, we minimize data: text matching email, phone, CPF or CNPJ patterns is removed, buyer data is sent only as aggregates, and supplier contact details are never sent.",
    "Public web search (Brave Search) receives only public terms such as the brand name, segment and monitored competitors; never questions, metrics, documents or personal data.",
    "AI output is advisory and is reviewed by the team before being published or sent to the customer.",
  ]},
  {title:"6. Sharing (processors and sub-processors)", points:[
    "Vercel (website hosting), Render (application server), Supabase (authentication and database), GitHub (scheduled jobs), OpenAI (AI processing) and Brave Search (public search).",
    "Integration providers (Meta, Google, Shopify, FBits, TikTok, Pinterest, LinkedIn, Microsoft) when the customer connects or acts through them.",
    "Authorities, when legally required. We do not sell personal data.",
  ]},
  {title:"7. International transfers", paragraphs:["Some providers process data outside Brazil (e.g., United States), under LGPD art. 33 with contractual clauses and provider safeguards."]},
  {title:"8. Retention", paragraphs:[
    `While the contract is active, data is kept to provide the service. After termination or a deletion request for a connection, customer and imported data are deleted or anonymized within ${RETENTION_DAYS} days, during which the customer may request an export.`,
    "Only legally required records are kept longer: access logs for 6 months and tax and contract records for the legal periods.",
    "Disconnecting an account stops new collection immediately; previously imported history is deleted within the period above, or earlier upon request.",
    "Backups: encrypted (AES-256) backups of the database and files are kept only for disaster recovery, for up to 30 days, in private storage. Data deleted at your request leaves the platform immediately and disappears from backups when they expire, within 30 days; backups are not accessed during that period and, if a restore happens, completed deletion requests are re-applied.",
  ]},
  {title:"9. Data subject rights (LGPD art. 18)", points:[
    "confirmation and access; correction; anonymization, blocking or deletion; portability; deletion of consent-based data; information on sharing; consent withdrawal and review of automated decisions.",
  ]},
  {title:"10. Exercising rights and response time", paragraphs:[
    "We answer requests from platform users. Requests from a customer's end buyers are forwarded to that customer as controller, and we support the response.",
    "We respond within 15 days (LGPD art. 19, II) after verifying identity and authorization.",
  ]},
  {title:"11. Security and incidents", paragraphs:[
    "Authenticated role-based access, server-side tenant isolation, encrypted integration credentials, audit logs without passwords or tokens, and least privilege for staff.",
    "Security incidents with relevant risk are reported to the ANPD and affected data subjects within a reasonable time (LGPD art. 48), and to the customers involved.",
  ]},
  {title:"12. Cookies and local storage", paragraphs:["Only essential storage is used: the login session and interface preferences. No advertising cookies or third-party trackers run in Mugoverso."]},
  {title:"13. Google API Services User Data Policy — Limited Use", paragraphs:[
    "Use and transfer of information received from Google APIs adhere to the Google API Services User Data Policy, including Limited Use requirements. Google user data serves only user-requested functions, is not sold or used for personalized advertising, and human access is limited to affirmative consent, security, legal obligations or aggregated, de-identified internal operations.",
  ]},
  {title:"14. Data Protection Officer and changes", paragraphs:[
    `Data Protection Officer (Encarregado) of ${COMPANY}: [DPO NAME], reachable at the contact address below. Material changes to this policy will be announced in the platform.`,
  ]},
];
const deletionPT: Section[] = [
  {title:"1. Como solicitar", paragraphs:["Envie um e-mail ao contato abaixo com o assunto 'Exclusão de dados — Mugoverso'. Informe a empresa, o nome e o e-mail profissional da pessoa responsável, o provedor afetado e se deseja remover a conexão, o histórico importado ou ambos. Não envie senhas nem tokens."]},
  {title:"2. Verificação e prazo", paragraphs:["Confirmamos a identidade e o vínculo do solicitante com a empresa e respondemos em até 15 dias (art. 19, II, LGPD). Registros que a lei obriga a guardar (por exemplo, registros de acesso por 6 meses e documentos fiscais) ficam retidos pelo prazo legal, e informamos quais são."]},
  {title:"3. O que é excluído", paragraphs:[`Tokens e credenciais, conexões, dados pessoais relacionados, métricas e históricos importados de Meta, Google, Shopify, FBits, TikTok, Pinterest, LinkedIn e demais provedores, materiais enviados e conversas com a IA. Ao fim do contrato, a eliminação ou anonimização ocorre em até ${RETENTION_DAYS} dias mesmo sem pedido.`]},
  {title:"4. Desconectar e revogar", paragraphs:["Desconecte os canais em Integrações. Revogue também o acesso nas configurações de aplicativos conectados da Meta, Google, TikTok, Pinterest e LinkedIn, ou na área de apps da Shopify. A revogação no provedor interrompe novas coletas; o histórico importado é eliminado conforme o item 3."]},
  {title:"5. Compradores finais de uma loja", paragraphs:["Se você comprou de uma loja que usa o Mugoverso, a loja é a controladora dos seus dados. Encaminharemos o seu pedido a ela e apoiaremos a resposta."]},
  {title:"6. Confirmação", paragraphs:["Respondemos com o que foi excluído, o que ficou retido por obrigação legal e até quando."]},
];
const deletionEN: Section[] = [
  {title:"1. Requesting deletion", paragraphs:["Email the address below with the subject 'Data deletion — Mugoverso'. Include the business name, the requester's name and business email, the provider and whether you want the connection, imported history or both removed. Do not send passwords or tokens."]},
  {title:"2. Verification and timeframe", paragraphs:["We verify identity and authorization and respond within 15 days (LGPD art. 19, II). Records the law requires us to keep (e.g., access logs for 6 months and tax records) are retained for the legal period, and we tell you which."]},
  {title:"3. What is deleted", paragraphs:[`Tokens and credentials, connections, related personal data, imported metrics and history from Meta, Google, Shopify, FBits, TikTok, Pinterest, LinkedIn and other providers, uploaded materials and AI conversations. After contract termination, deletion or anonymization happens within ${RETENTION_DAYS} days even without a request.`]},
  {title:"4. Disconnect and revoke access", paragraphs:["Disconnect channels in Integrations. Also revoke access in the connected-app settings at Meta, Google, TikTok, Pinterest and LinkedIn, or in Shopify's app settings. Provider revocation stops new collection; imported history is deleted as described above."]},
  {title:"5. End buyers of a store", paragraphs:["If you bought from a store that uses Mugoverso, the store is the controller of your data. We forward your request to it and support the response."]},
  {title:"6. Confirmation", paragraphs:["We confirm what was deleted, what was retained under legal obligation and until when."]},
];
const termsPT: Section[] = [
  {title:"1. Prestador e serviço", paragraphs:[`O Mugoverso é disponibilizado por ${COMPANY}, CNPJ ${CNPJ}, sob a marca Mugô, como plataforma SaaS B2B de análise de marketing, comércio e operações.`]},
  {title:"2. Contas e acesso por empresa", paragraphs:["Cada empresa gerencia os usuários autorizados e deve proteger suas credenciais. A plataforma separa os dados por empresa; o acesso depende do papel e das permissões atribuídas."]},
  {title:"3. Responsabilidades e uso aceitável", paragraphs:["A empresa declara ter autorização para conectar contas de terceiros e tratar os dados importados, inclusive base legal para os dados de seus clientes finais (por exemplo, consentimento para e-mail marketing). É proibido acessar informações de outras empresas, contornar controles, distribuir conteúdo ilícito ou usar o serviço de forma abusiva."]},
  {title:"4. Integrações e titularidade dos dados", paragraphs:["As integrações dependem das políticas, disponibilidade e aprovações dos respectivos fornecedores. Os dados comerciais fornecidos ou conectados pela empresa permanecem dela; tratamos esses dados como operadores, para prestar o serviço."]},
  {title:"5. Inteligência artificial", paragraphs:["Análises, textos e recomendações geradas por IA são auxiliares e podem conter imprecisões. A empresa deve conferir antes de decidir sobre anúncios, investimentos, contratos ou dados pessoais."]},
  {title:"6. Disponibilidade e responsabilidade", paragraphs:["Níveis de serviço, disponibilidade e limitação de responsabilidade: [DISPONIBILIDADE E RESPONSABILIDADE — definir com jurídico]. Não há promessa de funcionamento ininterrupto nem de resultado comercial garantido."]},
  {title:"7. Encerramento e exclusão", paragraphs:[`Condições de encerramento: conforme contrato. Após o encerramento, a empresa pode pedir exportação e os dados são eliminados ou anonimizados em até ${RETENTION_DAYS} dias, salvo registros com guarda obrigatória por lei.`]},
  {title:"8. Proteção de dados", paragraphs:["O tratamento de dados pessoais segue a Política de Privacidade e a LGPD. As partes cooperam no atendimento a titulares e na comunicação de incidentes."]},
  {title:"9. Alterações e foro", paragraphs:["Alterações destes termos serão avisadas na plataforma com antecedência razoável. Foro: [FORO — definir com jurídico]."]},
];
const termsEN: Section[] = [
  {title:"1. Provider and service", paragraphs:[`Mugoverso is provided by ${COMPANY}, Brazilian CNPJ ${CNPJ}, under the Mugô brand, as a B2B marketing, commerce and operations SaaS platform.`]},
  {title:"2. Organization accounts", paragraphs:["Each business manages its authorized users and protects credentials. Data is separated by organization and access follows assigned roles and permissions."]},
  {title:"3. Responsibilities and acceptable use", paragraphs:["Customers declare they are entitled to connect third-party accounts and process imported data, including a legal basis for their end customers' data (e.g., consent for email marketing). Cross-tenant access, bypassing controls, unlawful content and abusive use are prohibited."]},
  {title:"4. Integrations and data ownership", paragraphs:["Integrations depend on providers' terms, availability and approvals. Customer business data remains the customer's; we process it as a processor to provide the service."]},
  {title:"5. Artificial intelligence", paragraphs:["AI-generated analyses, text and recommendations are advisory and may be inaccurate. Customers must verify before making advertising, financial, contractual or personal-data decisions."]},
  {title:"6. Availability and liability", paragraphs:["Service levels, availability and limitations of liability: [SERVICE LEVELS AND LIABILITY — legal review required]. Uninterrupted access and commercial outcomes are not guaranteed."]},
  {title:"7. Termination and deletion", paragraphs:[`Termination conditions: per contract. After termination, the customer may request an export and data is deleted or anonymized within ${RETENTION_DAYS} days, except records the law requires us to keep.`]},
  {title:"8. Data protection", paragraphs:["Personal data processing follows the Privacy Policy and the LGPD. The parties cooperate on data subject requests and incident notifications."]},
  {title:"9. Amendments and venue", paragraphs:["Amendments will be announced in the platform with reasonable notice. Venue: [VENUE — legal review required]."]},
];
export function PrivacyPage() {
  const en = english();
  return <main className="legalPage" data-public-route="privacy" data-legal-status="draft-legal-review">
    <LegalHeader title={en ? "Privacy Policy" : "Política de Privacidade"} summary={en ? "How authorized data is processed in the Mugoverso platform." : "Como tratamos os dados autorizados na plataforma Mugoverso."} page="privacy" en={en}/>
    <article className="legalContent"><LegalSections sections={en ? privacyEN : privacyPT}/><section><h2>{en ? "15. Contact" : "15. Contato"}</h2><p data-legal-contact="privacy">{LEGAL_CONTACT}</p>
      <p><a href={urls.deletion[en ? 1 : 0]}>{en ? "Data deletion instructions" : "Instruções de exclusão de dados"}</a></p></section></article><LegalFooter en={en}/>
  </main>;
}
export function DataDeletionPage() {
  const en = english();
  return <main className="legalPage" data-public-route="data-deletion" data-legal-status="draft-legal-review">
    <LegalHeader title={en ? "Data Deletion" : "Exclusão de dados"} summary={en ? "Request deletion of imported data and account authorizations." : "Como solicitar a exclusão de dados importados e autorizações."} page="deletion" en={en}/>
    <article className="legalContent"><LegalSections sections={en ? deletionEN : deletionPT}/><section><h2>{en ? "7. Contact" : "7. Contato"}</h2><p data-legal-contact="data-deletion">{LEGAL_CONTACT}</p></section></article><LegalFooter en={en}/>
  </main>;
}
export function TermsPage() {
  const en = english();
  return <main className="legalPage" data-public-route="terms" data-legal-status="draft-legal-review">
    <LegalHeader title={en ? "Terms of Service" : "Termos de Uso"} summary={en ? "Terms for the B2B Mugoverso service." : "Condições de utilização do serviço B2B Mugoverso."} page="terms" en={en}/>
    {import.meta.env.MODE !== "production" ? <aside className="legalDraftNote" role="note">{en ? "Legal draft — not approved for publication." : "Minuta pendente de revisão jurídica — não publicar."}</aside> : null}
    <article className="legalContent"><LegalSections sections={en ? termsEN : termsPT}/><section><h2>{en ? "10. Contact" : "10. Contato"}</h2><p data-legal-contact="terms">{LEGAL_CONTACT}</p></section></article><LegalFooter en={en}/>
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

