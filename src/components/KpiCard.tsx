type Props = {
  label: string;
  value?: string | number;
  monthValue?: string | number;
  todayValue?: string | number;
  deltaPct?: number | null;
  deltaLabel?: string;
  hint?: string;
  spark?: number[];
  active?: boolean;
  tone?: "organic" | "ads";
  onClick?: () => void;
};

function clamp(n: number, a: number, b: number) {
  return Math.max(a, Math.min(b, n));
}

function normalizeSpark(values: number[]) {
  const normalized = values.map((x) => (Number.isFinite(x) ? x : 0));
  const max = Math.max(1, ...normalized);
  return normalized.map((x) => clamp(x / max, 0, 1));
}

function GrowthPill({ value }: { value: number | null }) {
  if (value === null || !Number.isFinite(value)) {
    return <span className="pill pillSoft">Novo</span>;
  }

  const up = value >= 0;
  const abs = Math.abs(value);
  const txt = `${up ? "↑" : "↓"} ${abs.toFixed(abs >= 10 ? 0 : 1)}%`;

  return <span className={`pill pillGrowth ${up ? "up" : "down"}`}>{txt}</span>;
}

export default function KpiCard(props: Props) {
  const main = props.monthValue ?? props.value ?? "0";
  const showToday =
    typeof props.todayValue === "string" || typeof props.todayValue === "number";
  const showDelta =
    Boolean(String(props.deltaLabel || "").trim()) ||
    typeof props.deltaPct === "number" || props.deltaPct === null;
  const deltaLabel = String(props.deltaLabel || "").trim();

  const spark = Array.isArray(props.spark) ? props.spark : [];
  const sparkNorm = spark.length ? normalizeSpark(spark) : [];

  const tone = props.tone || "organic";
  return (
    <div
      className={`kpiCard ${props.active ? "kpiActive" : ""} ${tone === "ads" ? "kpiCardAds" : "kpiCardOrganic"}`}
      onClick={props.onClick}
      role={props.onClick ? "button" : undefined}
      tabIndex={props.onClick ? 0 : -1}
      onKeyDown={(e) => {
        if (!props.onClick) return;
        if (e.key === "Enter" || e.key === " ") props.onClick();
      }}
    >
      <div className="kpiTop">
        <div className="kpiLabel">{props.label}</div>
        {showDelta ? (
          deltaLabel ? (
            <span className="pill pillSoft">{deltaLabel}</span>
          ) : (
            <GrowthPill value={props.deltaPct ?? null} />
          )
        ) : null}
      </div>

      <div className="kpiValue">{main}</div>

      {showToday ? (
        <div className="kpiHint">
          Hoje: <b>{props.todayValue}</b>
        </div>
      ) : (
        <div className="kpiHint">{props.hint || "—"}</div>
      )}

      {sparkNorm.length ? (
        <div
          className="kpiSpark"
          aria-hidden="true"
          style={{
            gridTemplateColumns: `repeat(${sparkNorm.length}, minmax(0, 1fr))`,
          }}
        >
          {sparkNorm.map((h, i) => (
            <span
              key={i}
              className={`sparkBar ${props.active ? "sparkActive" : ""} ${tone === "ads" ? "sparkAds" : "sparkOrganic"}`}
              style={{ height: `${Math.max(6, Math.round(h * 40))}px` }}
            />
          ))}
        </div>
      ) : (
        <div className="kpiSpark kpiSparkEmpty" />
      )}
    </div>
  );
}
