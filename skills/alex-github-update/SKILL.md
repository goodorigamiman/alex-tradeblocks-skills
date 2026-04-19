---
name: alex-github-update
description: 'Publish dev skills to the GitHub marketplace. Audits versions against cache, flags content changes without version bumps, syncs files to the repo with name/version transforms, commits, pushes, and triggers cache update. Config-driven — builds alex_github_update_config.md on first run.

  '
compatibility: Requires git, gh CLI, and access to the GitHub repo configured in alex_github_update_config.md.
metadata:
  author: alex-tradeblocks
  version: '2.2'
---

# Dev GitHub Update

Publish dev skills from the local dev folder to the GitHub marketplace plugin repo. Six steps: load config → **preview plan (awaits user confirm)** → audit versions → sync files → commit & push → update cache.

## Sync model: strict mirror with allowlist (Model A)

The dev folder `Dev-TradeBlocks-Skills/` is the **source of truth**. After Step 2 finishes, the repo at `{repo_path}/` must be a byte-for-byte mirror of the dev folder — with three exceptions ("the allowlist") that are repo-only and never touched by sync:

| Allowlist entry | Reason |
|---|---|
| `.claude-plugin/` | Plugin metadata managed by Steps 2D + 2E (plugin.json, marketplace.json). Never sourced from dev. |
| `.git/` and `.gitignore` | Git metadata. Never sourced from dev. |

Everything else in the repo must trace back to a file in the dev folder. The skill:
- **Copies** dev files into the repo (with prefix/version transforms for skill frontmatter)
- **Deletes** any file or folder in the repo that isn't in the dev folder and isn't on the allowlist

Dev skills use the `{dev_prefix}` (default `dev-`) and publish as `{published_prefix}` (default `alex-`). Top-level dev files like `README.md`, `LICENSE`, `package.json` are copied to the repo root as-is (no rename transform). The `_shared/` folder mirrors to `{repo}/{support_files_dest}/` (default `_shared/`).

---

## Step 0: Load (or Create) Config

Look for `$TB_ROOT/alex_github_update_config.md`.

### If config exists

Parse the YAML frontmatter with a real YAML parser — same pattern as startup:

```python
import re, yaml, pathlib
txt = pathlib.Path('alex_github_update_config.md').read_text()
fm = re.search(r'^---\n(.*?)\n---', txt, re.DOTALL).group(1)
config = yaml.safe_load(fm)
```

If PyYAML is unavailable, install with `pip install pyyaml`. Do NOT use line-by-line regex.

Validate that `repo_path` exists and is a git repo. If not, flag and ask.

### If config does NOT exist (first run)

Detect values by probing, present to user for confirmation, then write the config:

| Key | How to detect |
|---|---|
| `repo_path` | Search common dev directories (`~/Developer/`, `~/Projects/`, `~/repos/`) for a folder containing `.claude-plugin/plugin.json`. If multiple or none found, ask the user for the absolute path. |
| `dev_skills_folder` | Read from `alex_tradeblocks_startup_config.md` if it exists (`dev_skills_folder` key), otherwise glob for `Dev-*Skills*` or `*-dev-skills` in `$TB_ROOT`. |
| `plugin_id` | Read `~/.claude/plugins/installed_plugins.json` — find the plugin whose install path contains the repo name. Format: `{namespace}@{marketplace-name}`. |
| `plugin_namespace` | Extract from `plugin_id` (the part before `@`). Used to locate the cache directory. |
| `dev_prefix` | Default `dev-`. Confirm with user. |
| `published_prefix` | Read the name field of any existing published skill in `{repo_path}/skills/*/SKILL.md` and extract the common prefix. Confirm with user. |
| `support_files_src` | The shared folder inside `{dev_skills_folder}` containing `.default.csv` and `.default.sql` files. Default `_shared`. Stored as a name relative to `{dev_skills_folder}`. |
| `support_files_dest` | The folder name in the repo where shared files land. Default `_shared` (mirrors the dev layout). Verify exists in repo. |
| `plugin_json_path` | `.claude-plugin/plugin.json` (standard location). Verify exists in repo. |
| `marketplace_json_path` | `.claude-plugin/marketplace.json`. Verify exists in repo. |
| `skills_dir` | `skills` (standard location). Verify exists in repo. |
| `exclude_skills` | Ask user if any dev skills should be excluded from publishing. Default empty list. |

