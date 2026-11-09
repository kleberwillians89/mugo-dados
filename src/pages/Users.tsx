import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { getActiveClientId, getActiveClientName } from "../app/activeClient";
import {
  USERNAME_RE, createTeamMember, generatePassword, getTeamCatalog, listTeamMembers, removeTeamMember,
  resetTeamMemberPassword, setTeamMemberStatus, updateTeamMember,
  type PermissionInput, type TeamCatalog, type TeamMember, type TeamPreset,
} from "../app/team";
import Drawer from "../components/Drawer";
import Shell from "../components/Shell";
import StatusBadge from "../components/StatusBadge";
import PageHeader from "../components/data/PageHeader";
import SegmentedControl from "../components/data/SegmentedControl";
import "../styles/users.css";

function message(cause: unknown, fallback: string) {
  return cause instanceof Error && cause.message ? cause.message : fallback;
}

type Editing = { member: TeamMember | null; name: string; login: string; password: string } & PermissionInput;

/**
 * Usuários da empresa ativa (modelo "Equipe e acessos" do CRM Ruah): quem entra e o que cada pessoa pode
 * ver e alterar, tela por tela. Login por usuário e senha definidos aqui. Esconder botão é só conveniência:
 * o servidor confere cada ação (team.view / team.edit e as permissões que o próprio admin tem).
 */
