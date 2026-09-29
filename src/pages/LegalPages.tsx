import MugoLogo from "../components/MugoLogo";
import "../styles/LegalPages.css";

const LAST_UPDATED = "29 de setembro de 2026";

function LegalHeader({ title, summary }: { title: string; summary: string }) {
  return (
    <>
      <header className="legalHeader">
        <a className="legalBrand" href="/" aria-label="Mugô Dados — página inicial">
          <MugoLogo variant="responsive" />
        </a>
        <nav aria-label="Documentos legais">
          <a href="/privacidade">Privacidade</a>
          <a href="/exclusao-de-dados">Exclusão de dados</a>
        </nav>
      </header>
      <section className="legalHero">
        <p className="legalEyebrow">Mugô Dados</p>
        <h1>{title}</h1>
        <p>{summary}</p>
        <small>Última atualização: {LAST_UPDATED}</small>
      </section>
    </>
  );
}

function LegalFooter() {
  return (
    <footer className="legalFooter">
      <strong>Mugô Dados</strong>
      <span>Plataforma de dados e inteligência da Mugô.</span>
      <a href="/">Voltar ao acesso do Mugô Dados</a>
    </footer>
  );
}

export function PrivacyPage() {
  return (
    <main className="legalPage" data-public-route="privacy">
      <LegalHeader
        title="Política de Privacidade"
        summary="Esta política explica como o Mugô Dados trata informações autorizadas pelas empresas que conectam seus ativos da Meta à plataforma."
      />
      <article className="legalContent">
        <section>
          <h2>1. Sobre o Mugô Dados</h2>
          <p>
            O Mugô Dados é uma plataforma analítica utilizada por empresas atendidas pela Mugô para
            consolidar indicadores de marketing, conteúdo e mídia paga. Cada empresa acessa seu próprio
            ambiente e escolhe quais ativos deseja conectar.
          </p>
        </section>

        <section>
          <h2>2. Dados acessados na integração com a Meta</h2>
          <p>Quando uma pessoa autorizada conecta a Meta, o Mugô Dados pode acessar:</p>
          <ul>
            <li>identificação básica da conta Meta que realizou a autorização;</li>
            <li>Páginas do Facebook disponíveis para essa conta;</li>
            <li>identificação e conteúdo do Instagram profissional vinculado a uma Página;</li>
            <li>métricas de perfil, publicações, Reels e Stories do Instagram profissional;</li>
            <li>contas de anúncios selecionadas e métricas de campanhas, anúncios e criativos;</li>
            <li>Business Managers disponíveis, para apoiar a identificação dos ativos no onboarding.</li>
          </ul>
          <p>
            O Mugô Dados utiliza somente os ativos escolhidos durante a configuração. A integração não é
            destinada a contas pessoais do Instagram que não estejam disponíveis como conta profissional.
          </p>
        </section>

        <section>
          <h2>3. Finalidades</h2>
          <p>
            Os dados são tratados para autenticar a integração, descobrir e validar ativos, importar
            métricas autorizadas, produzir dashboards e relatórios, acompanhar desempenho orgânico e de
            mídia paga e manter o histórico analítico da empresa conectada.
          </p>
        </section>

        <section>
          <h2>4. Armazenamento, proteção e isolamento</h2>
          <p>
            As credenciais de integração são mantidas no backend de forma protegida e não são entregues ao
            navegador. Os registros e conexões são associados à empresa correspondente, e o acesso depende
            de autenticação e vínculo com essa empresa. Os dados podem ser processados pelos provedores de
            infraestrutura necessários para operar a plataforma, sujeitos aos controles aplicáveis ao serviço.
          </p>
        </section>

        <section>
          <h2>5. Compartilhamento e acesso</h2>
          <p>
            As informações ficam disponíveis no Mugô Dados para as pessoas autorizadas da empresa e para a
            equipe responsável pela operação e suporte da plataforma, conforme as permissões de acesso. O
            Mugô Dados não publica tokens de acesso nem os disponibiliza como parte dos relatórios.
          </p>
        </section>

        <section>
          <h2>6. Retenção, desconexão e revogação</h2>
          <p>
            A desconexão remove a credencial local usada para novas consultas, mas o histórico analítico já
            importado pode ser preservado. A pessoa autorizada também pode revogar o acesso nas configurações
            de integrações da própria Meta. Para pedir a remoção do histórico e dos dados associados, siga as
            instruções da página de <a href="/exclusao-de-dados">Exclusão de dados</a>.
          </p>
        </section>

        <section>
          <h2>7. Direitos e solicitações</h2>
          <p>
            A empresa ou pessoa responsável pode solicitar informações, correção, limitação de uso ou
            exclusão dos dados associados à sua conexão. A solicitação será verificada para evitar que uma
            pessoa sem autorização altere dados de outra empresa.
          </p>
        </section>

        <section>
          <h2>8. Contato</h2>
          <p>
            Para questões de privacidade, utilize o canal de atendimento da Mugô informado no contrato,
            proposta ou onboarding da sua empresa. Informe o nome da empresa e indique que o assunto é
            “Privacidade — Mugô Dados”.
          </p>
        </section>
      </article>
      <LegalFooter />
    </main>
  );
}

export function DataDeletionPage() {
  return (
    <main className="legalPage" data-public-route="data-deletion">
      <LegalHeader
        title="Exclusão de dados"
        summary="Veja como solicitar a remoção dos dados associados à integração da sua empresa com a Meta."
      />
      <article className="legalContent">
        <section>
          <h2>Como solicitar</h2>
          <p>
            Envie a solicitação pelo canal de atendimento da Mugô informado no contrato, proposta ou
            onboarding da sua empresa. Use o assunto “Exclusão de dados — Mugô Dados”. A exclusão não é
            automática: a equipe verifica a identidade e o vínculo da pessoa solicitante antes de executar
            a remoção aplicável.
          </p>
        </section>

        <section>
          <h2>Informações necessárias</h2>
          <p>Inclua na solicitação:</p>
          <ul>
            <li>nome da empresa conectada ao Mugô Dados;</li>
            <li>nome e e-mail profissional da pessoa solicitante;</li>
            <li>nome da conta Meta que realizou a autorização, quando disponível;</li>
            <li>Página, Instagram profissional ou conta de anúncios envolvidos;</li>
            <li>se deseja excluir toda a integração Meta ou somente dados específicos.</li>
          </ul>
          <p>
            Essas informações são usadas para localizar o tenant e a conexão corretos e impedir a remoção
            de dados pertencentes a outra empresa.
          </p>
        </section>

        <section>
          <h2>Revogar o acesso na Meta</h2>
          <p>
            Além de solicitar a exclusão à Mugô, a pessoa administradora pode revogar a autorização do
            aplicativo nas configurações de integrações empresariais da Meta. A revogação impede novas
            consultas com aquela autorização, mas não substitui o pedido de exclusão do histórico já
            importado no Mugô Dados.
          </p>
        </section>

        <section>
          <h2>O que acontece depois</h2>
          <p>
            Após validar a solicitação, a Mugô identifica as conexões e os registros relacionados à empresa,
            confirma o escopo pedido e informa o andamento pelo mesmo canal de atendimento. Dados que devam
            ser mantidos por obrigação legal ou para resguardar direitos podem seguir os prazos aplicáveis.
          </p>
        </section>

        <section>
          <h2>Dúvidas</h2>
          <p>
            Use o canal de atendimento já fornecido à sua empresa e mencione “Mugô Dados” para que a
            solicitação seja encaminhada à equipe responsável.
          </p>
        </section>
      </article>
      <LegalFooter />
    </main>
  );
}