Write to `$TB_ROOT/alex_github_update_config.md` using the Config Schema below.

### Config Schema

All values below are **placeholders** — replace with actual paths and names during first-run detection.

```markdown
---
schema_version: 1

# Repo
repo_path: <absolute-path-to-git-repo>           # e.g. /Users/you/Developer/your-skills-repo
skills_dir: skills
plugin_json_path: .claude-plugin/plugin.json
marketplace_json_path: .claude-plugin/marketplace.json

# Dev workspace
dev_skills_folder: <dev-folder-name>              # relative to TB root

# Support files (shipped with plugin but not skills)
support_files_src: _shared                        # relative to dev_skills_folder; contains .default.csv/.sql files + README
support_files_dest: _shared                       # folder name in the repo; default mirrors dev layout

# Naming conventions
dev_prefix: "dev-"                                # prefix on dev skill folder/names
published_prefix: "<your-prefix>-"                # prefix on published skill folder/names
plugin_id: <namespace>@<marketplace-name>         # from installed_plugins.json
plugin_namespace: <namespace>                     # for cache directory lookup

# Exclusions (dev skills that should NOT be published — empty = publish all)
exclude_skills: []
---

# GitHub Update — Local Config

Generated on YYYY-MM-DD. Edit by hand if paths or conventions change.

## Notes

- The repo and dev folder are separate directories. This skill bridges them.
- Cache is keyed by plugin version in plugin.json — bumping is required for cache refresh.
- After push + cache update, user must re-open Claude Code to load new cache.
```

### Updating config

The user edits by hand. The skill detects drift (e.g. repo moved, new exclusions) and prompts — it does not silently overwrite.

---

## Step 0.5: Publish Plan Preview (MUST confirm before proceeding)

**Purpose:** give the user a clean read of exactly which skills will be published this run, which will be skipped, and which excluded skills will be deleted from the repo — BEFORE any audit or sync work runs. This is the gate; everything after it is actual work.

### Procedure

1. Enumerate dev skills: `ls {dev_skills_folder}/{dev_prefix}*/SKILL.md`.
2. Partition by `exclude_skills` (membership match on the full dev-skill folder name, e.g. `dev-entry-filter-pareto`):
   - **Publish set** — dev skills NOT in `exclude_skills`.
   - **Skip set** — dev skills IN `exclude_skills`.
3. For each skill in the Skip set, probe the repo at `{repo_path}/{skills_dir}/{published_prefix}{stem}/`. If the folder exists, mark the skill **"in repo — will be removed"**. Otherwise mark **"not in repo — no-op"**.
4. Render the preview table to the user:

```
Publish plan ({total} dev skills total)

  WILL PUBLISH (N)
    alex-entry-filter-heatmap              → alex-entry-filter-heatmap       (v5.0.0-dev)
    alex-entry-filter-threshold-sweep      → alex-entry-filter-threshold-sweep (v1.2.0-dev)
    alex-entry-filter-build-data           → alex-entry-filter-build-data    (v1.0.0-dev)
    alex-entry-filter-enrich-market-holiday → alex-entry-filter-enrich-market-holiday (v1.0.1-dev)
    alex-create-datelist                   → alex-create-datelist            (v1.5.0-dev)
    alex-normalize-statistics              → alex-normalize-statistics       (v1.0.1-dev)

  WILL SKIP (M — in exclude_skills)
    dev-entry-filter-pareto               [in repo — WILL BE REMOVED from repo]
    alex-entry-filter-threshold-analysis   [in repo — WILL BE REMOVED from repo]
    dev-entry-filter-parallel-coords      [not in repo — no-op]
    dev-entry-filter-time                 [not in repo — no-op]
    dev-entry-filter-time-overlay         [not in repo — no-op]
    alex-github-update                     [not in repo — no-op]
    dev-sync-profiles                     [not in repo — no-op]
    alex-tradeblocks-startup               [not in repo — no-op]
```

