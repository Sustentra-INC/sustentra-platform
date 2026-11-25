import { ApiError } from "../../../lib/api";

const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const NO_FILE = "The server did not send an Excel file, so nothing was saved. Please try again.";
const NO_SERVER = "Could not reach the server, so nothing was downloaded. Check your connection and try again.";

/** A file name safe to save under: no path, no odd characters, ending in .xlsx; ``fallback`` when nothing is left. */
export function safeFileName(raw: string | null, fallback: string): string {
  const cleaned = (raw ?? "")
    .replace(/[^A-Za-z0-9 ._-]+/g, "")
    .replace(/^[ ._-]+/, "")
    .trim()
    .slice(0, 120);
  if (!cleaned) return fallback;
  return /\.xlsx$/i.test(cleaned) ? cleaned : `${cleaned}.xlsx`;
}

function nameFrom(disposition: string | null): string | null {
  const match = disposition ? /filename="([^"]*)"/i.exec(disposition) : null;
  return match ? match[1] : null;
}

/**
 * Fetch an Excel file with the session cookie and save it. A refusal (409, 413, 500, 503, 401) or a body that is
 * not an Excel file throws, with the server's own words when it gave any, and saves nothing; a plain link would
 * have saved the error page as the file. Never retries: a retry of the workpaper download is a new record.
 */
export async function downloadExcel(url: string, fallbackName: string): Promise<void> {
  let response: Response;
  try {
    response = await fetch(url, { credentials: "same-origin", cache: "no-store" });
  } catch {
    throw new Error(NO_SERVER);
  }
  if (!response.ok) {
    let detail = `The download failed (${response.status}). Please try again.`;
    let parsed: unknown;
    try {
      parsed = await response.json();
      const d = (parsed as { detail?: unknown } | null)?.detail;
      if (typeof d === "string" && d) detail = d;
    } catch {
      // not JSON: keep the status-only message
    }
    throw new ApiError(response.status, detail, parsed, null);
  }
  if (!(response.headers.get("content-type") ?? "").toLowerCase().startsWith(XLSX)) throw new Error(NO_FILE);
  let blob: Blob;
  try {
    blob = await response.blob();
  } catch {
    throw new Error(NO_SERVER); // the connection dropped part way
  }
  const objectUrl = URL.createObjectURL(blob);
  try {
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = safeFileName(nameFrom(response.headers.get("content-disposition")), fallbackName);
    link.style.display = "none";
    document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
  }
}

/** The words to show for a failed download: the server's own for a refusal, never the upload message for a 413. */
export function downloadErrorMessage(error: unknown, fallback: (e: unknown) => string): string {
  if (error instanceof ApiError && error.status === 413) return error.detail;
  return fallback(error);
}
