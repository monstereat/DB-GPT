# Report template governance

## Goal

Replace runtime dependence on the checked-in report-template JSON with a locally persisted, versioned template catalog that requires a second admin to approve new templates before they can be used for exports.

## Scope

- Seed a local SQLite release store from `report_templates.json` so current behavior remains available on first startup.
- Allow identified admins to submit versioned templates and another admin to approve or reject them.
- Validate role, metric, definition-field, and result-field allowlists before persistence and publication.
- Use only published templates for synchronous and asynchronous report execution; pin a published template snapshot and catalog version into queued tasks.
- Keep an append-only audit trail for submission, review, and self-review denial.
- Do not change enterprise metadata DB schemas, production storage, encryption-key operations, or multi-instance task storage.

## Acceptance criteria

- Initial local startup seeds the three existing templates as published with a stable content hash.
- Unknown roles, metrics, fields, duplicate template IDs, malformed IDs, and granting a role outside a metric's export allowlist are rejected.
- Only admin users can submit/review; submitters cannot approve or reject their own template.
- Only approved template releases appear in the runtime catalog; rejection has no runtime effect.
- Export/task requests capture an immutable published template snapshot. Later releases do not change already queued task output.
- API/store and existing Text-to-SQL regressions pass; roadmap records local-only limits.
