/**
 * Reads a .zip in the browser without holding it in memory: the index (central directory) is read
 * from the end of the file with Blob.slice, and each entry is unpacked on demand, in small pieces,
 * counting the bytes that really come out (a header can lie about sizes). fflate is loaded only
 * when a zip is opened (dynamic import). Nothing here touches the server.
 */

export class ZipError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ZipError";
  }
}

export interface ZipEntry {
  /** Name as stored, decoded (UTF-8 when flagged, else UTF-8 if valid, else code page 437). */
  name: string;
  isDirectory: boolean;
  isLink: boolean;
  encrypted: boolean;
  method: number;
  compressedSize: number;
  size: number;
  crc: number;
  localOffset: number;
}

const SIG_EOCD = 0x06054b50;
const SIG_EOCD64_LOCATOR = 0x07064b50;
const SIG_EOCD64 = 0x06064b50;
const SIG_CENTRAL = 0x02014b50;
const SIG_LOCAL = 0x04034b50;
const MAX_INDEX_BYTES = 32 * 1024 * 1024;
const PUSH_BYTES = 16 * 1024;
const READ_BYTES = 256 * 1024;

const CP437 =
  "ÇüéâäàåçêëèïîìÄÅÉæÆôöòûùÿÖÜ¢£¥₧ƒáíóúñÑªº¿⌐¬½¼¡«»░▒▓│┤╡╢╖╕╣║╗╝╜╛┐└┴┬├─┼╞╟╚╔╩╦╠═╬╧╨╤╥╙╘╒╓╫╪┘┌█▄▌▐▀αßΓπΣσµτΦΘΩδ∞φε∩≡±≥≤⌠⌡÷≈°∙·√ⁿ²■ ";

function decodeName(bytes: Uint8Array, utf8Flag: boolean): string {
  if (utf8Flag) return new TextDecoder("utf-8").decode(bytes);
  if (bytes.every((b) => b < 128)) return new TextDecoder("utf-8").decode(bytes);
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    return Array.from(bytes, (b) => (b < 128 ? String.fromCharCode(b) : CP437[b - 128])).join("");
  }
}

function safeNumber(value: bigint, what: string): number {
  if (value > BigInt(Number.MAX_SAFE_INTEGER)) throw new ZipError(`The zip is damaged (${what} is out of range).`);
  return Number(value);
}

