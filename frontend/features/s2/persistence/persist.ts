export type PersistEntity =
  | "examination"
  | "note"
  | "finding"
  | "assignment"
  | "request";

export interface PersistedRecord<Entity extends PersistEntity = PersistEntity, Payload = unknown> {
  id: string;
  entity: Entity;
  payload: Payload;
  actor: string;
  recordedAt: string;
  durable: false;
}

const sessionRecords: PersistedRecord[] = [];

export function persist<Entity extends PersistEntity, Payload>(
  entity: Entity,
  payload: Payload
): PersistedRecord<Entity, Payload> {
  const record: PersistedRecord<Entity, Payload> = {
    id: `s2-session-${sessionRecords.length + 1}`,
    entity,
    payload,
    actor: "C. Yang",
    recordedAt: new Date().toISOString(),
    durable: false,
  };
  sessionRecords.push(record);
  return record;
}

export function listPersistedRecords(): PersistedRecord[] {
  return [...sessionRecords];
}

export function clearPersistedRecords(): void {
  sessionRecords.splice(0, sessionRecords.length);
}

