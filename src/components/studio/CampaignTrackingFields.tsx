import type { TrackingParams } from "../../app/adTracking";
import "./campaignTrackingFields.css";
import { slugForTracking, trackingSearch } from "../../app/adTracking";

type Props = {
  platform: "meta" | "google";
  campaignName: string;
  value: TrackingParams;
  onChange: (value: TrackingParams) => void;
  disabled?: boolean;
};
const FIELDS = [
  { key: "utm_source", label: "Origem" },
  { key: "utm_medium", label: "Mídia" },
  { key: "utm_campaign", label: "Campanha" },
  { key: "utm_content", label: "Criativo (opcional)" },
  { key: "utm_term", label: "Termo (opcional)" },
] as const;
export default function CampaignTrackingFields({platform,campaignName,value,onChange,disabled}: Props) {
  const params = value || {};
  const suggestion: TrackingParams = {
    utm_source: platform === "meta" ? "meta" : "google",
    utm_medium: platform === "meta" ? "paid_social" : "cpc",
    utm_campaign: slugForTracking(campaignName) || "campanha",
  };
  const preview = trackingSearch(params);
  return <fieldset className="mediaTrackingFields" disabled={disabled}>
    <legend>Rastreamento e UTMs</legend>
    <div className="mediaTrackingHeader">
      <p>Identifique a origem dos cadastros e das vendas nos relatórios do Mugô e no Analytics.
        Os parâmetros serão enviados à plataforma somente quando criar o anúncio.</p>
      <button type="button" className="ds-button" disabled={disabled}
        onClick={() => onChange({...suggestion, ...params})}>Preencher sugestão</button>
    </div>
    <div className="mediaTrackingGrid">
      {FIELDS.map(field => <label key={field.key}>{field.label}
        <input type="text" maxLength={150} value={params[field.key] || ""}
          placeholder={suggestion[field.key] || "Opcional"}
          onChange={e => onChange({...params,[field.key]:e.target.value})} />
      </label>)}
    </div>
    <p className="mediaTrackingPreview"><b>Parâmetros de URL:</b> {preview || "Nenhum parâmetro configurado"}
    </p>
    <small>UTMs não substituem o Pixel, o CAPI nem as conversões do Google. Não adicione dados pessoais às tags.</small>
  </fieldset>;
}
