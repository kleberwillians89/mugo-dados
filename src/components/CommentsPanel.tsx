import { memo } from "react";
import type { CommentItem, TopWord } from "../app/types";
import WordCloud from "./WordCloud";
import DataNotice from "./data/DataNotice";

type Props = {
  comments: CommentItem[];
  topWords: TopWord[];
  loading: boolean;
  refreshing?: boolean;
  updatedAtLabel?: string | null;
  hasMore?: boolean;
  total?: number;
  hasOrganicData?: boolean;
  error?: string | null;
  message?: string | null;
  onLoadMore?: () => void;
};

function arrayOrEmpty<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function CommentsPanel({
  comments,
  topWords,
  loading,
  refreshing = false,
  updatedAtLabel = null,
  hasMore = false,
  total,
  hasOrganicData = false,
  error = null,
  message = null,
  onLoadMore,
}: Props) {
  const safeComments = arrayOrEmpty<CommentItem>(comments);
  const safeTopWords = arrayOrEmpty<TopWord>(topWords);
  const showSkeleton = loading && safeComments.length === 0;
  const hasTopWords = safeTopWords.length > 0;
  const showUnavailable = Boolean(error) && !safeComments.length && !hasTopWords && !loading;
  const showEmpty = !loading && !showUnavailable && !safeComments.length && !hasTopWords;
  const commentCount =
    typeof total === "number" && Number.isFinite(total)
      ? Math.max(total, safeComments.length)
      : safeComments.length;
  const countLabel = loading
    ? "Carregando..."
    : refreshing
      ? "Atualizando..."
      : `${commentCount.toLocaleString("pt-BR")} ${commentCount === 1 ? "comentário" : "comentários"} no período`;

  return (
    <section className="ds-section commentsSection" aria-labelledby="comments-title">
      <div className="ds-sectionHead">
        <div className="ds-sectionHeadText">
          <h3 id="comments-title" className="ds-sectionTitle">Comentários</h3>
          {!showUnavailable ? (
            <p className="ds-caption">{countLabel}{updatedAtLabel ? ` · ${updatedAtLabel.replace(/^Última atualização /, "atualizado em ")}` : ""}</p>
          ) : null}
        </div>
      </div>

      {showUnavailable ? (
        <DataNotice tone="negative" title="Comentários indisponíveis">
          {message || (hasOrganicData ? "Não foi possível carregar os comentários agora." : "Comentários ainda não sincronizados.")}
        </DataNotice>
      ) : showEmpty ? (
        <p className="ds-emptyLine">
          {message || (hasOrganicData ? "Nenhum comentário neste período." : "Comentários ainda não sincronizados.")}
        </p>
      ) : (
        <>
          {error ? <DataNotice tone="warning" title="Atualização parcial dos comentários">Exibindo a última leitura disponível.</DataNotice> : null}

          <div className="commentsGrid">
            <div className="commentsWords">
              <p className="ds-subTitle">Palavras mais citadas</p>
              {hasTopWords ? (
                <WordCloud words={safeTopWords} />
              ) : loading ? (
                <p className="ds-status">Carregando palavras mais citadas...</p>
              ) : (
                <p className="ds-emptyLine">Sem palavras suficientes no período.</p>
              )}
            </div>

            <div className="commentsList">
              {showSkeleton ? (
                <p className="ds-status" role="status">Carregando comentários...</p>
              ) : safeComments.length ? (
                safeComments.slice(0, 120).map((c, index) => (
                  <div className="commentItem" key={c.comment_id || `${c.media_id || "media"}-${index}`}>
                    <div className="commentHead">
                      <b>@{c.username || "usuario"}</b>
                      <span>{c.timestamp ? new Date(c.timestamp).toLocaleDateString("pt-BR", { timeZone: "America/Sao_Paulo" }) : ""}</span>
                    </div>
                    <div>{c.text || "(sem texto)"}</div>
                  </div>
                ))
              ) : (
                <p className="ds-emptyLine">Nenhum comentário neste período.</p>
              )}
              {hasMore && onLoadMore ? (
                <button type="button" className="ds-button" onClick={onLoadMore} disabled={loading}>
                  {loading ? "Carregando..." : "Ver mais comentários"}
                </button>
              ) : null}
            </div>
          </div>
        </>
      )}
    </section>
  );
}

export default memo(CommentsPanel);