5. **Prompt the user:** *"Proceed to audit the {N} publish-set skills? (Y/n) Anything to add or remove from `exclude_skills` before continuing? Edit `alex_github_update_config.md` and re-run if so."*

6. **On `n` or uncertainty: abort cleanly.** Report: *"No changes made. Edit `alex_github_update_config.md` → `exclude_skills`, then re-run."*. Do not touch any files.

7. **On `Y`: record the Publish set and Skip set for the remaining steps** — the audit uses them to tier severity, the sync uses them to drive deletion. Do not re-enumerate from `exclude_skills` later; decisions are fixed at this point.

### What this step does NOT do

- No version checks, no content diffs, no cache lookups. Those belong in Step 1. This step's only job is "here's the plan, confirm before I work."
- No file mutations. The preview is read-only. If the user wants to change exclusions, they edit config and re-invoke — the skill never edits `exclude_skills` on the user's behalf.

---

## Step 1: Version & Content Audit

This step is **severity-tiered by publish status**:

| Status | What runs | How findings are handled |
|---|---|---|
| **Publish set** (not in `exclude_skills`) | Full audit: version+content diff vs cache & repo; dependency/cross-skill reference checks (see below). | **CRITICAL** — FLAG and MISMATCH findings block sync; user must resolve or override. |
| **Skip set** (in `exclude_skills`) | Same version+content checks run, but findings are relabelled. | **WARNING** — reported so the user sees rot, but they do NOT block and require no action. |

The rationale: the user opted the Skip-set skills out for a reason (not ready to publish, in-flux, etc.), so "their version doesn't match cache" or "content changed without a bump" is expected noise, not a problem to act on. The preview in Step 0.5 already confirmed the partition; Step 1 just surfaces issues at the appropriate severity.

### For each dev skill (Publish + Skip sets):

1. Parse dev SKILL.md frontmatter with `yaml.safe_load` → extract `name`, `metadata.version` (or `version`), full file content.
2. Derive the **stem** by stripping `{dev_prefix}` from the name (e.g. `{dev_prefix}my-skill` → `my-skill`).
3. Look for a matching **cache skill**:
   - Glob `~/.claude/plugins/cache/*/{plugin_namespace}/*/skills/{published_prefix}{stem}/SKILL.md`
   - If found, parse its frontmatter for version and read its full content.
4. Look for a matching **repo skill**:
   - Check `{repo_path}/{skills_dir}/{published_prefix}{stem}/SKILL.md`
   - If found, read full content for diff comparison.

### Dependency & cross-skill reference checks (Publish set only, critical)

For each skill in the Publish set, additionally verify:

