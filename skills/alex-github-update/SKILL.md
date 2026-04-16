---
name: alex-github-update
description: >
  Publish dev skills to the GitHub marketplace. Audits versions against cache, flags content
  changes without version bumps, syncs files to the repo with name/version transforms, commits,
  pushes, and triggers cache update. Config-driven — builds github_update_config.md on first run.
compatibility: Requires git, gh CLI, and access to the GitHub repo configured in github_update_config.md.
metadata:
  author: alex-tradeblocks
  version: "1.0"
---

# Dev GitHub Update

Publish dev skills from the local dev folder to the GitHub marketplace plugin repo. Five steps: load config, audit versions, sync files, commit & push, update cache.

---

## Step 0: Load (or Create) Config

Look for `$TB_ROOT/github_update_config.md`.

### If config exists

Parse the YAML frontmatter with a real YAML parser — same pattern as startup:

```python
import re, yaml, pathlib
txt = pathlib.Path('github_update_config.md').read_text()
fm = re.search(r'^---\n(.*?)\n---', txt, re.DOTALL).group(1)
config = yaml.safe_load(fm)
```

If PyYAML is unavailable, install with `pip install pyyaml`. Do NOT use line-by-line regex.

Validate that `repo_path` exists and is a git repo. If not, flag and ask.

### If config does NOT exist (first run)

Detect values by probing, present to user for confirmation, then write the config:

| Key | How to detect |
|---|---|
| `repo_path` | Search `~/Developer/` for a directory containing `.claude-plugin/plugin.json`. If multiple or none found, ask the user for the absolute path. |
| `dev_skills_folder` | Read from `startup_config.md` if it exists (`dev_skills_folder` key), otherwise look for `Dev-*Skills*` in `$TB_ROOT`. |
| `plugin_id` | Read `~/.claude/plugins/installed_plugins.json` — find the plugin whose install path contains the repo name. Format: `{namespace}@{marketplace-name}`. |
| `dev_prefix` | Default `dev-`. Confirm with user. |
| `published_prefix` | Read the name field of any existing published skill in `{repo_path}/skills/*/SKILL.md` and extract the common prefix. Default `alex-`. Confirm with user. |
| `support_files_src` | Look for a non-skills, non-hidden directory in `$TB_ROOT` that matches the repo name or contains `.default.csv` files. Ask if ambiguous. |
| `support_files_dest` | Same folder name in the repo. Confirm. |
| `shared_folder` | Look for `_shared/` in `{dev_skills_folder}`. Default `_shared`. |
| `plugin_json_path` | `.claude-plugin/plugin.json` (standard location). Verify exists in repo. |
| `marketplace_json_path` | `.claude-plugin/marketplace.json`. Verify exists in repo. |
| `skills_dir` | `skills` (standard location). Verify exists in repo. |
| `exclude_skills` | Ask user if any dev skills should be excluded from publishing (e.g. `dev-tradeblocks-startup` if it's workspace-only). Default empty list. |

Write to `$TB_ROOT/github_update_config.md` using the Config Schema below.

### Config Schema

```markdown
---
schema_version: 1

# Repo
repo_path: /Users/username/Developer/alex-tradeblocks-skills
skills_dir: skills
plugin_json_path: .claude-plugin/plugin.json
marketplace_json_path: .claude-plugin/marketplace.json

# Dev workspace
dev_skills_folder: Dev-TradeBlocks-Skills    # relative to TB root
shared_folder: _shared                       # relative to dev_skills_folder

# Support files (shipped with plugin but not skills)
support_files_src: Alex-TradeBlocks-Skills   # in TB root
support_files_dest: Alex-TradeBlocks-Skills  # in repo

# Naming conventions
dev_prefix: "dev-"
published_prefix: "alex-"
plugin_id: alex-tradeblocks@alex-tradeblocks-skills

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

## Step 1: Version & Content Audit

For each dev skill in `{dev_skills_folder}/*/SKILL.md` (excluding any in `exclude_skills`):

1. Parse dev SKILL.md frontmatter with `yaml.safe_load` → extract `name`, `metadata.version` (or `version`), full file content.
2. Derive the **stem** by stripping `{dev_prefix}` from the name (e.g. `dev-entry-filter-pareto` → `entry-filter-pareto`).
3. Look for a matching **cache skill**:
   - Glob `~/.claude/plugins/cache/*/alex-tradeblocks/*/skills/{published_prefix}{stem}/SKILL.md`
   - If found, parse its frontmatter for version and read its full content.
4. Look for a matching **repo skill**:
   - Check `{repo_path}/{skills_dir}/{published_prefix}{stem}/SKILL.md`
   - If found, read full content for diff comparison.

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
  Skill                             Dev Ver   Cache Ver  Changed?  Status
  dev-entry-filter-pareto           3.0-dev   1.0        yes       READY (dev ahead)
  dev-threshold-analysis            3.0-dev   1.0        yes       READY (dev ahead)
  dev-entry-filter-heatmap          2.0-dev   --         --        NEW
  dev-create-datelist               1.0-dev   --         --        NEW
  ...
  dev-tradeblocks-startup           3.0-dev   --         --        EXCLUDED
  dev-github-update                 1.0-dev   --         --        EXCLUDED

  Summary: N ready · M new · J skipped (no change) · K excluded
```

**If any FLAG rows exist:** prompt the user with specific instructions: *"These skills have content changes but the dev version (after stripping -dev) matches cache. Cache won't refresh without a version bump. Bump now, or continue anyway?"*

If user chooses to bump: for each flagged skill, increment the version in the dev SKILL.md (suggest patch bump), re-read, and re-audit.

---

## Step 2: Sync to Repo

For each skill with status READY or NEW:

### 2A. Copy skill files

1. Create `{repo_path}/{skills_dir}/{published_prefix}{stem}/` if it doesn't exist.
2. Copy all files from `{dev_skills_folder}/{dev_prefix}{stem}/` to the repo skill folder.
3. **Transform the copied SKILL.md** (in the repo, NOT the dev original):
   - `name:` field — replace `{dev_prefix}` with `{published_prefix}` (e.g. `dev-entry-filter-pareto` → `alex-entry-filter-pareto`)
   - `description:` field — strip leading `[DEV] ` if present
   - `version:` field — strip trailing `-dev` (e.g. `3.0-dev` → `3.0`)
   - Leave all other fields and body content unchanged.

### 2B. Sync support files

Copy contents of `$TB_ROOT/{support_files_src}/` → `{repo_path}/{support_files_dest}/`, overwriting existing files. Also copy `{dev_skills_folder}/{shared_folder}/` contents into `{repo_path}/{support_files_dest}/` (shared CSVs, SQL templates, etc. that ship with the plugin).

### 2C. Update marketplace.json

Read `{repo_path}/{marketplace_json_path}`. For each NEW skill, add its path to the `plugins[0].skills` array:
```json
"./skills/alex-new-skill-name"
```

Do not duplicate existing entries. Sort the array alphabetically for consistency.

### 2D. Bump plugin version

Read current version from `{repo_path}/{plugin_json_path}`. Ask user: *"Current plugin version is X.Y.Z. Bump type? (patch / minor / major)"*

Apply the bump to **both** `plugin.json` (`version` field) and `marketplace.json` (`metadata.version` field). These must stay in sync.

---

## Step 3: Commit & Push

1. `cd {repo_path} && git add -A`
2. Run `git diff --cached --stat` and show the summary to the user.
3. Build a commit message:
   ```
   Update skills to vX.Y.Z

   Updated: skill-a (1.0 → 3.0), skill-b (1.0 → 3.0)
   Added: skill-c (2.0), skill-d (1.0)
   Support files synced.
   ```
4. Confirm with user: *"Commit and push to origin/main?"*
5. If confirmed:
   - `git commit -m "..."` (use HEREDOC for multiline)
   - `git push origin main`
6. Report the commit SHA.

---

## Step 4: Update Plugin Cache

After push succeeds:

1. Run: `claude plugins update {plugin_id}`
2. Report the result (new version, skills loaded).
3. Prompt: *"Re-open Claude Code to pick up the refreshed skill cache. New skills won't be available until restart."*

---

## Step 5: Report & Log

**Final summary:**

```
GitHub Update — YYYY-MM-DD HH:MM

Plugin version: X.Y.Z → X.Y.Z
  Updated: alex-entry-filter-pareto (1.0 → 3.0), alex-threshold-analysis (1.0 → 3.0)
  Added:   alex-entry-filter-heatmap (2.0), alex-create-datelist (1.0)
  Skipped: 3 (no changes), 2 (excluded)
Pushed: main @ abc1234
Cache: updated — restart Claude to load
```

**Append to `$TB_ROOT/github_update_log.md`:**

```markdown
## YYYY-MM-DD HH:MM
- Plugin version: 1.2.0 → 1.3.0
- Updated: alex-entry-filter-pareto (1.0 → 3.0), alex-threshold-analysis (1.0 → 3.0)
- Added: alex-entry-filter-heatmap (2.0)
- Skipped: 3 unchanged, 2 excluded
- Pushed: main @ abc1234
```

Create the log file if it doesn't exist. Append-only — never truncate.

---

## What NOT to Do

- Do not modify dev SKILL.md files except for version bumps the user explicitly approves.
- Do not push without explicit user confirmation.
- Do not overwrite `github_update_config.md` after first creation.
- Do not publish skills listed in `exclude_skills`.
- Do not modify the skill body content during sync — only transform frontmatter fields (name, description prefix, version suffix).
- Do not delete files in the repo that aren't in the dev folder. The repo may have files (README, LICENSE, .gitignore) that don't exist in dev.
