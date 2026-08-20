---
name: doc-fulfil
description: Raise a document request for a verified customer. Call request_documents. Do not email attachments from the mouth or invent a download link.
allowed-tools:
  - request_documents
  - get_customer_context
metadata:
  version: 1.0.0
  data_class:
    - pii
  eval_suite: skill.doc-fulfil
  mouth:
    - internal
    - whatsapp
    - voice
---

# Document fulfil

The CRM generates the artefact. The mouth only raises the request.

Allowed types include statement, no-dues, interest certificate, foreclosure letter, loan schedule, payment receipt, KYC letter.

Identity must already be verified. Do not read a vault URL or a fake portal path.
