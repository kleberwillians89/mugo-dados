import { useEffect, useMemo, useState } from "react";
import type { NoteItem } from "../app/types";
import MetaStateNotice from "./dashboard/MetaStateNotice";

type Props = {
  notes: NoteItem[];
  loading: boolean;
  available?: boolean;
  message?: string | null;
  error?: string | null;
  onCreate: () => Promise<NoteItem | null>;
  onUpdate: (noteId: string, patch: { title?: string; body?: string }) => Promise<void>;
};

type NoteDraft = {
  title: string;
  body: string;
};

function arrayOrEmpty<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === "string" && error.trim()) return error;
  return fallback;
}

export default function NotesPanel({
  notes,
  loading,
  available = true,
  message = null,
  error = null,
  onCreate,
  onUpdate,
}: Props) {
  const [selectedId, setSelectedId] = useState<string>("");
  const [drafts, setDrafts] = useState<Record<string, NoteDraft>>({});
  const [actionError, setActionError] = useState<string | null>(null);
  const safeNotes = useMemo(() => arrayOrEmpty<NoteItem>(notes), [notes]);
  const notesAvailable = available !== false;

  const resolvedSelectedId = useMemo(() => {
    if (!safeNotes.length) return "";
    if (selectedId && safeNotes.some((n) => n.id === selectedId)) return selectedId;
    return safeNotes[0].id;
  }, [safeNotes, selectedId]);

  const selected = useMemo(
    () => safeNotes.find((n) => n.id === resolvedSelectedId) || null,
    [safeNotes, resolvedSelectedId]
  );

  const draft = useMemo<NoteDraft>(() => {
    if (!selected) return { title: "", body: "" };
    const existing = drafts[selected.id];
    if (existing) return existing;
    return {
      title: selected.title || "",
      body: selected.body || "",
    };
  }, [selected, drafts]);

  useEffect(() => {
    if (!selected) return;

    const changed = draft.title !== (selected.title || "") || draft.body !== (selected.body || "");
    if (!changed) return;

    const t = window.setTimeout(() => {
      onUpdate(selected.id, { title: draft.title, body: draft.body }).catch(() => {});
    }, 800);

    return () => window.clearTimeout(t);
  }, [selected, draft.title, draft.body, onUpdate]);

  async function handleCreate() {
    setActionError(null);
    try {
      await onCreate();
    } catch (createError: unknown) {
      setActionError(errorMessage(createError, "Não foi possível criar a nota agora."));
    }
  }

  return (
    <div className="card cardWide notesPanel">
      <div className="sectionHeader">
        <div>
          <div className="h1">Notas do Cliente</div>
          <div className="p">Bloco secundário. Pode ficar indisponível sem comprometer o restante da página.</div>
        </div>
        <button
          className="btn btnGhost"
          type="button"
          onClick={() => {
            void handleCreate();
          }}
          disabled={loading || !notesAvailable}
        >
          Nova nota
        </button>
      </div>

      {error || actionError ? (
        <div className="metaInlineNotice">{actionError || error}</div>
      ) : null}

      {loading && !safeNotes.length ? (
        <MetaStateNotice
          title="Carregando notas"
          description="As notas são carregadas depois do núcleo principal do dashboard."
          tone="loading"
          message="Preparando notas do cliente..."
        />
      ) : !notesAvailable ? (
        <MetaStateNotice
          title="Notas indisponíveis"
          description="Esse ambiente ainda não expõe a tabela de notas do cliente ativo."
          tone="unavailable"
          message={message || "As notas não estão disponíveis agora."}
          secondaryMessage="O restante da página continua utilizável."
        />
      ) : null}

      {!!safeNotes.length && notesAvailable && (
        <select
          className="select"
          value={resolvedSelectedId}
          onChange={(e) => setSelectedId(e.target.value)}
          style={{ marginBottom: 10 }}
        >
          {safeNotes.map((n) => (
            <option key={n.id} value={n.id}>
              {n.title || "Sem título"}
            </option>
          ))}
        </select>
      )}

      {!selected && !loading && notesAvailable ? (
        <MetaStateNotice
          title="Sem notas ainda"
          description="Esse espaço serve para contexto comercial, observações e decisões combinadas com o cliente."
          tone="empty"
          message={message || "Nenhuma nota foi criada para essa conta ainda."}
          secondaryMessage="Use “Nova nota” quando quiser registrar contexto."
        />
      ) : selected ? (
        <div className="notesEditor">
          <input
            className="input"
            value={draft.title}
            onChange={(e) =>
              setDrafts((prev) => ({
                ...prev,
                [selected.id]: {
                  title: e.target.value,
                  body: draft.body,
                },
              }))
            }
            placeholder="Título"
          />
          <textarea
            className="textarea"
            value={draft.body}
            onChange={(e) =>
              setDrafts((prev) => ({
                ...prev,
                [selected.id]: {
                  title: draft.title,
                  body: e.target.value,
                },
              }))
            }
            placeholder="Escreva aqui..."
            rows={8}
          />
        </div>
      ) : null}
    </div>
  );
}
