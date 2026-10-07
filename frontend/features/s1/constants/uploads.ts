/**
 * Largest document the workpaper uploads (INFRA-007). Mirrors the API's
 * MAX_UPLOAD_MB (backend/app/core/config.py) and the upload route's limit in
 * deploy/Caddyfile; change all three together.
 */
export const MAX_UPLOAD_MB = 25;
export const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;

export const UPLOAD_TOO_LARGE = `This file is larger than the ${MAX_UPLOAD_MB} MB upload limit.`;
