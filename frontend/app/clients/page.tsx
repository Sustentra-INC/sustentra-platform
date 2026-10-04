"use client";

import { FormEvent, useEffect, useState } from "react";

import {
  createClient,
  createClientUser,
  deleteClient,
  deleteClientUser,
  listClients,
  listClientUsers,
  updateClient,
  type ClientRecord,
  type ClientUserRecord
} from "../../lib/api/clients";
import { ApiError } from "../../lib/api/client";
import { useActor } from "../../lib/useActor";

export default function ClientsPage() {
  const [clients, setClients] = useState<ClientRecord[]>([]);
  const [selected, setSelected] = useState<ClientRecord | null>(null);
  const [users, setUsers] = useState<ClientUserRecord[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [notes, setNotes] = useState("");
  const [userName, setUserName] = useState("");
  const [userEmail, setUserEmail] = useState("");
  const [userPassword, setUserPassword] = useState("");
  const actorType = useActor()?.actor_type ?? null;
  const canManage = actorType === "sustentra_user";

  async function refreshClients() {
    const rows = await listClients();
    setClients(rows);
    if (selected) {
      const latest = rows.find((row) => row.client_id === selected.client_id) ?? null;
      setSelected(latest);
    }
  }

  async function refreshUsers(clientId: string) {
    setUsers(await listClientUsers(clientId));
  }

  useEffect(() => {
    listClients()
      .then(setClients)
      .catch((exc) => {
        setError(exc instanceof ApiError ? exc.detail : "Log in to manage clients.");
      });
  }, []);

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      const created = await createClient({
        name,
        code,
        contact_email: contactEmail || undefined,
        notes: notes || undefined
      });
      setName("");
      setCode("");
      setContactEmail("");
      setNotes("");
      await refreshClients();
      setSelected(created);
      await refreshUsers(created.client_id);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.detail : "Could not create client.");
    }
  }

  async function handleUpdate(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    setError(null);
    try {
      const updated = await updateClient(selected.client_id, {
        name: selected.name,
        code: selected.code,
        contact_email: selected.contact_email ?? undefined,
        notes: selected.notes ?? undefined,
        status: selected.status === "inactive" ? "inactive" : "active"
      });
      setSelected(updated);
      await refreshClients();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.detail : "Could not update client.");
    }
  }

  async function handleDelete() {
    if (!selected) return;
    setError(null);
    try {
      await deleteClient(selected.client_id);
      setSelected(null);
      setUsers([]);
      await refreshClients();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.detail : "Could not delete client.");
    }
  }

  async function handleSelect(record: ClientRecord) {
    setSelected(record);
    setError(null);
    try {
      await refreshUsers(record.client_id);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.detail : "Could not load client-users.");
    }
  }

  async function handleCreateUser(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    setError(null);
    try {
      await createClientUser(selected.client_id, {
        username: userName,
        email: userEmail,
        password: userPassword
      });
      setUserName("");
      setUserEmail("");
      setUserPassword("");
      await refreshUsers(selected.client_id);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.detail : "Could not create client-user.");
    }
  }

  return (
    <section>
      <h2>Sustentra Clients</h2>
      <p>
        Clients are companies that use the app. They are not Sustentra users. A Sustentra user creates the company, then creates the client-users who will log in.
      </p>
      {error ? <p style={{ color: "#a40000" }}>{error}</p> : null}

      {canManage ? (
        <form onSubmit={handleCreate} style={{ display: "grid", gap: 8, maxWidth: 480, marginBottom: 24 }}>
          <strong>Create client</strong>
          <input placeholder="Company name" value={name} onChange={(e) => setName(e.target.value)} required />
          <input placeholder="Code (e.g. brewery)" value={code} onChange={(e) => setCode(e.target.value)} required />
          <input placeholder="Contact email" type="email" value={contactEmail} onChange={(e) => setContactEmail(e.target.value)} />
          <input placeholder="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
          <button type="submit">Create client</button>
        </form>
      ) : null}

      <table style={{ borderCollapse: "collapse", width: "100%", marginBottom: 24 }}>
        <thead>
          <tr>
            <th align="left">Name</th>
            <th align="left">Code</th>
            <th align="left">Status</th>
          </tr>
        </thead>
        <tbody>
          {clients.map((record) => (
            <tr key={record.client_id}>
              <td>
                <button type="button" onClick={() => handleSelect(record)} style={{ border: 0, background: "none", color: "#0645ad", cursor: "pointer", padding: 0 }}>
                  {record.name}
                </button>
              </td>
              <td>{record.code}</td>
              <td>{record.status}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {selected ? (
        <div style={{ display: "grid", gap: 16 }}>
          <form onSubmit={handleUpdate} style={{ display: "grid", gap: 8, maxWidth: 480 }}>
            <strong>Edit {selected.name}</strong>
            <input value={selected.name} onChange={(e) => setSelected({ ...selected, name: e.target.value })} />
            <input value={selected.code} onChange={(e) => setSelected({ ...selected, code: e.target.value })} />
            <input
              value={selected.contact_email ?? ""}
              onChange={(e) => setSelected({ ...selected, contact_email: e.target.value })}
            />
            <input value={selected.notes ?? ""} onChange={(e) => setSelected({ ...selected, notes: e.target.value })} />
            <select
              value={selected.status}
              onChange={(e) => setSelected({ ...selected, status: e.target.value })}
            >
              <option value="active">active</option>
              <option value="inactive">inactive</option>
            </select>
            {canManage ? (
              <div style={{ display: "flex", gap: 8 }}>
                <button type="submit">Save changes</button>
                <button type="button" onClick={handleDelete}>Delete client</button>
              </div>
            ) : null}
          </form>

          <div>
            <strong>Client-users</strong>
            <p>People at this company. Created by Sustentra users. They log in with the same login screen.</p>
            <ul>
              {users.map((user) => (
                <li key={user.client_user_id}>
                  {user.username} ({user.email})
                  {canManage ? (
                    <>
                      {" "}
                      <button
                        type="button"
                        onClick={() =>
                          deleteClientUser(selected.client_id, user.client_user_id).then(() =>
                            refreshUsers(selected.client_id)
                          )
                        }
                      >
                        Delete
                      </button>
                    </>
                  ) : null}
                </li>
              ))}
            </ul>
            {canManage ? (
              <form onSubmit={handleCreateUser} style={{ display: "grid", gap: 8, maxWidth: 420 }}>
                <input placeholder="username" value={userName} onChange={(e) => setUserName(e.target.value)} required />
                <input placeholder="email" type="email" value={userEmail} onChange={(e) => setUserEmail(e.target.value)} required />
                <input placeholder="password" type="password" value={userPassword} onChange={(e) => setUserPassword(e.target.value)} required minLength={8} />
                <button type="submit">Create client-user</button>
              </form>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
