import { api, apiPath } from "../../../lib/api";

/** One saved copy of an engagement's Excel workpaper (GET /engagements/{id}/workpaper-copies). */
export interface WorkpaperCopy {
  id: string;
  created_at: string | null;
  prepared_by: string | null;
  file_name: string;
  size_bytes: number;
  /** SHA-256 of the file. */
  sha256: string;
  app_version: string;
  downloads: number;
}

export interface WorkpaperCopyPage {
  items: WorkpaperCopy[];
  total: number;
  limit: number;
  offset: number;
}

export function listWorkpaperCopies(engagementId: string, limit = 20, offset = 0): Promise<WorkpaperCopyPage> {
  return api<WorkpaperCopyPage>(
    `/engagements/${encodeURIComponent(engagementId)}/workpaper-copies?limit=${limit}&offset=${offset}`
  );
}

/** Same-origin link to one saved copy, byte for byte as it was served. */
export function workpaperCopyHref(engagementId: string, copyId: string): string {
  return apiPath(`/engagements/${encodeURIComponent(engagementId)}/workpaper-copies/${encodeURIComponent(copyId)}/download`);
}
