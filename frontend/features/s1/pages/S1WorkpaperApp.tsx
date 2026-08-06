"use client";

import { useEffect, useState } from "react";

import {
  listWorkspaceEvidence,
  processDocument,
  submitFieldReview,
  uploadDocument,
  userFacingApiError,
} from "../api/s1Backend";
import { ExtractionReview } from "../components/ExtractionReview";
import {
  defaultWorkspaceState,
  EvidenceWorkspace,
  type EvidenceWorkspaceState,
} from "../components/EvidenceWorkspace";
import { S1Chrome } from "../components/S1Chrome";
import { engagementConfig } from "../fixtures/engagementConfig";
import { sixDocumentEvidence, supportiveEvidence } from "../fixtures/evidence/sixDocuments";
import { extractedFields } from "../fixtures/extraction/fields";
import type { ContainerState, EvidenceItem, ExtractedField } from "../types";
import type { AuditIntent } from "../utils/auditIntent";

type ActiveView =
  | { name: "evidence" }
  | { name: "extraction"; documentId: string };

export function S1WorkpaperApp() {
  const dataMode = process.env.NEXT_PUBLIC_S1_DATA_MODE === "fixture" ? "fixture" : "backend";
  const [activeView, setActiveView] = useState<ActiveView>({ name: "evidence" });
  const [auditIntents, setAuditIntents] = useState<AuditIntent[]>([]);
  const [demoState, setDemoState] = useState<ContainerState>(dataMode === "backend" ? "loading" : "populated");
  const [workspaceState, setWorkspaceState] =
    useState<EvidenceWorkspaceState>(defaultWorkspaceState);
  const [evidenceItems, setEvidenceItems] = useState<EvidenceItem[]>(sixDocumentEvidence);
  const [fieldItems, setFieldItems] = useState<ExtractedField[]>(extractedFields);
  const [isUploading, setIsUploading] = useState(false);
  const [processingDocumentIds, setProcessingDocumentIds] = useState<string[]>([]);
  const [backendError, setBackendError] = useState<string | null>(null);

  useEffect(() => {
    if (activeView.name === "evidence") {
      window.requestAnimationFrame(() => window.scrollTo(0, workspaceState.scrollTop));
    }
  }, [activeView.name, workspaceState.scrollTop]);

  useEffect(() => {
    if (dataMode !== "backend") return;
    void refreshBackendWorkspace();
  }, [dataMode]);

  async function refreshBackendWorkspace(nextContainerState?: ContainerState) {
    setBackendError(null);
    try {
      const workspace = await listWorkspaceEvidence(engagementConfig.engagementId);
      setEvidenceItems(workspace.evidence);
      setFieldItems(workspace.fields);
      setDemoState(nextContainerState ?? (workspace.evidence.length === 0 ? "empty_nothing_yet" : "populated"));
    } catch (error) {
      setBackendError(error instanceof Error ? error.message : "Could not reach the backend API.");
      setDemoState("error_degraded");
    }
  }

  function addAuditIntent(intent: AuditIntent) {
    setAuditIntents((current) => [...current, intent]);
  }

  function openExtraction(documentId: string, scrollTop: number) {
    setWorkspaceState((current) => ({ ...current, scrollTop }));
    setActiveView({ name: "extraction", documentId });
  }

  async function handleUploadFiles(files: FileList) {
    if (dataMode !== "backend") return;
    setIsUploading(true);
    setBackendError(null);
    try {
      for (const file of Array.from(files)) {
        const document = await uploadDocument(engagementConfig.engagementId, file);
        setProcessingDocumentIds((current) => [...current, document.document_id]);
        await processDocument(document.document_id);
        setProcessingDocumentIds((current) => current.filter((id) => id !== document.document_id));
      }
      await refreshBackendWorkspace("populated");
    } catch (error) {
      setBackendError(userFacingApiError(error));
      setProcessingDocumentIds([]);
      await refreshBackendWorkspace();
    } finally {
      setIsUploading(false);
    }
  }

  async function handleProcessDocument(documentId: string) {
    if (dataMode !== "backend") return;
    setBackendError(null);
    setProcessingDocumentIds((current) => [...new Set([...current, documentId])]);
    try {
      await processDocument(documentId);
      await refreshBackendWorkspace("populated");
    } catch (error) {
      setBackendError(userFacingApiError(error));
      await refreshBackendWorkspace();
    } finally {
      setProcessingDocumentIds((current) => current.filter((id) => id !== documentId));
    }
  }

  return (
    <main className="s1-app">
      <S1Chrome engagement={engagementConfig} currentTab={activeView.name === "evidence" ? "evidence" : "extraction"}>
        {activeView.name === "evidence" ? (
          <EvidenceWorkspace
            engagement={engagementConfig}
            evidence={evidenceItems}
            supportive={supportiveEvidence}
            auditIntents={auditIntents}
            demoState={demoState}
            workspaceState={workspaceState}
            onAuditIntent={addAuditIntent}
            onDemoState={setDemoState}
            onWorkspaceState={setWorkspaceState}
            onOpenExtraction={openExtraction}
            onUploadFiles={handleUploadFiles}
            onProcessDocument={handleProcessDocument}
            isUploading={isUploading}
            processingDocumentIds={processingDocumentIds}
            backendError={backendError}
            workspaceWritesEnabled={dataMode !== "backend"}
            showSessionAuditIntents={dataMode !== "backend"}
          />
        ) : (
          <ExtractionReview
            documents={evidenceItems}
            fields={fieldItems}
            initialDocumentId={activeView.documentId}
            auditIntents={auditIntents}
            onAuditIntent={addAuditIntent}
            onPersistReview={dataMode === "backend" ? submitFieldReview : undefined}
            showSessionAuditIntents={dataMode !== "backend"}
            onBack={() => setActiveView({ name: "evidence" })}
          />
        )}
      </S1Chrome>
    </main>
  );
}
