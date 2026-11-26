import { mugoIAActions, type MugoIAAction as Action, type MugoIAMeta } from "../../app/studio";
import MugoIAAction from "./MugoIAAction";

/** As peças de uma resposta (o pacote da campanha), cada uma com o seu Criar. */
export default function MugoIAActions({ messageId, meta, canCreate, onMeta }: {
  messageId: string | null; meta?: MugoIAMeta; canCreate: boolean; onMeta: (meta: MugoIAMeta) => void;
}) {
  const actions = mugoIAActions(meta);
  if (!actions.length) return null;
  const update = (index: number, action: Action) => {
    const next = actions.map((a, i) => (i === index ? action : a));
    onMeta(meta?.acoes?.length ? { ...meta, acoes: next } : { ...meta, acao: action });
  };
  return <div className="miaCreateList">
    {actions.length > 1 ? <small className="miaCreateCount">{actions.length} peças para criar</small> : null}
    {actions.map((action, index) => <MugoIAAction key={`${index}:${action.titulo}`} messageId={messageId} item={index} action={action}
      canCreate={canCreate} onChange={(a) => update(index, a)} />)}
  </div>;
}
