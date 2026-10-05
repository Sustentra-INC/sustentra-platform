"use client";

import { FormEvent, useEffect, useState } from "react";

import { createSustentraUser, listSustentraUsers } from "../../../lib/api/auth";
import { ApiError } from "../../../lib/api/client";
import { type Actor } from "../../../lib/session";
import { useActor } from "../../../lib/useActor";

export default function UsersPage() {
  const [users, setUsers] = useState<Actor[]>([]);
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("operator");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const actor = useActor();

  async function refresh() {
    const rows = await listSustentraUsers();
    setUsers(rows);
  }

  useEffect(() => {
    listSustentraUsers()
      .then(setUsers)
      .catch((exc) => {
        setError(exc instanceof ApiError ? exc.detail : "Log in as a Sustentra user to manage users.");
      });
  }, []);

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    try {
      await createSustentraUser({ username, email, password, role });
      setUsername("");
      setEmail("");
      setPassword("");
      setNotice("Sustentra user created.");
      await refresh();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.detail : "Could not create user.");
    }
  }

  return (
    <section>
      <h2>Sustentra Users</h2>
      <p>
        These are internal Sustentra operators. They are not clients. Sustentra users create client companies and the people who log in for those companies.
      </p>
      {actor?.actor_type !== "sustentra_user" ? (
        <p>Only Sustentra users can create other Sustentra users.</p>
      ) : (
        <form onSubmit={handleCreate} style={{ display: "grid", gap: 8, maxWidth: 420, marginBottom: 24 }}>
          <input placeholder="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
          <input placeholder="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          <input placeholder="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} />
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="operator">operator</option>
            <option value="admin">admin</option>
          </select>
          <button type="submit">Create Sustentra user</button>
        </form>
      )}
      {notice ? <p>{notice}</p> : null}
      {error ? <p style={{ color: "#a40000" }}>{error}</p> : null}
      <table style={{ borderCollapse: "collapse", width: "100%" }}>
        <thead>
          <tr>
            <th align="left">Username</th>
            <th align="left">Email</th>
            <th align="left">Role</th>
          </tr>
        </thead>
        <tbody>
          {users.map((user) => (
            <tr key={user.actor_id || user.username}>
              <td>{user.username}</td>
              <td>{user.email}</td>
              <td>{user.role ?? "operator"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
