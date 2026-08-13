---
name: skill-creator
description: Create or refine reusable global skills in ~/.lulu/skills. Use when a task pattern, workflow correction, tool procedure, or reusable technique should be captured as a skill instead of as memory or a one-off fix.
---

# Skill Creator

Use this skill to turn repeated work into a reusable global skill.

## Scope

- Capture procedural knowledge, not user facts.
- Target class-level capabilities, not one-off task artifacts.
- Keep the output lean and directly usable by `skill_lookup list`, `skill_lookup read`, and `skill_manage`.

## Workflow

1. Inspect existing skills with `skill_lookup list`.
2. Read only the relevant skill with `skill_lookup read`.
3. Decide whether to:
   - create a new skill,
   - patch an existing skill,
   - add a support file under `references/`, `templates/`, or `scripts/`.
4. Write the smallest useful change with `skill_manage`:
   - `create` with `name` and `description` to initialize a stable `SKILL.md` template.
   - `patch` to replace one template section or one precise existing passage.
   - `write_file` for supporting material
   - `remove_file` for removing supporting material
   - `update` only when patch cannot express the change cleanly or the whole `SKILL.md` must be restructured.
5. Validate the result by reading it back with `skill_lookup read` or `skill_lookup list`.

## Creation Rules

- Use `skill_manage create` first. Do not pass full body content to `create`.
- After creation, use `skill_lookup read` to inspect the generated template.
- Fill the generated sections by using `patch` against exact template headings or empty section blocks.
- Prefer one patch per coherent section, such as `## When to use`, `## Core principles`, `## Workflow`, or `## Support files`.
- Use `update` only if patching would be unclear, fragile, or require replacing most of the file.
- Put the essential procedure in `SKILL.md`.
- Move detail, examples, or reusable snippets into support files.
- Prefer concise, imperative steps.
- Keep the skill name stable and capability-focused.
- Do not create a skill for a transient session, a single bug, or a temporary environment issue.

## Refinement Rules

- Read the current skill before editing it.
- Patch the skill that was actually used, if one exists.
- Prefer targeted `patch` edits over full `update`.
- Use `update` only for major restructuring or when exact patch context cannot be made unique.
- Preserve what still works.
- Merge repeated corrections into the workflow or pitfalls section.
- Add support files only when they will be reused.

## Good Triggers

- The same task keeps recurring.
- A workflow correction should be remembered as procedure.
- A tool sequence needs to be repeated reliably.
- A domain-specific method should be available to future turns.

## Bad Triggers

- A single user fact.
- A temporary failure.
- A project-specific instruction that belongs in `AGENTS.md`.
- A task-specific note that will not generalize.

## Output Shape

When creating or updating a skill:

- start from the actual reusable behavior,
- keep the skill body short,
- add support files only if they remove real repetition,
- avoid overfitting to one example.