| Check | Scope | What it catches |
|---|---|---|
| **Referenced shared files exist** | Scan the skill's `*.py` / `*.sql` / SKILL.md for paths like `_shared/foo.default.sql` — every referenced file must exist under `{dev_skills_folder}/{support_files_src}/`. | Prevents shipping a skill that silently breaks because its shared dependency isn't in `_shared/`. |
| **Cross-skill references resolve in-set** | Scan the skill's body for other `{dev_prefix}*` skill names. Every referenced name must either be in the Publish set, or not a dev skill at all. References to Skip-set skills are CRITICAL — they'd break once published (the target wouldn't exist in the marketplace). | Prevents published skills from referencing a skill that was deliberately excluded. |
| **Adjacent helper files present** | If SKILL.md references a sibling `.py` (e.g. `gen_heatmap.py`), confirm the file exists in the dev skill folder. | Prevents ship of a SKILL.md that points to a deleted helper. |

For **Skip set** skills, the same checks run but findings are reported as WARNING (user isn't publishing the skill this round, so a broken reference in it is rot the user has deferred handling).

### Comparison logic for version/content:

**Comparison logic:**

| Dev Version | Cache Version | Content Changed? | Status |
|---|---|---|---|
| X.Y-dev | X.Y (match after strip) | Yes | **FLAG** — version bump needed, cache won't update |
| X.Y-dev | X.Y (match after strip) | No | OK — skip (no changes) |
| X.Y-dev | < X.Y | -- | **READY** — dev is ahead, will publish |
| -- | (no match) | -- | **NEW** — will be added to marketplace |

**Content comparison:** Compare the dev SKILL.md body (everything after the closing `---` of frontmatter) to the repo copy's body. Also compare any `.py`, `.sql`, or other non-SKILL.md files in the dev folder to their repo counterparts. Ignore frontmatter differences (name prefix, [DEV] tag, -dev suffix) since those are expected transforms.

**Output format:**

```
Version & Content Audit:

  Publish set (CRITICAL severity):
    Skill                             Dev Ver   Cache Ver  Changed?  Status        Findings
    alex-entry-filter-heatmap          5.0-dev   4.6        yes       READY         —
    alex-entry-filter-threshold-sweep  1.2-dev   1.0        yes       READY         —
    alex-entry-filter-build-data       1.0-dev   1.0        no        SKIPPED       —
    alex-create-datelist               1.5-dev   1.4        yes       READY         ref to alex-threshold-analysis
                                                                                    (not in publish set)
    ...

  Skip set (WARNING severity — no action required):
    dev-entry-filter-pareto           3.0-dev   3.0        yes       STALE          content diff vs cache
    alex-entry-filter-threshold-analysis 4.0-dev 3.0        yes       STALE          content diff vs cache
    ...

  Summary (publish set): N ready · M new · J unchanged · F flagged · D critical findings
  Summary (skip set):    S total · W warnings (informational only)
```

**If any CRITICAL FLAG or finding exists in the publish set: STOP and prompt the user.** Options:
- Address the flag (e.g. bump version, fix a broken cross-skill reference).
- Add the affected skill to `exclude_skills` if it isn't ready.
- Explicitly override ("continue anyway") — only for genuine judgement calls, not for version-bump oversights.

If the user opts to bump a flagged skill, increment the version in the dev SKILL.md (suggest patch bump), re-read, and re-audit.

**Skip-set WARNINGs never block.** Report them and move on — the user has already opted those skills out of this round.

---

## Step 2: Sync to Repo

For each skill with status READY or NEW:

### 2A. Sync skill files (strict mirror per skill)

For each dev skill:

1. Ensure `{repo_path}/{skills_dir}/{published_prefix}{stem}/` exists.
2. **Sync with delete** from `{dev_skills_folder}/{dev_prefix}{stem}/` to the repo skill folder:
   ```bash
   rsync -a --delete \
     "{dev_skills_folder}/{dev_prefix}{stem}/" \
     "{repo_path}/{skills_dir}/{published_prefix}{stem}/"
   ```
   This copies everything from dev and **deletes any file in the repo skill folder that no longer exists in dev**. Critical for catching retired `.py` helpers, renamed SQL, or removed reference files.
3. **Transform the copied SKILL.md** (in the repo, NOT the dev original):
   - `name:` field — replace `{dev_prefix}` with `{published_prefix}`
   - `description:` field — strip leading `[DEV] ` if present
   - `version:` field — strip trailing `-dev` (e.g. `3.0-dev` → `3.0`)
   - **Body cross-skill references** — replace `{dev_prefix}{stem}` with `{published_prefix}{stem}` for all known dev skill names throughout the entire file (frontmatter + body). Build the replacement map from the full list of dev skills being published in this run. Use whole-word matching (e.g. match `dev-threshold-analysis` but not `dev-threshold-analysis-extra`) to avoid partial replacements. This ensures "Related Skills" sections and inline references point to the published names, not dev names.

### 2B. Clean up stale skill folders (strict mirror at `{skills_dir}/`)

After Step 2A, the repo's `{skills_dir}/` must contain **exactly** the set of published skills mapped from the **Publish set** (Step 0.5). Everything else gets removed.

**Expected set:** for every dev skill in the Publish set (`{dev_prefix}{stem}`), the expected repo folder is `{published_prefix}{stem}`.

**Cleanup (three tiers, different friction):**

1. Glob `{repo_path}/{skills_dir}/*/` → actual set of skill folders.
2. Categorize each folder not in the expected set:

   | Category | Detection | Action |
   |---|---|---|
   | **Excluded skill in repo** | folder is `{published_prefix}{stem}` where `{dev_prefix}{stem}` is in `exclude_skills` | `git rm -rf` silently. Announce in the run summary: *"Removed alex-{stem} from repo (now in exclude_skills)."* |
   | **Dev-prefix leftover** | folder starts with `{dev_prefix}` (a raw dev copy that shouldn't be there) | `git rm -rf` silently. |
   | **Unknown folder** | not matched by either of the above | Report and ask: *"`{repo}/{skills_dir}/{folder}/` is not sourced from any dev skill and is not on the exclusion list. Delete it? (Model A strict mirror deletes by default; answer `keep` to override just this time — but consider whether this skill should be moved into dev or added to `exclude_skills`.)"* |

3. Execute deletions via `git -C {repo_path} rm -rf {skills_dir}/{folder}`.

**Exclusion-driven deletion is the key new behavior:** adding a skill to `exclude_skills` is the official way to retire it from publication. The first run after the addition deletes the corresponding `{published_prefix}{stem}/` folder from the repo and removes its entry from `marketplace.json` (Step 2D's full-rewrite handles the manifest side automatically).

Also remove any stale entries from `marketplace.json` that reference the deleted paths (Step 2D handles this as part of its full rewrite).

### 2C. Sync support files

Copy contents of `$TB_ROOT/{dev_skills_folder}/{support_files_src}/` → `{repo_path}/{support_files_dest}/`, overwriting existing files. This includes shared CSVs, SQL templates, and the README that ship with the plugin. The `support_files_src` path is relative to `{dev_skills_folder}` (e.g. `_shared` → `Dev-TradeBlocks-Skills/_shared/`). Skill-local `.py` modules are NOT copied here — they travel with their individual skill folder in Step 2A.

**Stale-destination cleanup:** if a legacy support-files folder exists in the repo under a different name (e.g. the historical `Alex-TradeBlocks-Skills/` before the 2026-04-16 rename to `_shared/`), flag it:

1. Check `{repo_path}/` for any folder that contains `.default.csv` or `.default.sql` files and is **not** the current `{support_files_dest}`.
2. If found, report: *"Stale support-files folder detected: `{repo}/{old_name}/`. Current target is `{support_files_dest}/`. Delete the stale folder?"*
3. On user confirm: `git -C {repo_path} rm -rf {old_name}`. The deletion is staged; commit happens in Step 3 along with the normal publish.

This keeps the repo layout aligned with the dev folder when the user renames `support_files_dest` in config.

**Sync-with-delete semantics:** within `{support_files_dest}/`, remove any file that exists in the destination but not in the source (the dev `{support_files_src}/`). Use `rsync --delete` or equivalent. This ensures stale `.py` modules or old CSVs that were moved skill-local don't linger in the published folder. Do not touch the destination folder's `.git*` files if any.

### 2D. Update marketplace.json skills array

Read `{repo_path}/{marketplace_json_path}`. The `plugins[0].skills` array must end up as an **exact mirror** of the published-skill folders in `{repo_path}/{skills_dir}/` after Step 2A and any stale-folder cleanup from Step 2B.

Procedure:

1. **Compute the expected set:** glob `{repo_path}/{skills_dir}/*/SKILL.md` after Step 2A+2B. Build the expected skills array as `["./{skills_dir}/{folder_name}" for each folder]`, sorted alphabetically.
2. **Read the current array** from marketplace.json.
3. **Diff the sets:**
   - In expected, not in current → **add**
   - In current, not in expected → **remove** (a skill was deleted from dev or renamed; the entry is now stale)
   - In both → keep
4. **Write the new array** sorted alphabetically back to marketplace.json.

Report the diff:

```
marketplace.json skills array:
  + ./skills/alex-new-skill        (added)
  - ./skills/alex-retired-skill    (removed — no longer in dev)
  12 unchanged
```

Do not duplicate existing entries. The skills array is always fully rewritten from the expected set — never append-only.

### 2E. Bump plugin version

Read current version from `{repo_path}/{plugin_json_path}`. Ask user: *"Current plugin version is X.Y.Z. Bump type? (patch / minor / major)"*

Apply the bump to **all four version records** so they stay in lockstep (the Step 2H audit enforces this):

1. `{repo_path}/{plugin_json_path} → version`
2. `{repo_path}/{marketplace_json_path} → metadata.version`
3. `$TB_ROOT/{dev_skills_folder}/package.json → version` (dev source — Step 2F will copy it to repo)
4. `{repo_path}/package.json → version` (via the Step 2F copy — will inherit from the dev bump above)

Edit #1, #2, and #3 directly. #4 happens automatically when Step 2F syncs dev → repo. **Do not edit `{repo}/package.json` directly** — that would break Model A strict mirror (dev is source of truth).

### 2F. Sync top-level repo files

Copy these files from `$TB_ROOT/{dev_skills_folder}/` to `{repo_path}/`, overwriting:

| Dev source | Repo destination | Required? |
|---|---|---|
| `README.md` | `{repo}/README.md` | Yes — user-facing plugin overview |
| `LICENSE` | `{repo}/LICENSE` | Yes |
| `package.json` | `{repo}/package.json` | Yes — Node metadata for marketplace |

If any of these are missing in dev, flag and ask the user whether to skip sync for that file (one-time override) or stop and add it to dev.

### 2G. Repo-root strict-mirror cleanup (allowlist-gated)

After Step 2F, the **repo root** (top level of `{repo_path}/`) must contain only:

1. Files/folders sourced from dev (copied above + `{skills_dir}/` + `{support_files_dest}/`)
2. Entries on the **allowlist** — hardcoded, not user-configurable:
   - `.claude-plugin/` (managed by Steps 2D + 2E — plugin.json, marketplace.json)
   - `.git/` (git metadata)
   - `.gitignore` (if present)

Procedure:
1. List `{repo_path}/` top-level entries (excluding `.` and `..`).
2. Build the expected set: dev-sourced top-level files + `{skills_dir}/` + `{support_files_dest}/` + allowlist.
3. For each actual entry not in the expected set:
   - Report: *"`{repo}/{entry}` is not on the allowlist and not sourced from dev. Delete? (Model A strict mirror; answer `keep` to override for this run, or add the file to dev if it should persist.)"*
4. On user confirm: `git -C {repo_path} rm -rf {entry}`.

Example: if the repo has a historical `Alex-TradeBlocks-Skills/` folder, this step flags it for deletion (already staged via Step 2C's stale-destination cleanup — this is a second safety net). If it has a `.DS_Store` file, same prompt — answer `keep` and add `.DS_Store` to `.gitignore` to stop it being flagged in future.

**Never flag `.claude-plugin/`, `.git/`, or `.gitignore`** — these are hardcoded in the allowlist.

### 2H. Pre-commit consistency audit (blocker before Step 3)

Before staging the commit, audit **every version record and every skill-list record** to verify they all agree. A commit that ships inconsistent versions or a stale README is a hidden bug — catch it here.

Build the **source of truth** from the already-synced files:
- `expected_version` = `plugin.json → version` (the value just written in Step 2E)
- `expected_skills` = list of `{repo_path}/{skills_dir}/*/` folder names, sorted alphabetically
- `expected_skill_count` = len(expected_skills)

Now check each record against the source of truth:

| # | Record | Check | On mismatch |
|---|---|---|---|
| 1 | `{plugin_json_path} → version` | equals `expected_version` | block commit — Step 2E must have failed partially |
| 2 | `{marketplace_json_path} → metadata.version` | equals `expected_version` | block commit — same as above |
| 3 | `{marketplace_json_path} → plugins[0].skills` (sorted) | equals `["./{skills_dir}/{s}" for s in expected_skills]` | block commit — Step 2D must have failed |
| 4 | Each `{repo_path}/{skills_dir}/*/SKILL.md` frontmatter `metadata.version` | does NOT end with `-dev` | block commit — Step 2A transform missed the `-dev` strip |
| 5 | `{repo_path}/README.md` skill list | every entry in `expected_skills` must appear as a line item (markdown table row, bullet, or backtick mention). For the reverse direction (catching stale entries that no longer exist), only flag candidate skill names matching `{published_prefix}[a-z][a-z0-9-]*` or the literal `example-skill` — NOT arbitrary identifiers like the plugin namespace (`alex-tradeblocks` on its own without a further hyphenated suffix) or other documentation terms that happen to start with the prefix | block commit — dev-folder README is stale; update `$TB_ROOT/{dev_skills_folder}/README.md` to match, then re-run Step 2F |
| 6 | `{repo_path}/README.md` skill count references (e.g. `"13 skills"`) | if the README contains a phrase matching `\d+ skills`, the number must equal `expected_skill_count` | block commit — update the count in the dev README and re-sync |
| 7 | `$TB_ROOT/{dev_skills_folder}/README.md` skill list & count | same checks as rows 5 and 6 | block commit — user must update the dev README before proceeding |
| 8 | `{repo_path}/README.md` version references | any `vX.Y.Z` or `version X.Y.Z` pattern must equal `expected_version` (if present). Use regex `(?<![\d.])v?\d+\.\d+\.\d+(?![\d.])` to avoid false positives on IP addresses (`0.0.0.0`), file paths (`v1.2.3.4.bak`), etc. | block commit — update dev README |
| 9 | `$TB_ROOT/{dev_skills_folder}/README.md` version references | same as row 8 (use the same anchored regex) | block commit |
| 10 | `{repo}/LICENSE` / `package.json` | byte-identical to `$TB_ROOT/{dev_skills_folder}/{filename}` | block commit — Step 2F failed to sync |
| 11 | `{repo}/package.json` `version` field (if present) | equals `expected_version` | block commit — update dev `package.json` version and re-run Step 2F |
| 12 | `{repo_path}/` top-level entries | matches expected set (dev-sourced + allowlist: `.claude-plugin/`, `.git/`, `.gitignore`) | block commit — Step 2G left un-mirrored entries |

Emit the audit as a compact table:

```
Pre-commit consistency audit:
  Check                             Expected     Actual       Status
  plugin.json version               2.0.3        2.0.3        OK
  marketplace.json version          2.0.3        2.0.3        OK
  marketplace.json skills array     13 entries   13 entries   OK
  SKILL.md versions (no -dev)       13 files     13 files     OK
  repo README skill list            13 skills    13 skills    OK
  repo README skill count phrase    "13 skills"  "13 skills"  OK
  dev README skill list             13 skills    12 skills    MISMATCH ← new skill added but dev README not updated
  dev README skill count            13 skills    "12 skills"  MISMATCH
  Version mentions (repo README)    2.0.3        2.0.3        OK
  Version mentions (dev README)     2.0.3        --           OK (no version mentioned in README body)
```

**On any MISMATCH: STOP. Do not proceed to Step 3.** Emit the specific fix required and ask the user to address it (or to confirm override, which should be rare). For skill-list mismatches in dev README, offer to auto-update: *"Update `$TB_ROOT/{dev_skills_folder}/README.md` skill-list section to match the current 13 skills and bump the count? (Y/n)"*. On accept, rewrite only the skill list and count; re-run Step 2F; re-run this audit.

**On all OK: proceed to Step 3 commit.**

---

## Step 3: Commit & Push

1. `cd {repo_path} && git add -A`
2. Run `git diff --cached --stat` and show the summary to the user.
3. Build a commit message:
   ```
   Update skills to vX.Y.Z

   Updated: {published_prefix}skill-a (1.0 → 3.0)
   Added: {published_prefix}skill-b (2.0)
   Support files synced.
   ```
4. Confirm with user: *"Commit and push to origin/main?"*
5. If confirmed:
   - `git commit -m "..."` (use HEREDOC for multiline)
   - `git push origin main`
6. Report the commit SHA.

---

## Step 4: Update Plugin Cache & Instruct User

Claude Code does NOT auto-refresh the plugin cache on restart — a restart alone reloads whatever version is already cached. To pick up the new publish, the cache itself must be updated via `claude plugin update`. That CLI command pulls the marketplace clone and rewrites the cache on disk, but the running session's in-memory registry remains stale until restart. So the flow is: run the update CLI here, then instruct the user to restart.

After push succeeds:

1. **Run the plugin update via CLI:**
   ```bash
   claude plugin update {plugin_id}
   ```
   Where `{plugin_id}` is the full `{namespace}@{marketplace-name}` from config (e.g. `alex-tradeblocks@alex-tradeblocks-skills`).

   Expected output: `✔ Plugin "{namespace}" updated from X.Y.Z to A.B.C for scope user. Restart to apply changes.`

   If the command reports "already up to date", the marketplace clone didn't see the new push yet — wait a few seconds and retry, or manually pull:
   ```bash
   marketplace_path="$HOME/.claude/plugins/marketplaces/{marketplace_name}"
   git -C "$marketplace_path" pull origin main
   ```
   Then re-run `claude plugin update`.

2. **Verify the cache updated:**
   ```bash
   jq -r '.plugins["{plugin_id}"][0].version' ~/.claude/plugins/installed_plugins.json
   ```
   Must equal the version just pushed (Step 2E's bump). If not, the CLI update didn't land — surface the error and stop.

3. **Report to the user:**

   ```
   Published v{X.Y.Z} @ {sha}. Cache updated {old_ver} → {X.Y.Z}. Restart Claude Code to activate.
   ```

   The cache is already current on disk; the restart just reloads the session's in-memory registry. Do not add extra steps — this is the whole fix.

---

## Step 5: Report & Log

**Final summary:**

```
GitHub Update — YYYY-MM-DD HH:MM

Plugin version: X.Y.Z → X.Y.Z
  Updated:   {published_prefix}skill-a (1.0 → 3.0)
  Added:     {published_prefix}skill-b (2.0), {published_prefix}skill-c (1.0)
  Unchanged: N skills (no diff since cache)
  Removed:   {published_prefix}old-skill (newly excluded this round)
  Excluded:  M dev skills skipped (W warnings reported, not acted on)
Pushed: main @ abc1234
Cache: updated X.Y.Z → A.B.C on disk · restart Claude Code to load into session
```

**Append to `$TB_ROOT/alex_github_update_log.md`:**

```markdown
## YYYY-MM-DD HH:MM
- Plugin version: X.Y.Z → X.Y.Z
- Updated: {published_prefix}skill-a (1.0 → 3.0)
- Added: {published_prefix}skill-b (2.0)
- Removed from repo (now excluded): {published_prefix}old-skill
- Skipped: N unchanged, M excluded (W skip-set warnings, no action taken)
- Pushed: main @ abc1234
- Cache: `claude plugin update` ran, cache @ vX.Y.Z · restart required
```

Create the log file if it doesn't exist. Append-only — never truncate.

---

## What NOT to Do

- Do not modify dev SKILL.md files except for version bumps the user explicitly approves.
- Do not push without explicit user confirmation.
- Do not overwrite `alex_github_update_config.md` after first creation.
- Do not auto-edit `exclude_skills` — changes to that list are the user's call and must be made by hand. If the preview (Step 0.5) doesn't match the user's intent, abort and tell them to edit the config.
- Do not publish skills listed in `exclude_skills`. If one is already present in the repo, delete it silently as part of Step 2B's strict-mirror cleanup (announce in the run summary).
- Do not skip Step 0.5's confirmation prompt, even on "obvious" runs. The preview is the gate that prevents surprises like silently publishing a half-done skill or silently deleting a repo folder the user forgot was published.
- Do not block the run on skip-set audit findings. Skip-set issues are WARNINGS by design — the user has already told you those skills are deferred.
- Do not modify the skill body content during sync — only transform frontmatter fields (name, description prefix, version suffix).
- Do not delete entries on the allowlist: `.claude-plugin/`, `.git/`, `.gitignore`. Everything else in the repo must be either sourced from dev (and thus gets overwritten/synced) or deleted per Model A strict mirror.
- Do not hardcode user-specific values (paths, repo names, prefixes) in this skill file. All user-specific values come from the config.
- Do not skip the `claude plugin update` CLI call in Step 4 — Claude Code does NOT auto-refresh the cache on restart. A restart alone will keep loading the stale cached version. The CLI command is what rewrites the cache; the restart only reloads the already-updated cache into the session.
- Do not run `claude plugin install` or `claude plugin uninstall` from within a Claude Code session — those change the set of installed plugins and the running process will not reconcile cleanly. Only `claude plugin update` is safe here because it only refreshes the cache of an already-installed plugin.
