import { useCallback, useState } from "react";
import { getActiveClient, getActiveClientName } from "../app/activeClient";
import { senderNotice, type SenderStatus } from "../app/emailMarketing";
import PageHeader from "../components/data/PageHeader";
import SegmentedControl from "../components/data/SegmentedControl";
import CampaignsPanel from "../components/email/CampaignsPanel";
import CartRecoveryPanel from "../components/email/CartRecoveryPanel";
import FlowsPanel from "../components/email/FlowsPanel";
import SenderPanel from "../components/email/SenderPanel";
import Shell from "../components/Shell";
import "../styles/emailMarketing.css";

type Tab = "campanhas" | "fluxos" | "carrinho" | "remetente";
const TABS = [
  { id: "campanhas", label: "Campanhas" },
  { id: "fluxos", label: "Fluxos automáticos" },
  { id: "carrinho", label: "Carrinho abandonado" },
  { id: "remetente", label: "Remetente" },
];

/** E-mail marketing (Resend) e recuperação de carrinho (e-mail + WhatsApp) da marca ativa. */
export default function EmailMarketing({ initialTab = "campanhas" }: { initialTab?: Tab } = {}) {
  const [tab, setTab] = useState<Tab>(initialTab);
  const [status, setStatus] = useState<SenderStatus | null>(null);
  const role = String(getActiveClient()?.role || "").toLowerCase();
  // Alterar e enviar: equipe Mugô e admin do cliente (o backend confere de novo em cada chamada).
  const canEdit = ["agency_admin", "platform_admin", "client_admin", "owner", "admin", "account_manager"].includes(role);
  const onStatus = useCallback((next: SenderStatus) => setStatus(next), []);
  const notice = tab !== "remetente" ? senderNotice(status) : null;

  return (
    <Shell title="E-mail marketing" variant="editorial">
      <div className="ds-page emPage">
        <PageHeader company={getActiveClientName()} title="E-mail marketing"
          dateline={<span>Campanhas, fluxos automáticos e recuperação de carrinho por e-mail e WhatsApp. E-mail pelo Resend.</span>}
          controls={<SegmentedControl ariaLabel="Seções" value={tab} onSelect={(id) => setTab(id as Tab)} options={TABS} />} />
        {/* O status do remetente é lido uma vez e vale para as três abas. */}
        <div hidden={tab !== "remetente"}><SenderPanel canEdit={canEdit} onStatus={onStatus} /></div>
        {notice ? <p className="emNotice">{notice}</p> : null}
        {tab === "campanhas" ? <CampaignsPanel canEdit={canEdit} /> : null}
        {tab === "fluxos" ? <FlowsPanel canEdit={canEdit} /> : null}
        {tab === "carrinho" ? <CartRecoveryPanel canEdit={canEdit} /> : null}
      </div>
    </Shell>
  );
}
