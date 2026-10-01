export type MembershipRole = "platform_admin" | "agency_admin" | "client_admin" | "owner" | "viewer";

export const ROLE_LABELS: Record<string, string> = {
  platform_admin: "Administrador da plataforma",
  agency_admin: "Administrador da agência",
  client_admin: "Administrador do cliente",
  owner: "Responsável",
  viewer: "Somente leitura",
};

// Rótulos vistos pela própria pessoa (menu da conta, convite). A
// administração usa ROLE_LABELS; aqui o cliente lê "da empresa", não "do
// cliente". owner/admin legados equivalem a client_admin no backend.
export const ACCOUNT_ROLE_LABELS: Record<string, string> = {
  platform_admin: "Administrador da plataforma",
  agency_admin: "Administrador da agência",
  client_admin: "Administrador da empresa",
  owner: "Responsável",
  admin: "Administrador da empresa",
  viewer: "Somente leitura",
};

export const ROLE_DESCRIPTIONS: Record<string, string> = {
  platform_admin: "Acesso total à plataforma Mugô, incluindo administração de todas as empresas.",
  agency_admin: "Mugô — gerencia todas as empresas.",
  client_admin: "Gerencia somente sua empresa.",
  owner: "Responsável principal pela empresa.",
  viewer: "Visualização somente leitura.",
};
