/* @vitest-environment jsdom */
import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";

import { EvidenceWorkspace } from "../components/EvidenceWorkspace";
import { UploadDialog, uploadTasksFor, type UploadTask } from "../components/UploadDialog";
import { isReadableUpload, UPLOAD_ACCEPT, uploadProblemTitle } from "../constants/uploads";
import { engagementConfig } from "../fixtures/engagementConfig";
import { manufacturerEvidence } from "../fixtures/evidence/manufacturerEvidence";

const ZIP_MESSAGE =
  "qa_archive.zip can't be read here. Upload a PDF, Word (.docx), Excel (.xls or .xlsx), CSV or text file, " +
  "an email (.eml), or a scan or photo (PNG, JPG or TIFF).";

const file = (name: string, type = "") => new File(["x"], name, { type });

function renderDialog(tasks: UploadTask[]) {
  render(<UploadDialog onClose={vi.fn()} onUploadFiles={vi.fn()} batch={[]} tasks={tasks} onOpenWorkspace={vi.fn()} />);
}

describe("upload: files no parser can read", () => {
  // The same check as the upload route (backend/app/api/documents.py): extension, then media type.
  it.each([
    ["bill.pdf", ""],
    ["letter.docx", ""],
    ["log.xlsx", ""],
    ["log.xlsm", ""],
    ["legacy.xls", "application/vnd.ms-excel"],
    ["readings.csv", ""],
    ["notes.txt", ""],
    ["notes.md", ""],
    ["Fwd March bill.eml", "message/rfc822"],
    ["Fwd March bill.EML", ""],
    ["meter.PNG", ""],
    ["meter.jpg", ""],
    ["meter.jpeg", ""],
    ["scan.tif", ""],
    ["scan.tiff", ""],
    ["scan", "image/png"],
    ["photo", "image/jpeg"],
    ["fax", "image/tiff"],
    ["export", "text/csv; charset=utf-8"],
    ["export", "application/vnd.ms-excel"],
    ["message", "message/rfc822"],
  ])("reads %s (%s)", (name, type) => {
    expect(isReadableUpload(file(name, type))).toBe(true);
  });

  it.each([
    ["qa_archive.zip", "application/zip"],
    ["page.html", "text/html"],
    ["old-bill.doc", "application/msword"],
    // Outlook's own format is not read yet, whatever media type the browser gives it.
    ["Fwd March bill.msg", "application/vnd.ms-outlook"],
    ["Fwd March bill.msg", "message/rfc822"],
    ["readings", ""],
    // Images Textract can't read (it takes PNG, JPEG and TIFF): by extension, then media type.
    ["photo.webp", "image/webp"],
    ["photo.gif", "image/gif"],
    ["scan.bmp", "image/bmp"],
    ["photo.webp", "image/png"],
    ["logo.svg", "image/svg+xml"],
    ["scan", "image/heic"],
    ["photo.heic", "image/heic"],
  ])("does not read %s (%s)", (name, type) => {
    expect(isReadableUpload(file(name, type))).toBe(false);
  });

  it("lets the file picker offer only what can be read", () => {
    renderDialog([]);
    const input = document.querySelector('input[type="file"]');
    expect(input).toHaveAttribute("accept", UPLOAD_ACCEPT);
    // The same formats the refusal names: PDF, Word, Excel, CSV, text, email, and PNG, JPG or TIFF.
    expect(UPLOAD_ACCEPT.split(",")).toEqual([
      ".pdf", ".docx", ".xlsx", ".xlsm", ".xls", ".csv", ".txt", ".md", ".markdown", ".eml", ".png", ".jpg", ".jpeg",
      ".tif", ".tiff",
    ]);
  });

  it("sets an unsupported image aside before anything is sent", () => {
    const [webp, png] = uploadTasksFor([file("photo.webp", "image/webp"), file("meter.png", "image/png")], "b1");
    expect(webp.stage).toBe("not_uploaded");
    expect(webp.error).toBe(
      "photo.webp can't be read here. Upload a PDF, Word (.docx), Excel (.xls or .xlsx), CSV or text file, " +
        "an email (.eml), or a scan or photo (PNG, JPG or TIFF)."
    );
    expect(png.stage).toBe("waiting");
  });

  it("sets an unreadable file aside before anything is sent", () => {
    const tasks = uploadTasksFor([file("bill.pdf", "application/pdf"), file("qa_archive.zip", "application/zip"), file("log.csv", "text/csv")], "b1");
    expect(tasks.map((t) => [t.filename, t.stage, t.error])).toEqual([
      ["bill.pdf", "waiting", undefined],
      ["qa_archive.zip", "not_uploaded", ZIP_MESSAGE],
      ["log.csv", "waiting", undefined],
    ]);
  });

  it("lists it in the dialog as not uploaded, with what to do", () => {
    const [pdf, zip, csv] = uploadTasksFor([file("bill.pdf"), file("qa_archive.zip"), file("log.csv")], "b1");
    renderDialog([{ ...pdf, stage: "done", progress: 1 }, zip, { ...csv, stage: "done", progress: 1 }]);

    expect(screen.getByText("Not uploaded")).toBeInTheDocument();
    expect(screen.getByText(ZIP_MESSAGE)).toBeInTheDocument();
    expect(screen.getByText("2 of 3 files uploaded and read")).toBeInTheDocument();
    expect(screen.getByText(/1 not uploaded/)).toBeInTheDocument();
    expect(screen.getByText("Done. Each uploaded file is a row in Evidence.")).toBeInTheDocument();
  });

  it("says so when nothing was uploaded", () => {
    renderDialog(uploadTasksFor([file("qa_archive.zip")], "b1"));
    expect(screen.getByText("0 of 1 file uploaded and read")).toBeInTheDocument();
    expect(screen.getByText("Nothing was uploaded.")).toBeInTheDocument();
  });

  it("shows the API's reason for a file it refused", () => {
    const [task] = uploadTasksFor([file("bill.pdf")], "b1");
    renderDialog([{ ...task, stage: "not_uploaded", error: "This file is larger than the 25 MB upload limit." }]);
    expect(screen.getByText("Not uploaded")).toBeInTheDocument();
    expect(screen.getByText("This file is larger than the 25 MB upload limit.")).toBeInTheDocument();
  });
});

describe("evidence banner: says what didn't work", () => {
  it("titles upload problems plainly", () => {
    expect(uploadProblemTitle(1, 0)).toBe("Couldn't upload 1 file");
    expect(uploadProblemTitle(2, 0)).toBe("Couldn't upload 2 files");
    expect(uploadProblemTitle(0, 1)).toBe("Couldn't read 1 file");
    expect(uploadProblemTitle(1, 1)).toBe("Couldn't upload or read 2 files");
  });

  it("shows the title, then the per-file message", () => {
    render(
      <EvidenceWorkspace
        engagement={engagementConfig}
        evidence={manufacturerEvidence}
        asks={[]}
        onSaveAsk={vi.fn()}
        onEvidenceChange={vi.fn()}
        onOpenExtraction={vi.fn()}
        onOpenUpload={vi.fn()}
        backendError={{ title: uploadProblemTitle(1, 0), message: ZIP_MESSAGE }}
      />
    );
    const banner = screen.getByRole("status");
    expect(banner).toHaveTextContent("Couldn't upload 1 file");
    expect(banner).toHaveTextContent(ZIP_MESSAGE);
    expect(screen.queryByText("Backend call failed")).toBeNull();
  });
});
