import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { creatorCompact, resolveCreator, searchPeople, type CreatorNetwork, type CreatorPick } from "../../app/creators";

function PickAvatar({ pick }: { pick: CreatorPick }) {
  const [broken, setBroken] = useState(false);
  return pick.avatar_url && !broken
    ? <img className="creatorAvatar" src={pick.avatar_url} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setBroken(true)} />
    : <span className="creatorAvatar is-fallback" aria-hidden="true">{pick.handle.slice(0, 1).toUpperCase()}</span>;
}

type Option = { key: string; pick?: CreatorPick; label?: string; action?: "people"; group: string };

/**
 * "Analisar perfil" com sugestões: enquanto digita, mostra quem já está salvo (com foto) e a prévia do @ exato pela
 * Meta; para nome (sem @ exato), a equipe Mugô pode procurar no Instagram pelo nome e escolher o perfil certo.
 * Escolher uma opção analisa aquele @.
 */
export default function CreatorFinder({ network, isAgency, busy, onPick }: {
  network: CreatorNetwork; isAgency: boolean; busy: boolean; onPick: (handle: string) => void;
}) {
  const [text, setText] = useState("");
  const [saved, setSaved] = useState<CreatorPick[]>([]);
  const [exact, setExact] = useState<CreatorPick | null>(null);
  const [similar, setSimilar] = useState<CreatorPick[]>([]);
  const [people, setPeople] = useState<{ query: string; list: CreatorPick[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const listId = useId();
  const seq = useRef(0);

  useEffect(() => {
    const q = text.trim();
    const mine = ++seq.current;
    if (q.replace(/^@/, "").length < 2) return;
    const timer = window.setTimeout(() => {
      setLoading(true);
      resolveCreator(network, q)
        .then((res) => { if (seq.current === mine) { setSaved(res.saved || []); setExact(res.exact); setSimilar(res.similar || []); setActive(0); } })
        .catch(() => { if (seq.current === mine) { setSaved([]); setExact(null); setSimilar([]); } })
        .finally(() => { if (seq.current === mine) setLoading(false); });
    }, 350);
    return () => window.clearTimeout(timer);
  }, [text, network]);

  const q = text.trim();
  const short = q.replace(/^@/, "").length < 2;
  const peopleHere = people && people.query === q ? people.list : [];
  const options: Option[] = short ? [] : [
    ...saved.map((pick) => ({ key: `s:${pick.handle}`, pick, group: "Já salvos" })),
    ...(exact && !exact.missing && !saved.some((s) => s.handle === exact.handle) ? [{ key: `e:${exact.handle}`, pick: exact, group: "Perfil com este @" }] : []),
    ...similar.filter((pick) => pick.handle !== exact?.handle && !saved.some((s) => s.handle === pick.handle))
      .map((pick) => ({ key: `m:${pick.handle}`, pick, group: "@ parecidos" })),
    ...peopleHere.map((pick) => ({ key: `p:${pick.handle}`, pick, group: `Resultado para “${q}” no Instagram` })),
    ...(isAgency && network === "instagram" && !peopleHere.length ? [{ key: "people", action: "people" as const, label: `Procurar “${q}” pelo nome no Instagram`, group: "Não achou?" }] : []),
  ];

  async function findPeople() {
    setSearching(true); setError(null);
    try {
      const res = await searchPeople(q);
      setPeople({ query: q, list: res.people || [] });
      setOpen(true); setActive(0);
      if (!res.people?.length) setError(`Nenhum perfil encontrado para “${q}”.`);
    } catch (cause) {
      setError(cause instanceof Error && cause.message ? cause.message : "Não foi possível procurar agora.");
    } finally { setSearching(false); }
  }

  function choose(option: Option | undefined) {
    if (!option || searching) return;
    if (option.action === "people") { void findPeople(); return; }
    if (!option.pick) return;
    setOpen(false); setText(""); setSaved([]); setExact(null); setPeople(null);
    onPick(option.pick.handle);
  }

  function onKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") { setOpen(false); return; }
    if (!options.length) return;
    if (event.key === "ArrowDown") { event.preventDefault(); setOpen(true); setActive((i) => Math.min(options.length - 1, i + 1)); }
    else if (event.key === "ArrowUp") { event.preventDefault(); setActive((i) => Math.max(0, i - 1)); }
    else if (event.key === "Enter" && open && options[active] && (options[active].pick || options[active].action)) { event.preventDefault(); choose(options[active]); }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!q) return;
    setOpen(false); setText("");
    onPick(q);
  }

  let lastGroup = "";
  const showPop = open && !short && (options.length > 0 || loading || Boolean(exact?.missing));
  return <form onSubmit={submit} className="creatorRow creatorFinder">
    <div className="ds-field creatorFinderField">
      <label htmlFor={`${listId}-input`}>Analisar perfil</label>
      <input id={`${listId}-input`} role="combobox" aria-expanded={showPop} aria-controls={listId} aria-autocomplete="list"
        aria-activedescendant={showPop && options[active] ? `${listId}-${active}` : undefined}
        value={text} autoComplete="off" placeholder="Nome do criador ou @"
        onChange={(e) => { setText(e.target.value); setOpen(true); setError(null); }}
        onFocus={() => setOpen(true)} onBlur={() => window.setTimeout(() => setOpen(false), 150)} onKeyDown={onKey} />
      {showPop ? <div className="creatorFinderPop">
        {loading && !options.length ? <p className="creatorFinderNote" role="status">Procurando…</p> : null}
        {exact?.missing ? <p className="creatorFinderNote">@{exact.handle}: {exact.reason}</p> : null}
        <ul id={listId} role="listbox" aria-label="Criadores encontrados">
          {options.map((option, index) => {
            const header = option.group !== lastGroup ? option.group : null;
            lastGroup = option.group;
            return <li key={option.key} role="presentation">
              {header ? <span className="creatorFinderGroup" aria-hidden="true">{header}</span> : null}
              <div id={`${listId}-${index}`} role="option" aria-selected={index === active}
                className={`creatorFinderOpt${index === active ? " is-active" : ""}${option.action ? " is-action" : ""}`}
                onMouseDown={(e) => { e.preventDefault(); choose(option); }} onMouseEnter={() => setActive(index)}>
                {option.pick ? <>
                  <PickAvatar pick={option.pick} />
                  <span className="creatorFinderWho"><b>@{option.pick.handle}{option.pick.verified ? <span className="creatorFinderCheck" aria-label="verificado"> ✓</span> : null}</b>
                    <small>{[option.pick.display_name, option.pick.followers != null ? `${creatorCompact(option.pick.followers)} seguidores` : null, option.pick.private ? "perfil privado" : null].filter(Boolean).join(" · ")}</small></span>
                </> : <span className="creatorFinderWho"><b>{searching ? "Procurando no Instagram…" : option.label}</b><small>Usa 1 crédito da Apify (teto mensal)</small></span>}
              </div>
            </li>;
          })}
        </ul>
      </div> : null}
    </div>
    <button className="ds-button is-primary" disabled={busy || !q}>Analisar</button>
    {error ? <p className="creatorFinderError" role="alert">{error}</p> : null}
  </form>;
}
