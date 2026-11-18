import { useCallback, useEffect, useState } from "react";
import { http } from "../../app/api";
import { getActiveClientId } from "../../app/activeClient";

type Summary = {
  total: number; unique: number; email_opt_in_claimed: number; whatsapp_opt_in_claimed: number;
  consent_verified: number; pending_validation: number;
  daily: {day: string; leads: number}[];
  sources: {source: string; leads: number}[];
  sending_enabled: boolean;
};
const CAMPAIGN = "roove_first_access_2026";
type Recent = { id: string; name: string; email_masked: string; phone_masked: string; utm_source: string; email_opt_in_claimed: boolean; whatsapp_opt_in_claimed: boolean; consent_verified: boolean };
export default function FirstAccessLeads({canEdit = false}:{canEdit?: boolean}) {
  const clientId = getActiveClientId();
  const [report, setReport] = useState<Summary | null>(null);
  const [recent, setRecent] = useState<Recent[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const refresh = useCallback(async () => {
    if (!clientId) return;
    setLoading(true);
    try {
      const result = await http<Summary & {ok: true}>(`/api/relationship/campaigns/${CAMPAIGN}/summary?client_id=${encodeURIComponent(clientId)}`);
      if (getActiveClientId() === clientId) { setReport(result); setError(""); }
      if(canEdit){
        try { const response = await http<{contacts:Recent[]}>("/api/relationship/campaigns/"+CAMPAIGN+"/recent?client_id="+encodeURIComponent(clientId));
          if(getActiveClientId()===clientId)setRecent(response.contacts);
        } catch { if(getActiveClientId()===clientId)setRecent([]); }
      }
    } catch (err) {
      if (getActiveClientId() === clientId) setError(err instanceof Error ? err.message : "Falha ao carregar.");
    } finally { if (getActiveClientId() === clientId) setLoading(false); }
  }, [clientId, canEdit]);
  useEffect(() => {
    setReport(null); setRecent([]);
    void refresh();
    const id = window.setInterval(() => void refresh(), 60000);
    return () => window.clearInterval(id);
  }, [refresh]);
  return <section className="emFirstAccess" aria-label="Captação Roove First Access">
    <header style={{display:"flex",justifyContent:"space-between",gap:12,alignItems:"center",flexWrap:"wrap"}}>
      <div>
        <h2>Roove · First Access</h2>
        <p>Captação para 26/11/2026 às 12h. Dados desta empresa, separados dos disparos.</p>
      </div>
      <button className="ds-button" type="button" onClick={() => void refresh()} disabled={loading}>Atualizar</button>
    </header>
    <p role="status"><strong>Disparos não habilitados por esta integração.</strong> Aceites informados são declarações pendentes de verificação.</p>
    {error ? <p className="studioError" role="alert">{error}</p> : null}
    {!report && loading ? <p>Carregando captação…</p> : null}
    {report ? <>
      <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(160px,1fr))",gap:12,margin:"20px 0"}}>
        {[
          ["Leads recebidos",report.total],["Leads únicos",report.unique],
          ["Aceite e-mail declarado",report.email_opt_in_claimed],
          ["Aceite WhatsApp declarado",report.whatsapp_opt_in_claimed],
          ["Consentimentos verificados",report.consent_verified],
          ["Pendentes de validação",report.pending_validation],
        ].map(([label,value])=><div key={label} style={{border:"1px solid #dbe0e5",borderRadius:12,padding:18}}>
          <strong style={{fontSize:27,display:"block"}}>{value}</strong>
          <span style={{fontSize:12}}>{label}</span>
        </div>)}
      </div>
      <h3>Cadastros por dia</h3>
      {report.daily.length ? <div style={{overflowX:"auto"}}><table><thead><tr><th>Dia</th><th>Leads</th></tr></thead>
        <tbody>{report.daily.map(item=><tr key={item.day}><td>{item.day.split("-").reverse().join("/")}</td><td>{item.leads}</td></tr>)}</tbody>
      </table></div> : <p>Nenhum cadastro registrado ainda.</p>}
      {canEdit ? <><h3>Cadastros recentes (contatos protegidos)</h3>
      {recent.length ? <div style={{overflowX:"auto"}}><table><thead><tr><th>Nome</th><th>E-mail</th><th>WhatsApp</th><th>Origem</th><th>Consentimento</th></tr></thead><tbody>{recent.map(item=><tr key={item.id}><td>{item.name}</td><td>{item.email_masked}</td><td>{item.phone_masked}</td><td>{item.utm_source}</td><td>{item.consent_verified ? "Verificado" : "Pendente"}</td></tr>)}</tbody></table></div> : <p>Nenhum cadastro recente.</p>}
      </> : null}
      <h3>Origem dos cadastros</h3>
      {report.sources.length ? <div style={{overflowX:"auto"}}><table><thead><tr><th>Origem UTM</th><th>Leads</th></tr></thead>
        <tbody>{report.sources.map(item=><tr key={item.source}><td>{item.source}</td><td>{item.leads}</td></tr>)}</tbody>
      </table></div> : <p>Sem origens registradas.</p>}
    </> : null}
  </section>;
}
