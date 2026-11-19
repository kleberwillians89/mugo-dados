import { getActiveClient, getActiveClientName } from "../app/activeClient";
import Shell from "../components/Shell";
import PageHeader from "../components/data/PageHeader";
import FirstAccessLeads from "../components/email/FirstAccessLeads";
import "../styles/emailMarketing.css";

/** Captação é compartilhada por e-mail e WhatsApp; nenhum envio é disparado nesta página. */
export default function Capture() {
  const role = String(getActiveClient()?.role || "").toLowerCase();
  const canEdit = ["agency_admin", "platform_admin", "client_admin", "owner", "admin", "account_manager"].includes(role);
  return <Shell title="Captação" variant="editorial">
    <div className="ds-page emPage">
      <PageHeader
        company={getActiveClientName()}
        title="Captação"
        dateline={<span>Fontes, campanhas e novos contatos para relacionamento por e-mail e WhatsApp.</span>}
      />
      <FirstAccessLeads canEdit={canEdit} />
    </div>
  </Shell>;
}
