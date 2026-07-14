# S1 Contracts

## Contract boundaries

S1 defines the boundary between document identification, extraction planning, parser output normalization, and early-stage issue recording.

- Vocabulary Library: canonical document types and known variants used for document identification.
- Regulatory Schema: required fields and citations needed for assurance outcomes.
- Extraction Configuration: extraction instructions for how values are pulled and normalized.
- Verification Rules: checks that determine whether extracted values are valid.
- GapRecordV0: stage-specific failure or issue record.
- GapTicket: later consolidated S3 assurance-facing finding.

## Why Document does not require document_type

Document is upload metadata. Classification is produced after parsing and inspection, so the authoritative type is held in document_classification_result. The document_type field on Document remains optional for legacy or provisional use.

## Classification linkage

document_classification_result links each document to a primary canonical type and candidate matches from the Vocabulary Library.

## Parser to extraction flow

parser_output is parser/tool agnostic normalized output. extraction_candidate values are generated downstream from parser_output plus extraction_config rules.

## GapRecordV0 vs GapTicket

gap_record_v0 captures stage-local extraction or validation issues. gap_ticket is a later, consolidated assurance-facing artifact and should not be conflated with S1 stage records.
