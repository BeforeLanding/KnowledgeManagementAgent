# PRD

## Problem and users

Enterprise operational knowledge is scattered across engineering journals, documents, spreadsheets and exported email. Viewers need answers with evidence; curators need safe ingestion and failure recovery; administrators need access control, auditability and measurable release quality.

## V1 outcomes

- Upload PDF, DOCX, XLSX, CSV, TXT, Markdown and EML into a knowledge space.
- Search Chinese and English content using semantic and lexical signals.
- Answer only from accessible evidence and expose file/chunk locators.
- Refuse unsupported questions, preserve source conflicts and ignore instructions embedded in documents.
- Inspect redacted runs and execute a regression suite from the UI.

## Acceptance

Supported digital-document parsing is at least 98%; Recall@5 at least 90%; nDCG@10 at least 85%; citation accuracy at least 95%; groundedness at least 90%; no-answer F1 at least 90%; ACL leakage is zero; retrieval P95 is below one second at the 10,000-document target.

OCR, live mailbox sync, logistics entity extraction, write tools, multi-tenant SaaS, Kubernetes and production SSO are excluded.

