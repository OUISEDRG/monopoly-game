---
name: cleanup-archive-coordinator
description: Clean and archive project files at the end of every completed task. This skill is mandatory before final handoff, completion claims, commits, or publishing the next-AI task in this repository. It removes verified temporary artifacts, places durable outputs in the correct project directories, records cleanup evidence, and protects source files, user changes, and unknown files from accidental deletion.
---

# Cleanup And Archive Coordinator

Use this skill after implementation and verification are complete, but before the final handoff report or completion response.

The goal is to leave a workspace that is understandable to the next AI: no known temporary artifacts, no final deliverables stranded in temporary locations, and no unexplained files silently deleted.

## Project locations

- Specifications: `docs/superpowers/specs/`
- Implementation plans: `docs/superpowers/plans/`
- Change logs: `docs/superpowers/changelogs/`
- Workflow documents: `docs/superpowers/workflow/`
- Cleanup archive records: `docs/superpowers/archives/`
- Current handoff report: `docs/superpowers/交接记录/`
- Archive record template: `references/archive-record-template.md`

Resolve all paths from the repository root.

## 1. Mandatory trigger

Run this workflow whenever a task reaches a terminal state:

- feature or bug fix completed;
- review completed;
- tests or browser acceptance completed;
- documentation or planning task completed;
- work is about to be committed, handed off, or reported as complete.

Do not claim a task is complete until this workflow has either passed or reported a concrete blocker.

## 2. Establish the cleanup boundary

Before deleting or moving anything:

1. Confirm the repository root.
2. Capture `git status --short`.
3. List files created or modified during the current task.
4. Separate current-task files from pre-existing dirty-worktree files.
5. Resolve every deletion or move target to an absolute path and confirm it remains inside the repository.
6. Treat files with uncertain ownership or purpose as protected.

Never use broad destructive patterns against the repository root.

## 3. Classify files

Place each relevant file into exactly one class.

### A. Durable project files

Keep these in their established locations:

- source code and configuration;
- automated tests and fixtures;
- approved specifications and plans;
- change logs, workflow documents, and current rules;
- assets required by the application;
- the newest verified handoff report.

Do not move durable files merely to make the root directory look smaller.

### B. Final task artifacts needing archive placement

Move or write durable task records into the matching directory:

- design decisions → `docs/superpowers/specs/`;
- implementation instructions → `docs/superpowers/plans/`;
- completed behavior summaries → `docs/superpowers/changelogs/`;
- collaboration procedures → `docs/superpowers/workflow/`;
- cleanup evidence → `docs/superpowers/archives/`.

Use timestamped filenames when a same-purpose file could be replaced by a later task.

### C. Verified temporary or generated artifacts

Delete only after confirming they are reproducible and not required by the application:

- `__pycache__/` and `*.pyc`;
- extracted JavaScript syntax-check files;
- temporary browser screenshots not requested as deliverables;
- test scratch files created by the current task;
- editor backups such as `*.tmp`, `*.temp`, `*.bak`, `*.orig`, and `*~`;
- transient logs created solely for current verification;
- empty task directories.

Do not delete generated artifacts that are intentionally versioned or used at runtime.

### D. Protected or unknown files

Do not delete or move:

- user-created files;
- pre-existing uncommitted changes;
- files whose ownership cannot be established;
- credentials, local configuration, or data files;
- source, tests, documentation, and assets not explicitly superseded;
- anything outside the repository.

Record these files as preserved when they appear relevant to cleanup.

## 4. Archive record

For every completed task, create one cleanup record:

```text
docs/superpowers/archives/YYYY-MM-DD-HHMM-{AI名称}-清理归档记录.md
```

Use `references/archive-record-template.md`.

The record must include:

- task name and completion state;
- files kept and their final locations;
- files moved or archived;
- files deleted and why deletion was safe;
- protected files intentionally preserved;
- verification commands and results;
- final `git status --short` summary;
- unresolved clutter or cleanup blockers.

If no files were deleted or moved, still create the record and state that the workspace was inspected and no safe cleanup was necessary.

## 5. Cleanup execution order

Use this order so cleanup never destroys the only useful copy:

1. Put final artifacts in their durable destinations.
2. Confirm each destination exists and is readable.
3. Create the cleanup archive record.
4. Delete verified temporary artifacts.
5. Remove empty temporary directories.
6. Run the verification checks.
7. Update the archive record with exact results.
8. Only then proceed to the handoff report.

When moving or recursively deleting on Windows, verify resolved absolute paths are inside the intended repository directory and use native PowerShell cmdlets with `-LiteralPath`.

## 6. Verification

Always run:

```powershell
git status --short
git diff --check
```

Also run the task's relevant automated tests after cleanup when deleted or moved files could affect execution.

Confirm:

- no required source or test file disappeared;
- all final artifacts are readable from their documented paths;
- known temporary artifacts from the task are gone;
- remaining untracked files are intentional or documented;
- the cleanup record accurately matches the filesystem.

## 7. Integration with handoff

The `ai-handoff-coordinator` workflow must run this skill before creating its final handoff report.

The handoff report must reference the cleanup archive record and state:

- cleanup passed or was blocked;
- which temporary artifacts were removed;
- which files were archived;
- which dirty-worktree files were preserved.

Do not publish the next-AI task while cleanup remains unexplained.

## 8. Completion checklist

Before declaring cleanup complete, confirm:

- The repository boundary was verified.
- Current-task files were distinguished from pre-existing changes.
- Final artifacts are in durable project locations.
- Temporary files were deleted only with evidence that they were reproducible.
- Unknown and user-owned files were preserved.
- A timestamped cleanup archive record was created.
- `git status --short` and `git diff --check` were run.
- Remaining clutter and skipped cleanup were documented.
- The final handoff report references the cleanup record.