async function bytesOf(blob: Blob, start: number, end: number): Promise<Uint8Array> {
  return new Uint8Array(await blob.slice(start, end).arrayBuffer());
}

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32Update(crc: number, chunk: Uint8Array): number {
  let c = crc ^ 0xffffffff;
  for (let i = 0; i < chunk.length; i++) c = CRC_TABLE[(c ^ chunk[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

/** Reads the index. Throws ZipError with a plain reason when the file is not a usable zip. */
export async function readZipEntries(blob: Blob, maxEntries: number): Promise<ZipEntry[]> {
  if (blob.size < 22) throw new ZipError("This isn't a zip file, or it was cut short.");
  const tailStart = Math.max(0, blob.size - (22 + 0xffff));
  const tail = await bytesOf(blob, tailStart, blob.size);
  const tv = new DataView(tail.buffer);
  let eocd = -1;
  for (let i = tail.length - 22; i >= 0; i--) {
    if (tv.getUint32(i, true) === SIG_EOCD) {
      eocd = i;
      break;
    }
  }
  if (eocd < 0) throw new ZipError("This isn't a zip file, or it was cut short.");
  const disk = tv.getUint16(eocd + 4, true);
  const cdDisk = tv.getUint16(eocd + 6, true);
  if (disk !== 0 || cdDisk !== 0) throw new ZipError("Zips split across several files can't be opened.");
  let total = tv.getUint16(eocd + 10, true);
  let indexSize = tv.getUint32(eocd + 12, true);
  let indexOffset = tv.getUint32(eocd + 16, true);

  if (total === 0xffff || indexSize === 0xffffffff || indexOffset === 0xffffffff) {
    const locatorAt = eocd - 20;
    if (locatorAt < 0 || tv.getUint32(locatorAt, true) !== SIG_EOCD64_LOCATOR)
      throw new ZipError("The zip is damaged (its index is missing).");
    const eocd64At = safeNumber(tv.getBigUint64(locatorAt + 8, true), "index position");
    if (eocd64At + 56 > blob.size) throw new ZipError("The zip is damaged (its index is missing).");
    const e64 = new DataView((await bytesOf(blob, eocd64At, eocd64At + 56)).buffer);
    if (e64.getUint32(0, true) !== SIG_EOCD64) throw new ZipError("The zip is damaged (its index is missing).");
    total = safeNumber(e64.getBigUint64(32, true), "entry count");
    indexSize = safeNumber(e64.getBigUint64(40, true), "index size");
    indexOffset = safeNumber(e64.getBigUint64(48, true), "index position");
  }

  if (total > maxEntries) throw new ZipError(`The zip lists more than ${maxEntries.toLocaleString("en-US")} items.`);
  if (indexSize > MAX_INDEX_BYTES || indexOffset + indexSize > blob.size)
    throw new ZipError("The zip is damaged (its index is cut short).");

  const index = await bytesOf(blob, indexOffset, indexOffset + indexSize);
  const iv = new DataView(index.buffer);
  const entries: ZipEntry[] = [];
  let at = 0;
  for (let n = 0; n < total; n++) {
    if (at + 46 > index.length || iv.getUint32(at, true) !== SIG_CENTRAL)
      throw new ZipError("The zip is damaged (its index is unreadable).");
    const madeBy = iv.getUint16(at + 4, true);
    const flags = iv.getUint16(at + 8, true);
    const method = iv.getUint16(at + 10, true);
    const crc = iv.getUint32(at + 16, true);
    let compressedSize = iv.getUint32(at + 20, true);
    let size = iv.getUint32(at + 24, true);
    const nameLen = iv.getUint16(at + 28, true);
    const extraLen = iv.getUint16(at + 30, true);
    const commentLen = iv.getUint16(at + 32, true);
    const externalAttrs = iv.getUint32(at + 38, true);
    let localOffset = iv.getUint32(at + 42, true);
    const next = at + 46 + nameLen + extraLen + commentLen;
    if (next > index.length) throw new ZipError("The zip is damaged (its index is cut short).");
    const nameBytes = index.subarray(at + 46, at + 46 + nameLen);
    // zip64 extra field: the values that did not fit in 32 bits, in a fixed order.
    let ex = at + 46 + nameLen;
    const exEnd = ex + extraLen;
    while (ex + 4 <= exEnd) {
      const id = iv.getUint16(ex, true);
      const len = iv.getUint16(ex + 2, true);
      if (id === 0x0001) {
        let p = ex + 4;
        const end = Math.min(ex + 4 + len, exEnd);
        if (size === 0xffffffff && p + 8 <= end) {
          size = safeNumber(iv.getBigUint64(p, true), "size");
          p += 8;
        }
        if (compressedSize === 0xffffffff && p + 8 <= end) {
          compressedSize = safeNumber(iv.getBigUint64(p, true), "size");
          p += 8;
        }
        if (localOffset === 0xffffffff && p + 8 <= end) {
          localOffset = safeNumber(iv.getBigUint64(p, true), "position");
        }
      }
      ex += 4 + len;
    }
    const name = decodeName(nameBytes, (flags & 0x800) !== 0);
    const unixMode = madeBy >> 8 === 3 ? (externalAttrs >>> 16) & 0xf000 : 0;
    entries.push({
      name,
      isDirectory: name.endsWith("/") || name.endsWith("\\") || unixMode === 0x4000,
      isLink: unixMode === 0xa000,
      encrypted: (flags & 0x1) !== 0 || (flags & 0x40) !== 0,
      method,
      compressedSize,
      size,
      crc,
      localOffset,
    });
    at = next;
  }
  return entries;
}

export interface ExtractOptions {
  /** Most bytes this one file may unpack to. */
  maxBytes: number;
  /** Told of each piece of real output; throw to stop (a running total across the zip). */
  onBytes?: (n: number) => void;
  signal?: AbortSignal;
  maxRatio: number;
}

/** Unpacks one entry. Sizes are enforced on the bytes that really come out, not the declared ones. */
export async function extractZipEntry(blob: Blob, entry: ZipEntry, options: ExtractOptions): Promise<Uint8Array> {
  if (entry.encrypted) throw new ZipError("Password-protected.");
  if (entry.method !== 0 && entry.method !== 8) throw new ZipError("Packed in a way that can't be opened here.");
  if (entry.size > options.maxBytes) throw new ZipError("Over the size limit.");
  if (entry.localOffset + 30 > blob.size) throw new ZipError("The zip is cut short.");
  const header = new DataView((await bytesOf(blob, entry.localOffset, entry.localOffset + 30)).buffer);
  if (header.getUint32(0, true) !== SIG_LOCAL) throw new ZipError("Damaged inside the zip.");
  const dataStart = entry.localOffset + 30 + header.getUint16(26, true) + header.getUint16(28, true);
  const dataEnd = dataStart + entry.compressedSize;
  if (dataEnd > blob.size) throw new ZipError("The zip is cut short.");

  const parts: Uint8Array[] = [];
  let out = 0;
  let crc = 0;
  let packedIn = 0;
  const emit = (chunk: Uint8Array) => {
    out += chunk.length;
    if (out > options.maxBytes) throw new ZipError("Over the size limit.");
    if (out > entry.size) throw new ZipError("Damaged inside the zip (more data than it says).");
    if (out > 1024 * 1024 && out / Math.max(1, packedIn) > options.maxRatio)
      throw new ZipError("Unpacks to far more than it should.");
    options.onBytes?.(chunk.length);
    crc = crc32Update(crc, chunk);
    parts.push(chunk);
  };

  if (entry.method === 0) {
    if (entry.compressedSize !== entry.size) throw new ZipError("Damaged inside the zip.");
    for (let pos = dataStart; pos < dataEnd; pos += READ_BYTES) {
      if (options.signal?.aborted) throw new ZipError("Cancelled.");
      packedIn = pos - dataStart + 1;
      emit(await bytesOf(blob, pos, Math.min(dataEnd, pos + READ_BYTES)));
    }
  } else {
    const { Inflate } = await import("fflate");
    let failed: unknown = null;
    const inflater = new Inflate((chunk) => {
      try {
        emit(chunk.slice());
      } catch (error) {
        failed = error;
        throw error;
      }
    });
    try {
      if (entry.compressedSize === 0) inflater.push(new Uint8Array(0), true);
      for (let pos = dataStart; pos < dataEnd; pos += READ_BYTES) {
        if (options.signal?.aborted) throw new ZipError("Cancelled.");
        const block = await bytesOf(blob, pos, Math.min(dataEnd, pos + READ_BYTES));
        for (let o = 0; o < block.length; o += PUSH_BYTES) {
          const piece = block.subarray(o, Math.min(block.length, o + PUSH_BYTES));
          packedIn += piece.length;
          inflater.push(piece, pos + o + piece.length >= dataEnd);
        }
      }
    } catch (error) {
      if (error instanceof ZipError) throw error;
      if (failed instanceof ZipError) throw failed;
      throw new ZipError("Damaged inside the zip.");
    }
  }

  if (out !== entry.size) throw new ZipError("Damaged inside the zip (its size doesn't match).");
  if (crc !== entry.crc) throw new ZipError("Damaged inside the zip (its checksum doesn't match).");
  if (parts.length === 1) return parts[0];
  const whole = new Uint8Array(out);
  let at = 0;
  for (const part of parts) {
    whole.set(part, at);
    at += part.length;
  }
  return whole;
}
