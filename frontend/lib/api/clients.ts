import { apiRequest } from "./client";

export interface ClientRecord {
  client_id: string;
  name: string;
  code: string;
  contact_email?: string | null;
  notes?: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ClientUserRecord {
  client_user_id: string;
  client_id: string;
  username: string;
  email: string;
  status: string;
  mfa_enabled: boolean;
}

export function listClients() {
  return apiRequest<ClientRecord[]>("/v1/clients");
}

export function createClient(payload: {
  name: string;
  code: string;
  contact_email?: string;
  notes?: string;
}) {
  return apiRequest<ClientRecord>("/v1/clients", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function updateClient(
  clientId: string,
  payload: Partial<Pick<ClientRecord, "name" | "code" | "contact_email" | "notes" | "status">>
) {
  return apiRequest<ClientRecord>(`/v1/clients/${clientId}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export function deleteClient(clientId: string) {
  return apiRequest<{ client_id: string; status: string }>(`/v1/clients/${clientId}`, {
    method: "DELETE"
  });
}

export function listClientUsers(clientId: string) {
  return apiRequest<ClientUserRecord[]>(`/v1/clients/${clientId}/users`);
}

export function createClientUser(
  clientId: string,
  payload: { username: string; email: string; password: string }
) {
  return apiRequest<ClientUserRecord>(`/v1/clients/${clientId}/users`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function deleteClientUser(clientId: string, clientUserId: string) {
  return apiRequest<{ client_user_id: string; status: string }>(
    `/v1/clients/${clientId}/users/${clientUserId}`,
    { method: "DELETE" }
  );
}
