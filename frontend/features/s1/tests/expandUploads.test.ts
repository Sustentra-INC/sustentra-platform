import { strToU8, zipSync } from "fflate";
import { describe, expect, it } from "vitest";

import { expandUploads } from "../utils/expandUploads";
import { pickFromFileList, type UploadPick } from "../utils/uploadSources";

const zipFile = (entries: Record<string, Uint8Array | string>, name = "Evidence.zip", level: 0 | 6 = 6) => {
  const data: Record<string, Uint8Array> = {};
  for (const [k, v] of Object.entries(entries)) data[k] = typeof v === "string" ? strToU8(v) : v;
  const bytes = zipSync(data, { level });
  return new File([bytes.buffer as ArrayBuffer], name, { type: "application/zip" });
};
const pickOf = (...files: File[]): UploadPick => pickFromFileList(files);
const folderPick = (paths: Record<string, string>): UploadPick => ({
  sources: Object.entries(paths).map(([path, body]) => ({ file: new File([body], path.split("/").pop()!), path })),
  refused: [],
});
const byPath = (r: Awaited<ReturnType<typeof expandUploads>>) => Object.fromEntries(r.items.map((i) => [i.path, i]));

describe("zips", () => {
  it("lists each inner file with its path, skips system files and folders, and says so in one line", async () => {
    const zip = zipFile({
      "Plant A/2025/jan.pdf": "pdf one",
      "Plant A/2025/feb.csv": "a,b",
      "Plant A/notes.xyz": "x",
      "Plant A/empty.pdf": "",
      "__MACOSX/Plant A/._jan.pdf": "junk",
      "Plant A/.DS_Store": "junk",
      "Plant A/Thumbs.db": "junk",
      "Plant A/desktop.ini": "junk",
      "Plant A/.hidden.pdf": "junk",
    });
    const r = await expandUploads(pickOf(zip));
    const items = byPath(r);
    expect(Object.keys(items).sort()).toEqual([
      "Plant A/2025/feb.csv",
      "Plant A/2025/jan.pdf",
      "Plant A/empty.pdf",
      "Plant A/notes.xyz",
    ]);
    expect(items["Plant A/2025/jan.pdf"].name).toBe("jan.pdf");
    expect(items["Plant A/empty.pdf"].reason).toBe("The file is empty.");
    expect(items["Plant A/notes.xyz"].reason).toMatch(/can't be read here/);
    const file = await items["Plant A/2025/jan.pdf"].open!();
    expect(file.name).toBe("jan.pdf");
    expect(await file.text()).toBe("pdf one");
    expect(r.summaries).toEqual(["4 files found in Evidence.zip, 2 can't be read, 5 system files skipped"]);
  });

  it("keeps two files with the same name in different folders, each with its own path and a name that tells them apart", async () => {
    const r = await expandUploads(pickOf(zipFile({ "A/bill.pdf": "1", "B/bill.pdf": "2" })));
    expect(r.items.map((i) => [i.path, i.name])).toEqual([["A/bill.pdf", "A - bill.pdf"], ["B/bill.pdf", "B - bill.pdf"]]);
    expect(await (await r.items[1].open!()).text()).toBe("2");
  });

  it("does not open a zip inside a zip", async () => {
    const inner = zipSync({ "a.pdf": strToU8("x") });
    const r = await expandUploads(pickOf(zipFile({ "inner.zip": inner, "ok.pdf": "x" })));
    expect(byPath(r)["inner.zip"].reason).toMatch(/zip inside a zip/);
    expect(byPath(r)["ok.pdf"].open).toBeDefined();
  });

  it("refuses an unsafe path for that entry only", async () => {
    const r = await expandUploads(pickOf(zipFile({ "../evil.pdf": "x", "/abs.pdf": "x", "C:/win.pdf": "x", "ok/ok.pdf": "x" })));
    const unsafe = r.items.filter((i) => i.reason?.includes("outside the zip"));
    expect(unsafe).toHaveLength(3);
    expect(r.items.filter((i) => i.open).map((i) => i.path)).toEqual(["ok/ok.pdf"]);
    for (const i of r.items) expect(i.name).not.toMatch(/\.\.|^\//);
  });

  it("shows control characters and right-to-left marks safely", async () => {
    const r = await expandUploads(pickOf(zipFile({ "evil\u202Egpj.pdf": "x", "a\u0007b.pdf": "x" })));
    for (const i of r.items) {
      expect(i.path).not.toMatch(/[\u0000-\u001F\u202E]/);
      expect(i.name).not.toMatch(/[\u0000-\u001F\u202E]/);
    }
  });

  it("lists a repeated path and says why the later one was not uploaded", async () => {
    const zip = zipFile({ "a/x.pdf": "1", "a/y.pdf": "2" });
    const bytes = new Uint8Array(await zip.arrayBuffer());
    for (let i = 0; i < bytes.length - 7; i++) {
      if (new TextDecoder("latin1").decode(bytes.subarray(i, i + 7)) === "a/y.pdf") bytes[i + 2] = 0x78; // y -> x
    }
    const r = await expandUploads(pickOf(new File([bytes.buffer as ArrayBuffer], "dup.zip")));
    expect(r.items).toHaveLength(2);
    expect(r.items[0].open).toBeDefined();
    expect(r.items[1].reason).toMatch(/same path/);
  });

  it("says plainly when a .zip is not a zip, or is cut short, and carries on with the others", async () => {
    const bad = new File(["this is not a zip file at all, just text padding padding"], "bad.zip");
    const good = zipFile({ "ok.pdf": "x" }, "good.zip");
    const full = zipFile({ "ok.pdf": "x".repeat(5000) }, "cut.zip", 0);
    const cut = new File([full.slice(0, Math.floor(full.size / 2))], "cut.zip");
    const r = await expandUploads(pickOf(bad, cut, good));
    expect(byPath(r)["bad.zip"].reason).toMatch(/isn't a zip/);
    expect(byPath(r)["cut.zip"].reason).toMatch(/cut short|isn't a zip/);
    expect(r.items.some((i) => i.path.endsWith("ok.pdf") && i.open)).toBe(true);
  });

  it("flags a damaged entry (bad checksum) when it is unpacked, not the others", async () => {
    const zip = zipFile({ "a.pdf": "x".repeat(2000), "b.pdf": "y".repeat(2000) }, "z.zip", 0);
    const bytes = new Uint8Array(await zip.arrayBuffer());
    const at = new TextDecoder("latin1").decode(bytes).indexOf("x".repeat(50));
    bytes[at + 10] ^= 0xff;
    const r = await expandUploads(pickOf(new File([bytes.buffer as ArrayBuffer], "z.zip")));
    await expect(byPath(r)["a.pdf"].open!()).rejects.toThrow(/Damaged/);
    expect(await (await byPath(r)["b.pdf"].open!()).text()).toBe("y".repeat(2000));
  });

  it("refuses an encrypted entry only", async () => {
    const zip = zipFile({ "secret.pdf": "x", "ok.pdf": "y" });
    const bytes = new Uint8Array(await zip.arrayBuffer());
    const dv = new DataView(bytes.buffer);
    for (let i = 0; i < bytes.length - 46; i++) {
      if (dv.getUint32(i, true) === 0x02014b50) {
        const name = new TextDecoder().decode(bytes.subarray(i + 46, i + 46 + dv.getUint16(i + 28, true)));
        if (name === "secret.pdf") dv.setUint16(i + 8, dv.getUint16(i + 8, true) | 1, true);
      }
    }
    const r = await expandUploads(pickOf(new File([bytes.buffer as ArrayBuffer], "e.zip")));
    expect(byPath(r)["secret.pdf"].reason).toMatch(/Password-protected/);
    expect(byPath(r)["ok.pdf"].open).toBeDefined();
  });

  it("reads zip64 sizes from the extra field", async () => {
    const zip = zipFile({ "a.pdf": "hello" }, "z64.zip", 0);
    const bytes = new Uint8Array(await zip.arrayBuffer());
    // Rebuild the central entry with 0xFFFFFFFF sizes and a zip64 extra field carrying the real ones.
    const dv = new DataView(bytes.buffer);
    let cd = -1;
    for (let i = 0; i < bytes.length - 4; i++) if (dv.getUint32(i, true) === 0x02014b50) cd = i;
    const nameLen = dv.getUint16(cd + 28, true);
    const entryEnd = cd + 46 + nameLen;
    const eocd = bytes.length - 22;
    const extra = new Uint8Array(20);
    const ev = new DataView(extra.buffer);
    ev.setUint16(0, 1, true);
    ev.setUint16(2, 16, true);
    ev.setBigUint64(4, 5n, true);
    ev.setBigUint64(12, 5n, true);
    const out = new Uint8Array(bytes.length + 20);
    out.set(bytes.subarray(0, entryEnd), 0);
    out.set(extra, entryEnd);
    out.set(bytes.subarray(entryEnd), entryEnd + 20);
    const ov = new DataView(out.buffer);
    ov.setUint32(cd + 20, 0xffffffff, true);
    ov.setUint32(cd + 24, 0xffffffff, true);
    ov.setUint16(cd + 30, 20, true);
    ov.setUint32(eocd + 20 + 12, ov.getUint32(eocd + 20 + 12, true) + 20, true);
    const r = await expandUploads(pickOf(new File([out.buffer as ArrayBuffer], "z64.zip")));
    expect(r.items).toHaveLength(1);
    expect(await (await r.items[0].open!()).text()).toBe("hello");
  });

  it("refuses a zip with too many files, too big a total, or too big a file", async () => {
    const many = zipFile({ "a.pdf": "1", "b.pdf": "2", "c.pdf": "3" });
    const r1 = await expandUploads(pickOf(many), { limits: { maxFiles: 2 } });
    expect(r1.items).toHaveLength(1);
    expect(r1.items[0].reason).toMatch(/more than 2 files/);

    const r2 = await expandUploads(pickOf(zipFile({ "a.pdf": "x".repeat(600) })), { limits: { maxUnpackedBytes: 500 } });
    expect(r2.items[0].reason).toMatch(/unpacks to more than/);

    const r3 = await expandUploads(pickOf(zipFile({ "a.pdf": "x".repeat(600), "b.pdf": "ok" })), { limits: { maxFileBytes: 500 } });
    expect(byPath(r3)["a.pdf"].reason).toMatch(/larger than/);
    expect(byPath(r3)["b.pdf"].open).toBeDefined();

    const r4 = await expandUploads(pickOf(zipFile({ "a.pdf": "x" })), { limits: { maxZipBytes: 10 } });
    expect(r4.items[0].reason).toMatch(/larger than/);
  });

  it("stops a zip that lies about its size, on the bytes that really come out", async () => {
    const zip = zipFile({ "lie.pdf": "x".repeat(5000) }, "lie.zip", 6);
    const bytes = new Uint8Array(await zip.arrayBuffer());
    const dv = new DataView(bytes.buffer);
    for (let i = 0; i < bytes.length - 4; i++) {
      if (dv.getUint32(i, true) === 0x02014b50) dv.setUint32(i + 24, 100, true); // says 100 bytes
      if (dv.getUint32(i, true) === 0x04034b50) dv.setUint32(i + 22, 100, true);
    }
    const r = await expandUploads(pickOf(new File([bytes.buffer as ArrayBuffer], "lie.zip")));
    await expect(r.items[0].open!()).rejects.toThrow(/Damaged|Over the size/);
  });

  it("stops a bomb by ratio and by the running total of real bytes", async () => {
    const big = new Uint8Array(3 * 1024 * 1024); // zeros: packs to a few KB
    const zip = zipFile({ "bomb.csv": big });
    const r = await expandUploads(pickOf(zip));
    expect(r.items[0].reason).toMatch(/far more than it should/);

    // Each zip is within the limit on its own; together they pass it, and the running total says so.
    const r2 = await expandUploads(
      pickOf(zipFile({ "a.csv": "x,y\n".repeat(300) }, "One.zip"), zipFile({ "b.csv": "x,y\n".repeat(300) }, "Two.zip")),
      { limits: { maxUnpackedBytes: 1500 } }
    );
    await r2.items[0].open!();
    await expect(r2.items[1].open!()).rejects.toThrow(/more than/);
  });

  it("stops unpacking when cancelled: the signal is given when the file is opened", async () => {
    const c = new AbortController();
    const r = await expandUploads(pickOf(zipFile({ "a.csv": "x".repeat(100) })));
    c.abort();
    await expect(r.items[0].open!(c.signal)).rejects.toThrow(/Cancelled/);
    await expect(r.items[0].open!(new AbortController().signal)).resolves.toBeInstanceOf(File); // a retry, fresh signal
    const stopped = await expandUploads(pickOf(zipFile({ "a.csv": "x" })), { signal: c.signal });
    expect(stopped.items).toHaveLength(0);
  });

  it("decodes names stored in the old DOS code page", async () => {
    const zip = zipFile({ "x.pdf": "x" });
    const bytes = new Uint8Array(await zip.arrayBuffer());
    // Rename "x.pdf" -> bytes 0x82 (é in cp437) + ".pdf" in both headers, with the UTF-8 flag off.
    for (let i = 0; i < bytes.length - 5; i++) if (bytes[i] === 0x78 && bytes[i + 1] === 0x2e) bytes[i] = 0x82;
    const r = await expandUploads(pickOf(new File([bytes.buffer as ArrayBuffer], "d.zip")));
    expect(r.items[0].path).toBe("é.pdf");
  });

  it("prefixes the zip's name when more than one thing is picked", async () => {
    const r = await expandUploads(pickOf(zipFile({ "a.pdf": "x" }, "One.zip"), zipFile({ "a.pdf": "y" }, "Two.zip")));
    expect(r.items.map((i) => i.path)).toEqual(["One.zip/a.pdf", "Two.zip/a.pdf"]);
    expect(r.summaries).toHaveLength(2);
  });
});

describe("folders", () => {
  it("lists every file by path, skips junk, and counts them in one line", async () => {
    const r = await expandUploads(
      folderPick({
        "Evidence/Plant A/jan.pdf": "x",
        "Evidence/Plant A/jan.pdf.bak": "x",
        "Evidence/.DS_Store": "x",
        "Evidence/empty.csv": "",
      })
    );
    expect(r.items.map((i) => i.path)).toEqual(["Evidence/Plant A/jan.pdf", "Evidence/Plant A/jan.pdf.bak", "Evidence/empty.csv"]);
    expect(r.summaries).toEqual(["3 files found in Evidence, 2 can't be read, 1 system file skipped"]);
  });

  it("refuses a folder over the file limit, and a pick over the total limit", async () => {
    const files = Object.fromEntries(Array.from({ length: 5 }, (_, i) => [`Big/f${i}.pdf`, "x"]));
    const r = await expandUploads(folderPick(files), { limits: { maxFiles: 3 } });
    expect(r.items).toHaveLength(1);
    expect(r.items[0].reason).toMatch(/more than 3 files/);

    const two = folderPick({ "A/1.pdf": "x", "A/2.pdf": "x", "B/1.pdf": "x", "B/2.pdf": "x" });
    const r2 = await expandUploads(two, { limits: { maxFiles: 3 } });
    expect(r2.items.filter((i) => i.open)).toHaveLength(2);
    expect(r2.items.find((i) => i.reason)?.reason).toMatch(/past 3 files/);
  });

  it("opens a zip found inside a folder, with the folder in its path", async () => {
    const inner = zipFile({ "a.pdf": "x" }, "pack.zip");
    const r = await expandUploads({ sources: [{ file: inner, path: "Evidence/pack.zip" }], refused: [] });
    expect(r.items[0].path).toBe("Evidence/pack.zip/a.pdf");
  });

  it("never sends a path: the name is the last part", async () => {
    const r = await expandUploads(folderPick({ "A/B/C/doc.pdf": "x" }));
    expect(r.items[0].name).toBe("doc.pdf");
  });
});

describe("files with the same name", () => {
  const names = async (paths: Record<string, string>) =>
    Object.fromEntries((await expandUploads(folderPick(paths))).items.map((i) => [i.path, i.name]));

  it("keep their own name when it is unique, exactly", async () => {
    expect(await names({ "A/one.pdf": "x", "B/two.pdf": "x" })).toEqual({ "A/one.pdf": "one.pdf", "B/two.pdf": "two.pdf" });
  });

  it("are sent with the shortest parent folder that tells them apart, joined with ' - '", async () => {
    expect(await names({ "Plant A/bill.pdf": "x", "Plant B/bill.pdf": "x", "Plant B/other.pdf": "x" })).toEqual({
      "Plant A/bill.pdf": "Plant A - bill.pdf",
      "Plant B/bill.pdf": "Plant B - bill.pdf",
      "Plant B/other.pdf": "other.pdf",
    });
  });

  it("go deeper only as far as needed: three levels, and the same parent names under different years", async () => {
    expect(await names({ "2024/Plant A/bill.pdf": "x", "2025/Plant A/bill.pdf": "x" })).toEqual({
      "2024/Plant A/bill.pdf": "2024 - Plant A - bill.pdf",
      "2025/Plant A/bill.pdf": "2025 - Plant A - bill.pdf",
    });
    expect(await names({ "Site/2024/Plant A/bill.pdf": "x", "Site/2025/Plant A/bill.pdf": "x", "Site/2025/Plant B/bill.pdf": "x" })).toEqual({
      "Site/2024/Plant A/bill.pdf": "2024 - Plant A - bill.pdf",
      "Site/2025/Plant A/bill.pdf": "2025 - Plant A - bill.pdf",
      "Site/2025/Plant B/bill.pdf": "2025 - Plant B - bill.pdf",
    });
  });

  it("compare without regard to letter case", async () => {
    expect(await names({ "A/Bill.PDF": "x", "B/bill.pdf": "x" })).toEqual({ "A/Bill.PDF": "A - Bill.PDF", "B/bill.pdf": "B - bill.pdf" });
  });

  it("compare as the server will store them (it replaces anything but A-Z a-z 0-9 . _ - with _)", async () => {
    const out = await names({ "A/a b.pdf": "x", "B/a_b.pdf": "x", "C/電気.pdf": "x", "D/水.pdf": "x" });
    const stored = Object.values(out).map((n) => n.replace(/[^A-Za-z0-9._-]+/g, "_").toLowerCase());
    expect(new Set(stored).size).toBe(4);
    expect(out["A/a b.pdf"]).toBe("A - a b.pdf");
  });

  it("never end up equal after the server's cleaning, even when nothing tells them apart", async () => {
    const out = await names({ "電/電.pdf": "x", "水/水.pdf": "x", "火/火.pdf": "x" });
    const stored = Object.values(out).map((n) => n.replace(/[^A-Za-z0-9._-]+/g, "_").toLowerCase());
    expect(new Set(stored).size).toBe(3);
  });

  it("a loose file keeps its name when another of the same name sits in a folder", async () => {
    expect(await names({ "bill.pdf": "x", "A/bill.pdf": "x" })).toEqual({ "bill.pdf": "bill.pdf", "A/bill.pdf": "A - bill.pdf" });
  });

  it("keeps the 200-character cap and the extension", async () => {
    const long = `${"x".repeat(300)}.pdf`;
    const out = Object.values(await names({ [`A/${long}`]: "x", [`B/${long}`]: "x" }));
    for (const name of out) {
      expect(name.length).toBeLessThanOrEqual(200);
      expect(name.endsWith(".pdf")).toBe(true);
    }
    expect(new Set(out).size).toBe(2);
  });

  it("does the same inside zips, and the bytes sent carry the new name", async () => {
    const r = await expandUploads(pickOf(zipFile({ "A/bill.pdf": "1", "B/bill.pdf": "2" })));
    expect(r.items.map((i) => i.name)).toEqual(["A - bill.pdf", "B - bill.pdf"]);
    const file = await r.items[1].open!();
    expect(file.name).toBe("B - bill.pdf");
    expect(await file.text()).toBe("2");
  });

  it("only files that will be sent are renamed", async () => {
    const r = await expandUploads(folderPick({ "A/bill.pdf": "x", "B/bill.pdf": "" }));
    expect(r.items.map((i) => i.name)).toEqual(["bill.pdf", "bill.pdf"]);
  });
});
