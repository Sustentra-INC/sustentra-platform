/**
 * Largest document the workpaper uploads (INFRA-007). Mirrors the API's
 * MAX_UPLOAD_MB (backend/app/core/config.py) and the upload route's limit in
 * deploy/Caddyfile; change all three together.
 */
export const MAX_UPLOAD_MB = 25;
export const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;

export const UPLOAD_TOO_LARGE = `This file is larger than the ${MAX_UPLOAD_MB} MB upload limit.`;

/**
 * What the workpaper can read: the extensions, then the media types, the upload route
 * accepts (backend/app/api/documents.py, `_is_readable_upload`, which narrows the parser's
 * detection in backend/app/services/parser_service.py). Images are only PNG, JPEG and
 * TIFF, the formats Textract reads, matching the 415's words. The route refuses anything
 * else with a 415, so the dialog sets such files aside first. Change both together:
 * tests/uploadTypes.test.ts fails when these lists and the backend's drift apart.
 */
export const READABLE_UPLOAD_EXTENSIONS = [
  ".pdf",
  ".docx",
  ".xlsx",
  ".xlsm",
  ".xls",
  ".csv",
  ".txt",
  ".md",
  ".markdown",
  ".png",
  ".jpg",
  ".jpeg",
  ".tif",
  ".tiff",
] as const;

export const READABLE_UPLOAD_TYPES: ReadonlySet<string> = new Set([
  "text/plain",
  "text/markdown",
  "text/csv",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/vnd.ms-excel",
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "image/png",
  "image/jpeg",
  "image/tiff",
]);

/**
 * Image extensions the parser knows but no reader opens. As in the upload route, the
 * extension decides first, so these are refused whatever their media type says.
 */
const UNREADABLE_IMAGE_EXTENSIONS: readonly string[] = [".gif", ".bmp", ".webp"];

/** The file pickers' `accept` list. */
export const UPLOAD_ACCEPT = READABLE_UPLOAD_EXTENSIONS.join(",");

/** Whether a reader can open this file: by its extension first, then its media type. */
export function isReadableUpload(file: { name: string; type?: string }): boolean {
  const dot = file.name.lastIndexOf(".");
  const extension = dot > 0 ? file.name.slice(dot).toLowerCase() : ""; // ".pdf" alone has none, as in Python
  if ((READABLE_UPLOAD_EXTENSIONS as readonly string[]).includes(extension)) return true;
  if (UNREADABLE_IMAGE_EXTENSIONS.includes(extension)) return false;
  const type = (file.type ?? "").split(";")[0].trim().toLowerCase();
  return READABLE_UPLOAD_TYPES.has(type);
}

/** The same words as the upload route's 415. */
export function unreadableUploadMessage(filename: string): string {
  return (
    `${filename} can't be read here. Upload a PDF, Word (.docx), Excel (.xls or .xlsx), CSV or text file, ` +
    "or a scan or photo (PNG, JPG or TIFF)."
  );
}

/** The Evidence banner's title after an upload: what didn't work. */
export function uploadProblemTitle(notUploaded: number, notRead: number): string {
  const files = (n: number) => `${n} file${n === 1 ? "" : "s"}`;
  if (notUploaded && notRead) return `Couldn't upload or read ${files(notUploaded + notRead)}`;
  if (notRead) return `Couldn't read ${files(notRead)}`;
  return `Couldn't upload ${files(notUploaded)}`;
}
