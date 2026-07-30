import type { ReactNode } from "react";

type Props = {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: ReactNode;
};

export default function ShopifySectionHeader({
  eyebrow,
  title,
  description,
  action,
}: Props) {
  return (
    <div className="shopifySectionHeader">
      <div>
        {eyebrow ? <div className="shopifySectionEyebrow">{eyebrow}</div> : null}
        <h2 className="shopifySectionTitle">{title}</h2>
        {description ? <p className="shopifySectionDescription">{description}</p> : null}
      </div>
      {action ? <div className="shopifySectionAction">{action}</div> : null}
    </div>
  );
}
