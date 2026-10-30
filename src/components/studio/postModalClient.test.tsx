import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { CalendarItem } from "../../app/studio";
import PostModal from "./PostModal";

const item = {
  id: "p1", client_id: "roove", month: "2026-11-01", scheduled_at: "2026-11-05T22:00:00+00:00", format: "reels", pillar: "Produto",
  title: "Reels do lançamento", hook: "Olha isso", caption_draft: "Legenda", rationale: null, signals: {}, status: "em_revisao",
  review_note: null, origin: "ia", reviewed_by: null, reviewed_at: null, client_edited_at: "2026-11-01T12:00:00Z", client_edited_fields: ["caption_draft"],
} as CalendarItem;
const draft = { date: "2026-11-05", time: "19:00", format: "reels" as const, pillar: "Produto", title: item.title, hook: "Olha isso", caption_draft: "Legenda", rationale: "" };
const noop = async () => undefined;
const render = (clientMode: boolean) => renderToStaticMarkup(<PostModal item={item} initial={draft} handle="@roove" pillars={[]} canManage busy={false} error={null}
  onClose={() => undefined} onSave={async () => true} onStatus={noop} onDelete={noop} clientMode={clientMode} />);

describe("PostModal do cliente", () => {
  it("cliente aprova ou pede ajuste; não exclui, não publica, não reabre e não usa a IA", () => {
    const html = render(true);
    expect(html).toContain("Aprovar");
    expect(html).toContain("Pedir ajuste");
    expect(html).not.toContain("Excluir");
    expect(html).not.toContain("Reabrir");
    expect(html).not.toContain("Enviar p/ revisão");
    expect(html).toContain("A equipe Mugô já foi avisada");
  });

  it("a equipe vê a marca de edição do cliente e as ações completas", () => {
    const html = render(false);
    expect(html).toContain("Excluir");
    expect(html).toContain("Editado pelo cliente");
    expect(html).toContain("(legenda)");
  });
});
