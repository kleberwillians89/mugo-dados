import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getBusinessContext,
  saveBusinessContext,
  type BusinessContextFields,
} from "../../app/api";
import { getActiveClientName } from "../../app/activeClient";

/**
 * Contexto estratégico da empresa ativa.
 *
 * Mesma tabela e mesmos campos do backend (`client_business_context`): nada é
 * duplicado aqui. A empresa é a do contexto autorizado — nenhum client_id vai
 * na requisição —, e a edição depende do papel validado no servidor: esconder
 * o botão é só conveniência, quem recusa é o PUT.
 */

const MAX_LENGTH = 1200;

const FIELDS: Array<{
  name: keyof BusinessContextFields;
  label: string;
  hint: string;
  rows: number;
}> = [
  { name: "segment", label: "Segmento", hint: "Em que mercado a empresa atua.", rows: 2 },
  { name: "product_description", label: "Principais produtos ou serviços", hint: "O que a empresa vende, com o que importa para a leitura dos dados.", rows: 3 },
  { name: "audience", label: "Público", hint: "Quem compra e como costuma decidir.", rows: 3 },
  { name: "positioning", label: "Posicionamento", hint: "Como a marca quer ser percebida.", rows: 3 },
  { name: "differentiators", label: "Diferenciais", hint: "O que a empresa tem que a concorrência não tem.", rows: 3 },
  { name: "commercial_context", label: "Contexto comercial", hint: "Faixa de preço, margem, sazonalidade, canais de venda.", rows: 3 },
  { name: "goals", label: "Objetivos", hint: "O que a empresa quer alcançar no período.", rows: 3 },
  { name: "strategic_notes", label: "Observações estratégicas", hint: "Qualquer coisa que ajude a interpretar os números.", rows: 3 },
];

const EMPTY: BusinessContextFields = {
  segment: null, product_description: null, audience: null, positioning: null,
  differentiators: null, commercial_context: null, goals: null, strategic_notes: null,
};

type Props = {
  /** Papel de gestão já concedido pelo App; o backend valida de novo. */
  canEdit?: boolean;
};

function asText(value: string | null | undefined) {
  return typeof value === "string" ? value : "";
}

function toForm(context: Partial<BusinessContextFields> | null | undefined) {
  return FIELDS.reduce<Record<string, string>>((form, field) => {
    form[field.name] = asText(context?.[field.name]);
    return form;
  }, {});
}

export default function BusinessContextPanel({ canEdit = false }: Props) {
  const [form, setForm] = useState<Record<string, string>>(() => toForm(EMPTY));
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const savedRef = useRef<Record<string, string>>(toForm(EMPTY));

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError("");
    try {
      const response = await getBusinessContext({ signal });
      if (signal?.aborted) return;
      const loaded = toForm(response.context);
      savedRef.current = loaded;
      setForm(loaded);
    } catch (cause) {
      if (signal?.aborted) return;
      setError(cause instanceof Error && cause.message
        ? cause.message
        : "Não foi possível carregar o contexto da empresa.");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  // Alterações só vão ao servidor no Salvar: nada de autosave por tecla.
  const dirty = useMemo(
    () => FIELDS.some((field) => form[field.name] !== savedRef.current[field.name]),
    [form]
  );

  function update(name: keyof BusinessContextFields, value: string) {
    setSaved("");
    setForm((current) => ({ ...current, [name]: value.slice(0, MAX_LENGTH) }));
  }

  async function submit() {
    if (!canEdit || !dirty) return;
    setSaving(true);
    setError("");
    setSaved("");
    try {
      const payload = FIELDS.reduce<Partial<BusinessContextFields>>((body, field) => {
        body[field.name] = form[field.name].trim() || null;
        return body;
      }, {});
      const response = await saveBusinessContext(payload);
      const persisted = toForm(response.context);
      savedRef.current = persisted;
      setForm(persisted);
      setSaved("Contexto salvo. A Inteligência já usa estas informações.");
    } catch (cause) {
      setError(cause instanceof Error && cause.message
        ? cause.message
        : "Não foi possível salvar o contexto da empresa.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="companiesCard" data-testid="business-context-panel">
      <div className="companiesListTitle">
        <div>
          <h2>Contexto estratégico</h2>
          <p className="companiesCardNote">
            Essas informações ajudam a Inteligência a interpretar os dados dentro da realidade
            da marca. Valem para {getActiveClientName() || "a empresa ativa"}.
          </p>
        </div>
        {canEdit ? (
          <div className="companiesActions">
            <button className="btn" type="button" disabled={loading || saving} onClick={() => void load()}>
              Recarregar
            </button>
            <button
              className="btn btnPrimary"
              type="button"
              disabled={loading || saving || !dirty}
              onClick={() => void submit()}
            >
              {saving ? "Salvando..." : "Salvar contexto"}
            </button>
          </div>
        ) : null}
      </div>

      {error ? <p className="companiesError" role="alert">{error}</p> : null}
      {saved ? <p className="companiesSuccess" role="status">{saved}</p> : null}
      {!error && dirty && canEdit ? (
        <p className="companiesCardNote" role="status" data-testid="business-context-dirty">
          Há alterações não salvas.
        </p>
      ) : null}
      {!canEdit ? (
        <p className="companiesCardNote">
          Você pode consultar o contexto. A edição é de administradores da empresa.
        </p>
      ) : null}

      {loading ? (
        <p className="companiesCardNote" role="status">Carregando contexto da empresa...</p>
      ) : (
        <div className="businessContextForm">
          {FIELDS.map((field) => (
            <label key={field.name}>
              {field.label}
              <span className="businessContextHint">{field.hint}</span>
              <textarea
                rows={field.rows}
                maxLength={MAX_LENGTH}
                value={form[field.name]}
                disabled={!canEdit || saving}
                onChange={(event) => update(field.name, event.target.value)}
              />
              <span className="businessContextCount">
                {form[field.name].length}/{MAX_LENGTH}
              </span>
            </label>
          ))}
        </div>
      )}
    </section>
  );
}
