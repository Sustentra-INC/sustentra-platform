import { EXACT_COPY } from "../constants/copy";
import { expectedDocuments } from "../fixtures/states/empty";
import type { ContainerState } from "../types";

interface ContainerStateSurfaceProps {
  state: ContainerState;
  totalDocuments?: number;
  onClearFilter?: () => void;
  onUploadFiles?: (files: FileList) => void;
  isUploading?: boolean;
  children?: React.ReactNode;
}

export function ContainerStateSurface({
  state,
  totalDocuments = 0,
  onClearFilter,
  onUploadFiles,
  isUploading = false,
  children,
}: ContainerStateSurfaceProps) {
  if (state === "populated") {
    return <>{children}</>;
  }

  if (state === "empty_nothing_yet") {
    return (
      <section className="s1-content">
        <div className="s1-band s1-upload">
          <div>
            <h2>{EXACT_COPY.noEvidenceYet}</h2>
            <p className="s1-muted">Expected evidence</p>
            <ul>
              {expectedDocuments.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
          <label className="s1-button">
            {isUploading ? "Uploading" : "Choose files"}
            <input
              className="s1-file-input"
              type="file"
              multiple
              onChange={(event) => {
                if (event.target.files && event.target.files.length > 0) {
                  onUploadFiles?.(event.target.files);
                  event.target.value = "";
                }
              }}
            />
          </label>
        </div>
      </section>
    );
  }

  if (state === "empty_filtered") {
    return (
      <section className="s1-panel s1-empty">
        <h2>{EXACT_COPY.noDocumentsMatch}</h2>
        <p>{totalDocuments} documents are in this engagement.</p>
        <button className="s1-button" type="button" onClick={onClearFilter}>
          Clear filter
        </button>
      </section>
    );
  }

  if (state === "loading") {
    return (
      <div className="s1-table-wrap" aria-label="Loading evidence">
        <table className="s1-table">
          <tbody>
            {Array.from({ length: 6 }).map((_, index) => (
              <tr key={index}>
                <td colSpan={9} style={{ height: "var(--row-height-compact)" }}>
                  <span className="s1-muted">Loading row</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  if (state === "error_degraded") {
    return (
      <section className="s1-panel">
        <h2>Evidence table degraded</h2>
        <p>Document rows are still available. Relationship metadata is not available.</p>
        {children}
      </section>
    );
  }

  return (
    <section className="s1-panel">
      <h3>Completeness</h3>
      <p>{EXACT_COPY.dependencyBlocked}</p>
    </section>
  );
}
