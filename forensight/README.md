# ForenSight

ForenSight is a local-first forensic investigation support prototype for organizing case records, private evidence files, handling history, investigator-entered evidence relationships, approximate scene markers, and case-record PDFs. It distinguishes stored investigator records from software screening prompts. It does not make investigative conclusions.

This is a prototype, not a validated or production-ready law-enforcement system. Do not use it as the sole record of evidence or to replace approved agency procedures.

## Features

- Investigator registration, login/logout, password hashing, session cookies, CSRF protection, and case-assignment authorization.
- Case creation, search/filter, selected-case metadata and status editing, API/UI pagination, archive-safe data relationships, and database-backed overview statistics.
- Private JPG/JPEG, PNG, WebP, PDF, and UTF-8 text uploads with content checks, a 20 MB upload limit, a 20-million-pixel image limit, exclusive generated storage names, SHA-256 hashes, integrity rechecks, and authenticated no-store previews/downloads.
- Case tasks with due dates and completion tracking. Tasks are configurable examples and are not a compliance determination.
- TraceGuard handling events and transparent documentation rules for absent collection records, missing timestamps, transfers without recipients, missing packaging notes, timestamp regressions, and custodian mismatches.
- EvidenceLink case-scoped relationships, NetworkX graph data, manual relationship review, and explicit evidence-ID reference screening.
- Three.js manual room scene with approximate evidence positions, camera rotation/zoom/pan, labels, and persisted markers.
- Pillow image dimensions/format metadata, stored as an unreviewed analysis record. No object detector is included.
- Multi-page PDF reports generated from persisted case data, with evidence hashes, tasks, relationships, handling history, the same screening rules as TraceGuard, and analysis review status.
- Audit records for case/evidence/task/handling/relationship/scene/report actions. The database audit log is mutable and is not tamper-proof.

## Technology and architecture

- Python 3.11+ and Flask.
- Flask-SQLAlchemy and SQLite for the prototype database.
- Flask-Login and Flask-WTF CSRF protection.
- Pillow for file-content validation and image metadata.
- NetworkX for graph construction.
- ReportLab for PDF reports.
- Vanilla HTML, CSS, and JavaScript with Three.js loaded as a browser module for the manual scene.

`app.py` creates the Flask app and registers blueprints. `models/` defines persisted records, `routes/` handles API/auth/access checks, `services/` contains report generation, `templates/` and `static/` provide the workstation UI, and `tests/` uses isolated SQLite databases and temporary files.

The app uses `db.create_all()` only through the explicit `flask init-db` command. It never resets an existing database. `init-db` creates missing tables; it is not a migration tool. This prototype does not include schema migration files; back up the database before schema changes and plan a migration workflow before multi-version use.

## Windows setup

From PowerShell in the project directory:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Generate a secret and place it in `.env` as `SECRET_KEY=<generated-value>`. For example, generate one with:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

The app uses a random process-local key when `SECRET_KEY` is unset. Sessions will not survive a server restart in that mode. Set a stable secret in `.env` for normal local use. Never commit `.env`.

Initialize the database and run the development server (the server uses port 5000):

```powershell
python -m flask --app app init-db
python app.py
```

Open <http://127.0.0.1:5000>. The Flask development server is for local development only. Set `COOKIE_SECURE=1` only when serving over HTTPS.

To create an administrator without a hard-coded password:

```powershell
python -m flask --app app create-admin
```

The command prompts for a username, email, and password. Run `init-db` first. There is no default administrator. Regular self-registration creates an Investigator account. Administrators can assign account roles and deactivate accounts in the User Access view; the last active administrator cannot be disabled or demoted.

To add fictional demo records, first ensure the database is initialized and an Investigator or Administrator account exists. Set `ALLOW_DEMO_DATA=1` in `.env`, then run `python -m flask --app app seed-demo --username <your-username> --confirm-fictional-data`. The command refuses to overwrite the reserved demo case numbers. Demo artifacts are synthetic UTF-8 text files, marked fictional, and any analysis row is explicitly simulated. To remove only the reserved demo records and their private files, run `python -m flask --app app remove-demo --confirm-fictional-data-removal`; review any customized demo case records before using this destructive command.

## Tests

```powershell
python -m pytest -q
```

Tests create temporary SQLite databases and synthetic image bytes; they do not use real evidence. The test suite covers password hashing/session behavior, CSRF and JSON error handling, assigned-case isolation, upload validation and image pixel limits, integrity mismatch detection, task and handling workflows, duplicate relationship graph edges, scene-marker persistence and coordinate validation, identifier screening, reviewer relationship approval, fictional demo lifecycle, and private PDF generation/download.

## API overview

All state-changing API requests require the CSRF token rendered in the application page. The JavaScript client sends it in `X-CSRFToken`.

