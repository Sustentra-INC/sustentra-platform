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
  "qa_archive.zip can't be read here. Upload a PDF, Word (.docx), Excel (.xlsx), CSV or text file, " +
  "or a scan or photo (PNG, JPG or TIFF).";

const file = (name: string, type = "") => new File(["x"], name, { type });

function renderDialog(tasks: UploadTask[]) {
  render(<UploadDialog onClose={vi.fn()} onUploadFiles={vi.fn()} batch={[]} tasks={tasks} onOpenWorkspace={vi.fn()} />);
}

describe("upload: files no parser can read", () => {
  // The same detection as backend/app/services/parser_service.py: extension, then media type.
  it.each([
    ["bill.pdf", ""],
    ["letter.docx", ""],
    ["log.xlsx", ""],
    ["log.xlsm", ""],
    ["readings.csv", ""],
    ["notes.txt", ""],
    ["notes.md", ""],
    ["meter.PNG", ""],
    ["meter.jpeg", ""],
    ["scan.tiff", ""],
    ["photo.webp", ""],
    ["scan", "image/heic"],
    ["export", "text/csv; charset=utf-8"],
  ])("reads %s", (name, type) => {
    expect(isReadableUpload(file(name, type))).toBe(true);
  });

  it.each([
    ["qa_archive.zip", "application/zip"],
    ["page.html", "text/html"],
    ["old-bill.doc", "application/msword"],
    ["legacy.xls", "application/vnd.ms-excel"],
    ["readings", ""],
  ])("does not read %s", (name, type) => {
    expect(isReadableUpload(file(name, type))).toBe(false);
  });

  it("lets the file picker offer only what can be read", () => {
    renderDialog([]);
    const input = document.querySelector('input[type="file"]');
    expect(input).toHaveAttribute("accept", UPLOAD_ACCEPT);
    expect(UPLOAD_ACCEPT.split(",")).toEqual(expect.arrayContaining([".pdf", ".docx", ".xlsx", ".csv", ".png", ".jpg", ".tiff"]));
    expect(UPLOAD_ACCEPT).not.toContain(".zip");
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
