---
name: ai-handoff-coordinator
description: Use when Codex, Trae, or another AI starts, reviews, completes, or hands off any coding, debugging, testing, planning, documentation, or project-management task in this repository.
---

# AI Handoff Coordinator

Use this workflow for every substantive task in this project. The handoff report is a map, not proof: verify important claims against Git, code, tests, and the running application.

## 0. Fixed role constitution

Roles in this project are fixed by the user. They do not rotate and must not be inferred from task wording.

- **Codex is the project brain and sole coordinator/reviewer.** Codex reviews evidence, makes architecture and priority decisions, maintains plans and governance documents, and issues one bounded task to the executor.
- **Trae and every non-Codex AI are executors.** An executor implements only the task packet issued by Codex, verifies and cleans its work, and returns the result to Codex for review.
- Only an explicit user instruction may temporarily override these identities. No AI-authored report may change them.

Hard prohibitions:

- An executor must never label Codex as an executor, implementation agent, or subordinate.
- An executor must never assign implementation work to Codex.
- An executor must not choose, authorize, or start the next numbered task.
- An executor hands completed work back to **Codex for review**. It does not issue Codex a "next task".
- Codex normally does not implement feature code. It may edit plans, skills, task packets, reports, and other coordination artifacts, or act only when the user explicitly overrides the division of labor.

Every report must begin with:

```text
Project brain: Codex
Current executor: {AI name, or "none" while Codex reviews}
Report author role: coordinator/reviewer OR executor
Role authority: fixed by the user; an AI may not reassign it
```

## Project locations

- Handoff reports: `docs/superpowers/交接记录/`
- Handoff template: `references/handoff-template.md`
- Design documents: `docs/superpowers/specs/`
- Implementation plans: `docs/superpowers/plans/`
- Change logs: `docs/superpowers/changelogs/`

Resolve all relative paths from the repository root.

## 1. Start-of-work protocol

Before planning or editing:

1. Confirm the repository root and inspect `git status --short`.
2. List handoff reports and select the newest report:
   - Prefer the timestamp encoded in filenames.
   - Fall back to file modification time for legacy reports.
3. Read the newest report completely.
4. Read every specification, plan, issue, or change log directly referenced by that report when relevant to the assigned task.
5. Compare the report with reality:
   - Verify the current branch and latest commit.
   - Confirm listed files and functions exist.
   - Run or inspect the claimed tests when their result affects the next decision.
   - Treat discrepancies as findings; do not silently copy incorrect metadata.
6. Preserve existing user and agent changes. Never discard, reset, or overwrite unrelated dirty-worktree changes.
7. State a short intake summary before substantial work:
   - What the previous AI completed.
   - What remains unverified or unfinished.
   - What this turn will do.
   - Which files are expected to change.

If no handoff report exists, create an initial report from the current Git and project state before beginning risky work.

## 2. Apply the fixed working role

### Coordinator/reviewer role

Codex always uses this role unless the user explicitly overrides it for the current turn.

- Inspect the implementation and independently verify claims.
- Lead with concrete defects, risks, and missing evidence.
- Do not implement the next feature unless the user explicitly assigns implementation to this AI.
- Publish a bounded task packet that the executor can follow without guessing.

### Executor role

Trae and every non-Codex AI always use this role unless the user explicitly overrides it.

- Follow the latest approved specification and task packet.
- Keep edits inside the stated scope unless a necessary dependency is discovered.
- Add tests proportional to the behavioral risk.
- Complete implementation and verification before writing the handoff.
- Return the completed result to Codex for review.
- Do not issue or begin the next numbered implementation task.

Ambiguity never changes the fixed roles. If an executor has no valid Codex task packet, it must request one instead of acting as coordinator.

## 3. Work protocol

During the task:

1. Convert the assignment into explicit acceptance criteria.
2. Inspect nearby implementation and tests before editing.
3. Keep the user informed of meaningful discoveries.
4. Use focused changes that follow existing project conventions.
5. Record deviations from the previous plan and explain why they were necessary.
6. Do not mark work complete based only on code inspection.

When a previous AI's report conflicts with the repository, use the repository as evidence and document the discrepancy.

## 4. Verification protocol

Run the narrowest relevant checks first, then broader regression checks when the change affects shared game flow.

