type Tone = "loading" | "empty" | "unavailable";

type Props = {
  title: string;
  description?: string;
  message: string;
  tone?: Tone;
  actionLabel?: string;
  onAction?: () => void;
  secondaryMessage?: string | null;
};

const TONE_LABEL: Record<Tone, string> = {
  loading: "Carregando",
  empty: "Sem dados",
  unavailable: "Indisponível",
};

export default function MetaStateNotice({
  title,
  description,
  message,
  tone = "empty",
  actionLabel,
  onAction,
  secondaryMessage = null,
}: Props) {
  return (
    <div className={`metaStateCard metaState-${tone}`}>
      <div className="metaStateHead">
        <div>
          <div className="metaStateTitle">{title}</div>
          {description ? <div className="metaStateDescription">{description}</div> : null}
        </div>
        <span className={`pill ${tone === "unavailable" ? "pillDanger" : "pillSoft"}`}>
          {TONE_LABEL[tone]}
        </span>
      </div>

      <div className="metaStateBody">
        <div className="metaStateMessage">{message}</div>
        {secondaryMessage ? <div className="smallMuted">{secondaryMessage}</div> : null}
      </div>

      {actionLabel && onAction ? (
        <div className="metaStateActions">
          <button type="button" className="btn btnGhost" onClick={onAction}>
            {actionLabel}
          </button>
        </div>
      ) : null}
    </div>
  );
}