export default function Users({ canManage = false, myCodes, isTeam = false, myAccessTotal = false }: { canManage?: boolean; myCodes?: string[]; isTeam?: boolean; myAccessTotal?: boolean }) {
  const clientId = getActiveClientId();
  const clientName = getActiveClientName() || "empresa";
  const [catalog, setCatalog] = useState<TeamCatalog | null>(null);
  const [members, setMembers] = useState<TeamMember[] | null>(null);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [secret, setSecret] = useState<{ login: string; password: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [filter, setFilter] = useState<"active" | "inactive" | "all">("active");

  const load = useCallback(async () => {
    try {
      const [cat, list] = await Promise.all([getTeamCatalog(), listTeamMembers()]);
      if (getActiveClientId() !== clientId) return;
      setCatalog(cat); setMembers(list.items);
    } catch (cause) { setError(message(cause, "Não foi possível carregar os usuários.")); }
  }, [clientId]);
  useEffect(() => { void load(); }, [load]);

  async function run(key: string, fn: () => Promise<unknown>, fallback: string): Promise<boolean> {
    setBusy(key); setError(null); setNotice(null);
    try { await fn(); return true; } catch (cause) { setError(message(cause, fallback)); return false; } finally { setBusy(null); }
  }

  const presetOf = (code: TeamPreset) => catalog?.presets.find((p) => p.code === code);
  const mine = useMemo(() => new Set(myCodes || []), [myCodes]);
  const canGrant = (code: string) => isTeam || myAccessTotal || mine.has(code);

  function openNew() {
    const preset = presetOf("visualizacao");
    setSecret(null);
    setEditing({ member: null, name: "", login: "", password: generatePassword(), preset: "visualizacao",
      view_all: preset?.view_all ?? true, access_total: false, codes: preset?.codes ?? [] });
  }

  function openEdit(member: TeamMember) {
    setSecret(null);
    setEditing({ member, name: member.name || "", login: member.login, password: "", preset: member.preset,
      view_all: member.view_all, access_total: member.access_total, codes: member.codes });
  }

  function choosePreset(code: TeamPreset) {
    const preset = presetOf(code);
    if (!editing || !preset) return;
    setEditing({ ...editing, preset: code, view_all: preset.view_all, access_total: preset.access_total,
      codes: code === "personalizado" ? editing.codes : preset.codes });
  }

  function toggleCode(code: string) {
    if (!editing) return;
    const codes = new Set(editing.codes);
    if (codes.has(code)) {
      codes.delete(code);
      if (code.endsWith(".view")) codes.delete(code.replace(/\.view$/, ".edit")); // sem ver, não altera
    } else {
      codes.add(code);
      if (code.endsWith(".edit")) codes.add(code.replace(/\.edit$/, ".view"));
    }
    setEditing({ ...editing, codes: [...codes] });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!editing) return;
    const input: PermissionInput = { preset: editing.preset, view_all: editing.view_all, access_total: editing.access_total, codes: editing.codes };
    if (editing.member) {
      const ok = await run("save", () => updateTeamMember(editing.member!.user_id, input), "Não foi possível salvar as permissões.");
      if (ok) { setEditing(null); setNotice("Permissões atualizadas. Valem a partir do próximo carregamento da pessoa."); await load(); }
      return;
    }
    const login = editing.login.trim().toLowerCase();
    if (!login.includes("@") && !USERNAME_RE.test(login)) {
      setError("Usuário: 3 a 32 caracteres, só letras minúsculas, números, ponto, hífen ou _."); return;
    }
    const password = editing.password;
    const ok = await run("save", () => createTeamMember({ ...input, name: editing.name.trim(), login, password }), "Não foi possível criar o usuário.");
    if (ok) { setEditing(null); setSecret({ login, password }); await load(); }
  }

  async function resetPassword(member: TeamMember) {
    if (!window.confirm(`Gerar uma senha nova para ${member.name || member.login}? A senha atual deixa de funcionar.`)) return;
    const password = generatePassword();
    const ok = await run(`p:${member.user_id}`, () => resetTeamMemberPassword(member.user_id, password), "Não foi possível redefinir a senha.");
    if (ok) setSecret({ login: member.login, password });
  }

  async function toggleStatus(member: TeamMember) {
    const next = member.status === "active" ? "inactive" : "active";
    if (next === "inactive" && !window.confirm(`Desativar ${member.name || member.login}? A pessoa deixa de entrar em ${clientName}.`)) return;
    const ok = await run(`s:${member.user_id}`, () => setTeamMemberStatus(member.user_id, next), "Não foi possível alterar o status.");
    if (ok) await load();
  }

  async function remove(member: TeamMember) {
    if (!window.confirm(`Remover o acesso de ${member.name || member.login} a ${clientName}? A conta continua existindo para outras empresas.`)) return;
    const ok = await run(`r:${member.user_id}`, () => removeTeamMember(member.user_id), "Não foi possível remover.");
    if (ok) await load();
  }

  const shown = (members || []).filter((m) => filter === "all" || m.status === filter);
  const groups = useMemo(() => (catalog?.modules || []).map((m) => ({
    ...m, items: (catalog?.permissions || []).filter((p) => p.module === m.code),
  })), [catalog]);
  const selected = new Set(editing?.access_total ? (catalog?.permissions || []).map((p) => p.code) : editing?.codes || []);

  return <Shell title="Usuários" variant="editorial"><div className="ds-page usersPage">
    <PageHeader company={clientName} title="Usuários" />
    <p className="usersIntro">Quem entra na Mugô por {clientName} e o que cada pessoa pode ver e alterar, tela por tela.</p>
    <div className="usersToolbar">
      <SegmentedControl ariaLabel="Status" value={filter} onSelect={(id) => setFilter(id as typeof filter)}
        options={[{ id: "active", label: "Ativos" }, { id: "inactive", label: "Inativos" }, { id: "all", label: "Todos" }]} />
      {canManage ? <button type="button" className="ds-button is-primary" onClick={openNew} disabled={!catalog}>+ Novo usuário</button> : null}
    </div>
    {error ? <div className="ds-notice is-negative" role="alert"><p className="ds-noticeTitle">{error}</p></div> : null}
    {notice ? <div className="ds-notice is-positive" role="status"><p className="ds-noticeTitle">{notice}</p></div> : null}
    {secret ? <div className="ds-notice is-warning usersSecret" role="status">
      <p className="ds-noticeTitle">Anote e envie para a pessoa: esta senha não aparece de novo.</p>
      <p>Usuário: <code>{secret.login}</code> · Senha: <code>{secret.password}</code></p>
      <div className="usersActions">
        <button type="button" className="ds-button" onClick={() => void navigator.clipboard?.writeText(`Usuário: ${secret.login}\nSenha: ${secret.password}`)}>Copiar</button>
        <button type="button" className="ds-link is-quiet" onClick={() => setSecret(null)}>Fechar</button>
      </div>
    </div> : null}

    {!members ? <p>Carregando…</p> : !shown.length ? <p className="usersMuted">Nenhum usuário {filter === "inactive" ? "inativo" : filter === "active" ? "ativo" : ""}.</p> :
      <div className="usersScroll"><table className="ds-table usersTable">
        <thead><tr><th>Pessoa</th><th>Perfil</th><th>Acesso</th><th>Status</th><th>Último acesso</th><th aria-label="Ações" /></tr></thead>
        <tbody>{shown.map((m) => <tr key={m.user_id}>
          <td><b>{m.name || m.login}</b>{m.name ? <small>{m.login}</small> : null}</td>
          <td>{m.is_global_role ? "Equipe Mugô" : m.preset_label}</td>
          <td><small>{m.is_global_role || m.access_total ? "Acesso total" : `${m.codes.length} permissões${m.view_all ? " · vê tudo" : ""}`}</small></td>
          <td><StatusBadge label={m.status === "active" ? "Ativo" : "Inativo"} tone={m.status === "active" ? "success" : "neutral"} /></td>
          <td><small>{m.last_sign_in_at ? new Date(m.last_sign_in_at).toLocaleString("pt-BR") : "Nunca"}</small></td>
          <td>{canManage && !m.is_global_role ? <div className="usersActions">
            <button type="button" className="ds-button" disabled={Boolean(busy)} onClick={() => openEdit(m)}>Permissões</button>
            <button type="button" className="ds-link is-quiet" disabled={Boolean(busy)} onClick={() => void resetPassword(m)}>Nova senha</button>
            <button type="button" className="ds-link is-quiet" disabled={Boolean(busy)} onClick={() => void toggleStatus(m)}>{m.status === "active" ? "Desativar" : "Reativar"}</button>
            <button type="button" className="ds-link is-quiet usersDanger" disabled={Boolean(busy)} onClick={() => void remove(m)}>Remover</button>
          </div> : null}</td>
        </tr>)}</tbody>
      </table></div>}

    <Drawer open={Boolean(editing)} width="lg" title={editing?.member ? `Permissões de ${editing.member.name || editing.member.login}` : "Novo usuário"}
      description="Escolha um perfil pronto e ajuste tela por tela. Alterar exige ver." onClose={() => { if (!busy) setEditing(null); }}>
      {editing && catalog ? <form className="usersForm" onSubmit={submit}>
        {!editing.member ? <>
          <label className="ds-field">Nome<input maxLength={120} value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} placeholder="Ana Souza" /></label>
          <label className="ds-field">Usuário (é com ele que a pessoa entra)<input required value={editing.login} autoCapitalize="none" spellCheck={false}
            onChange={(e) => setEditing({ ...editing, login: e.target.value.toLowerCase().replace(/\s+/g, ".") })} placeholder="ana.roove" /></label>
          <label className="ds-field">Senha
            <span className="usersPasswordRow">
              <input required minLength={8} value={editing.password} onChange={(e) => setEditing({ ...editing, password: e.target.value })} />
              <button type="button" className="ds-button" onClick={() => setEditing({ ...editing, password: generatePassword() })}>Gerar senha</button>
            </span>
          </label>
        </> : null}
        <label className="ds-field">Perfil
          <select value={editing.preset} onChange={(e) => choosePreset(e.target.value as TeamPreset)}>
            {catalog.presets.map((p) => <option key={p.code} value={p.code}>{p.label}</option>)}
          </select>
        </label>
        <label className="usersCheck"><input type="checkbox" checked={editing.access_total} disabled={!isTeam && !myAccessTotal}
          onChange={(e) => setEditing({ ...editing, access_total: e.target.checked, preset: e.target.checked ? "administrador" : editing.preset === "administrador" ? "personalizado" : editing.preset })} /> Acesso total (pode tudo nesta empresa, inclusive integrações e usuários)</label>
        <label className="usersCheck"><input type="checkbox" checked={editing.view_all} disabled={editing.access_total}
          onChange={(e) => {
            const views = catalog.permissions.filter((p) => p.code.endsWith(".view") && p.code !== "team.view").map((p) => p.code);
            const codes = new Set(editing.codes);
            views.forEach((c) => (e.target.checked ? codes.add(c) : undefined));
            setEditing({ ...editing, view_all: e.target.checked, codes: [...codes] });
          }} /> Ver tudo (todas as telas, menos Usuários)</label>
        <fieldset className="usersGrid" disabled={editing.access_total}>
          <legend>Permissões por tela</legend>
          {groups.map((g) => <div key={g.code} className="usersModule">
            <b>{g.label}</b>
            {g.items.map((p) => <label key={p.code} className="usersCheck">
              <input type="checkbox" checked={selected.has(p.code)} disabled={!canGrant(p.code) && !selected.has(p.code)}
                onChange={() => { toggleCode(p.code); if (editing.preset !== "personalizado") setEditing((cur) => cur && { ...cur, preset: "personalizado" }); }} /> {p.label}
            </label>)}
          </div>)}
        </fieldset>
        <div className="usersFormActions"><button type="button" className="ds-button" onClick={() => setEditing(null)}>Cancelar</button>
          <button className="ds-button is-primary" disabled={Boolean(busy)}>{busy === "save" ? "Salvando…" : editing.member ? "Salvar permissões" : "Criar usuário"}</button></div>
      </form> : null}
    </Drawer>
  </div></Shell>;
}
