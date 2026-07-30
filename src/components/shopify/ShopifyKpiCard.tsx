type Props = {
  label: string;
  value: string;
  hint?: string;
  tone?: "default" | "accent";
};

export default function ShopifyKpiCard({
  label,
  value,
  hint,
  tone = "default",
}: Props) {
  return (
    <article className={`shopifyKpiCard ${tone === "accent" ? "isAccent" : ""}`.trim()}>
      <div className="shopifyKpiLabel">{label}</div>
      <div className="shopifyKpiValue">{value}</div>
      {hint ? <div className="shopifyKpiHint">{hint}</div> : <div className="shopifyKpiHint isPlaceholder">.</div>}
    </article>
  );
}
