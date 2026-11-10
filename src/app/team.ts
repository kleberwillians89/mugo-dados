import { http } from "./api";

/** Usuários da empresa ativa com permissões por módulo (modelo do CRM Ruah). A empresa vai no X-Client-Id. */

export type TeamPreset = "administrador" | "gestor" | "marketing" | "comercial" | "visualizacao" | "personalizado";
export type TeamCatalog = {
  modules: { code: string; label: string }[];
  permissions: { code: string; module: string; label: string; opt_in?: boolean }[];
  presets: { code: TeamPreset; label: string; view_all: boolean; access_total: boolean; codes: string[] }[];
};
export type TeamMember = {
  user_id: string; name: string | null; login: string; role: string; is_global_role: boolean;
  preset: TeamPreset; preset_label: string; view_all: boolean; access_total: boolean;
  status: "active" | "inactive"; permission_overrides: number; codes: string[];
  last_sign_in_at: string | null; created_at: string | null;
};
export type MyAccess = { client_id: string; team: boolean; access_total: boolean; preset?: TeamPreset | null; codes: string[] };
export type PermissionInput = { preset: TeamPreset; view_all: boolean; access_total: boolean; codes: string[] };

const json = (method: string, body?: unknown) => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });

export const getTeamCatalog = () => http<TeamCatalog>("/api/team/catalog");
export const getMyAccess = () => http<MyAccess>("/api/team/me");
export const listTeamMembers = () => http<{ items: TeamMember[] }>("/api/team/members");
export const createTeamMember = (input: PermissionInput & { name: string; login: string; password: string }) =>
  http<{ user_id: string; login: string; account_created: boolean }>("/api/team/members", json("POST", input));
export const updateTeamMember = (userId: string, input: PermissionInput) =>
  http<{ codes: string[] }>(`/api/team/members/${encodeURIComponent(userId)}`, json("PUT", input));
export const setTeamMemberStatus = (userId: string, status: "active" | "inactive") =>
  http(`/api/team/members/${encodeURIComponent(userId)}/status`, json("POST", { status }));
export const resetTeamMemberPassword = (userId: string, password: string) =>
  http(`/api/team/members/${encodeURIComponent(userId)}/password`, json("POST", { password }));
export const removeTeamMember = (userId: string) => http(`/api/team/members/${encodeURIComponent(userId)}`, { method: "DELETE" });

/** Senha legível, sem caracteres ambíguos (0/O, 1/l/I), 14 caracteres. */
export function generatePassword(): string {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789";
  const bytes = new Uint32Array(14);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (n) => alphabet[n % alphabet.length]).join("");
}

export { INTERNAL_LOGIN_DOMAIN, USERNAME_RE, normalizeLoginIdentifier, ROUTE_MODULE, OPT_IN_CODES } from "./teamRules";
