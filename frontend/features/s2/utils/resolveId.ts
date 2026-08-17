export type S2Entity =
  | "line"
  | "requirement"
  | "field"
  | "document"
  | "finding"
  | "request"
  | "ask"
  | "procedure"
  | "change";

export interface ResolvedId {
  entity: S2Entity;
  id: string;
  label: string;
}

export function resolveId(entity: S2Entity, id: string): ResolvedId {
  return {
    entity,
    id,
    label: id,
  };
}