- Auth: `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`.
- Administrator access: `GET /api/admin/users`, `PATCH /api/admin/users/<id>/role` (administrator only).
- Dashboard: `GET /api/dashboard/stats`.
- Cases: `GET/POST /api/cases`, `GET/PUT /api/cases/<id>`, `PATCH /api/cases/<id>/status`.
- Evidence: `GET /api/cases/<id>/evidence`, `POST /api/cases/<id>/evidence`, `GET/PUT /api/evidence/<id>`, `POST /api/evidence/<id>/verify-integrity`, authenticated `/download` and `/preview` endpoints.
- Tasks: `GET/POST /api/cases/<id>/tasks`, `PATCH /api/tasks/<id>`.
- TraceGuard: `GET/POST /api/evidence/<id>/handling`, `GET /api/evidence/<id>/risk-checks`, `PATCH /api/handling/<id>/review`.
- EvidenceLink: `GET/POST /api/cases/<id>/relationships`, `PATCH /api/relationships/<id>`, `GET /api/cases/<id>/evidence-graph`, `POST /api/cases/<id>/analyze-report`.
- SceneReplay: `GET/POST /api/cases/<id>/scene-markers`, `PUT/DELETE /api/scene-markers/<id>`, `POST /api/cases/<id>/reconstruction`.
- Image metadata: `POST /api/evidence/<id>/analyze`, `GET /api/evidence/<id>/analysis`, `PATCH /api/analysis/<id>/review`.
- Reports: `GET/POST /api/cases/<id>/reports`, `GET /api/reports/<id>/download`.
- Case audit history: `GET /api/cases/<id>/audit-log`.

Unauthorized case access is returned as 404 so case existence is not disclosed. The browser only offers records returned for the signed-in user; server-side checks remain authoritative.

## Evidence storage and integrity

Uploads are stored under `uploads/`, outside Flask's public static directory, with UUID-based names. The database records the submitted safe filename, MIME type, size, and SHA-256 hash of the received bytes. Image previews use the original bytes without modifying them. Reverification compares the current stored bytes with the upload hash. A mismatch is an integrity discrepancy requiring investigation; it does not independently establish when, how, or why a change occurred.

The prototype does not provide write-once storage, external timestamping, signed audit records, backup/retention controls, malware scanning, or forensic acquisition tooling. Protect the database, upload directory, backups, host, and access credentials as sensitive data.

## AI, NLP, and reconstruction limits

- No external AI provider is configured, and no object-detection model is bundled. The UI/API explicitly report that object detection is unavailable and do not invent detections.
- Image analysis currently records Pillow image dimensions, format, and mode only. These are metadata, not forensic interpretations.
- spaCy and a language model are not installed. EvidenceLink checks explicit `EV-...` identifier patterns only; it does not extract people, dates, places, organizations, or infer relationships. Unknown evidence identifiers produce rule-tagged review prompts.
- Three.js displays a manually configured room and approximate, user-entered coordinates. No measured scene, photogrammetry, or COLMAP reconstruction is claimed. The reconstruction endpoint returns unavailable rather than generating fake output.
- Add a compatible model, versioned adapter, evaluation set, review workflow, and validation appropriate to the intended use before claiming any AI capability.

## Security and production considerations

This prototype includes password hashing, CSRF validation, private authenticated no-store downloads, JSON API authentication/error responses, server-side case scoping, safe internal filenames, exclusive file creation, content-based type checks for supported file formats, upload and image-pixel limits, finite scene-coordinate checks, and environment-based configuration. It has not undergone security testing or forensic validation. Before any operational use, add and review rate limiting, MFA, hardened deployment/session policy, database migrations, durable backups, encrypted storage and transport, immutable or externally verifiable audit controls, monitoring, retention policy, malware scanning, dependency review, jurisdiction-specific procedures, and independent security/privacy review.

Never commit uploaded evidence, case databases, `.env`, passwords, or secret keys. Fictional demonstration data is not seeded automatically.

## Troubleshooting

- `python` is not found on Windows: use `py -3.11` or activate the virtual environment before running commands.
- Login or form requests return 400: load the application page again so its CSRF token is current; ensure cookies are enabled.
- Evidence previews or downloads return 404: verify the private upload path still exists and that the signed-in user is assigned to the case (or is an administrator).
- The 3D viewer reports unavailable: check browser WebGL support and network access to the pinned Three.js CDN module. Saved marker records remain available.
- The case register shows Previous/Next controls when more than one page of cases exists. Search or status changes restart at page one.
- SQLite schema errors after changing model definitions: `init-db` creates missing tables but does not migrate existing ones. Back up the DB and apply an explicit migration; do not delete the database containing case records.
- Reports are not operational findings: check source records and have an authorized investigator review the generated document.