For this project, the normal verification set is:

```powershell
node --test tests/*.mjs
python -m py_compile monopoly_app.py
```

Also extract the inline script from `monopoly.html` and run `node --check` when JavaScript changed. Run `git diff --check` before handoff. For user-facing changes, verify the affected flow in a browser at desktop and mobile widths when practical.

Never claim a check passed unless it was run during the current work session. Record skipped checks and the reason.

## 5. End-of-work handoff

Before creating the final handoff report, run `.agents/skills/cleanup-archive-coordinator/SKILL.md`. Do not proceed until its cleanup record has been created and verified, or until a concrete cleanup blocker has been documented.

Create a new report without overwriting the previous report during report generation.

Use this filename:

```text
docs/superpowers/交接记录/YYYY-MM-DD-HHMM-{AI名称}-交接报告.md
```

Copy the structure from `references/handoff-template.md`. Populate it with observed facts rather than optimistic placeholders.

The report must include:

- The fixed role declaration from section 0.
- Starting handoff report and discrepancies found.
- User request and working role.
- Files changed, with concise behavioral descriptions.
- Verification commands and exact results.
- Known risks, skipped checks, and dirty-worktree notes.
- Current Git branch and commit.
- The cleanup archive record path and cleanup result.
- A Codex report: one bounded implementation task for the executor.
- An executor report: a review-return packet addressed to Codex, with no next feature assignment.

Do not report "0 issues" when browser testing, integration testing, or another relevant verification layer was skipped. Say exactly what remains unverified.

After the new report has been written and checked:

1. Confirm the new report exists, is readable, and contains either the Codex task packet or the executor's review-return packet.
2. Delete every older handoff report from `docs/superpowers/交接记录/`, leaving only the new report.
3. Never delete the previous report before the replacement report is complete and verified.
4. If report creation or verification fails, keep the previous report and treat cleanup as incomplete.
5. Preserve older reports only when the user explicitly asks for an archive or history.

This cleanup rule prevents agents from selecting stale instructions and keeps the handoff directory focused on the current project state.

## 6. Publish the correct handoff

### Codex report

Only Codex publishes the next implementation task. The recipient must be an executor, never Codex.

After writing the report, repeat the task packet in the final response under `下一位 AI 任务`.

Use this format:

```markdown
### 下一位 AI 任务
- 项目大脑：Codex
- 任务接收者：执行者（Trae 或用户指定的其他执行 AI）
- 目标：一句话描述唯一主要目标
- 开始前必读：最新交接报告及相关规范路径
- 修改范围：允许修改的文件或模块
- 验收标准：可观察、可测试的完成条件
- 必跑检查：具体命令或浏览器场景
- 禁止事项：不得覆盖的改动、不得改变的规则
- 完成后：先新建并核验交接报告，再删除所有旧交接报告，只保留最新报告，并发布下一任务
```

Issue one primary task per packet. If several independent tasks exist, prioritize one and list the rest as backlog rather than asking the next AI to change unrelated systems simultaneously.

### Executor report

An executor must not publish a next implementation task. It must use:

```markdown
### 交回 Codex 审查
- 项目大脑：Codex
- 本轮执行者：{AI name}
- 已完成任务：当前 Codex 任务包名称
- 请求 Codex：独立验收本轮成果并决定下一任务
- 验证证据：实际运行的命令和结果
- 未解决事项：风险、警告、跳过的检查
- 禁止越权声明：未启动、未授权、未规划下一编号任务，未向 Codex 分配实现工作
```

An executor may list backlog for context, but must not express it as an instruction, authorization, or active task.

## 7. Completion checklist

Before ending the turn, confirm:

- Latest prior handoff was read.
- Git and code were checked against it.
- Existing unrelated changes were preserved.
- Assigned work or review was completed.
- Relevant verification was run or explicitly marked as skipped.
- The cleanup and archive skill was run and its record was verified.
- A new timestamped handoff report was written.
- The new report was checked before cleanup.
- All older handoff reports were deleted unless the user explicitly requested an archive.
- A Codex report includes the executor task packet in both the report and final response; an executor report includes the review-return packet.
- The report explicitly names Codex as project brain.
- An executor report returns work to Codex and does not assign Codex implementation work.
