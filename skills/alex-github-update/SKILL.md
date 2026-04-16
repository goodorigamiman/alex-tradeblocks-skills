---
name: alex-github-update
description: >
  Publish dev skills to the GitHub marketplace. Audits versions against cache, flags content
  changes without version bumps, syncs files to the repo with name/version transforms, commits,
  pushes, and triggers cache update. Config-driven — builds alex_github_update_config.md on first run.
compatibility: Requires git, gh CLI, and access to the GitHub repo configured in alex_github_update_config.md.
metadata:
  author: alex-tradeblocks
  version: "1.3"
---

# Dev GitHub Update

Publish dev skills from the local dev folder to the GitHub marketplace plugin repo. Five steps: load config, audit versions, sync files, commit & push, update cache.

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
| `support_files_src` | Look for a non-skills, non-hidden directory in `$TB_ROOT` that contains `.default.csv` files. Ask if ambiguous. |
| `support_files_dest` | Same folder name in the repo. Confirm. |
| `shared_folder` | Look for `_shared/` in `{dev_skills_folder}`. Default `_shared`. |
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
shared_folder: _shared                            # relative to dev_skills_folder

# Support files (shipped with plugin but not skills)
support_files_src: <support-folder-in-tb-root>    # folder containing .default.csv files
support_files_dest: <support-folder-in-repo>      # usually same name as src

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

## Step 1: Version & Content Audit

For each dev skill in `{dev_skills_folder}/*/SKILL.md` (excluding any in `exclude_skills`):

1. Parse dev SKILL.md frontmatter with `yaml.safe_load` → extract `name`, `metadata.version` (or `version`), full file content.
2. Derive the **stem** by stripping `{dev_prefix}` from the name (e.g. `{dev_prefix}my-skill` → `my-skill`).
3. Look for a matching **cache skill**:
   - Glob `~/.claude/plugins/cache/*/{plugin_namespace}/*/skills/{published_prefix}{stem}/SKILL.md`
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
  {dev_prefix}skill-a               3.0-dev   1.0        yes       READY (dev ahead)
  {dev_prefix}skill-b               3.0-dev   1.0        yes       READY (dev ahead)
  {dev_prefix}skill-c               2.0-dev   --         --        NEW
  ...

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
   - `name:` field — replace `{dev_prefix}` with `{published_prefix}`
   - `description:` field — strip leading `[DEV] ` if present
   - `version:` field — strip trailing `-dev` (e.g. `3.0-dev` → `3.0`)
   - Leave all other fields and body content unchanged.

### 2B. Clean up stale folders

Check for any folders in `{repo_path}/{skills_dir}/` that use the `{dev_prefix}` naming (e.g. `dev-my-skill` instead of `{published_prefix}my-skill`). These are leftovers from prior manual copies and should be removed:

1. Glob `{repo_path}/{skills_dir}/{dev_prefix}*/`
2. For each match, check if a properly-named `{published_prefix}` counterpart exists.
3. If counterpart exists: delete the stale `{dev_prefix}` folder (it's been superseded).
4. If no counterpart: flag it and ask the user whether to rename or delete.

Also remove any stale entries from `marketplace.json` that reference `{dev_prefix}` paths.

### 2C. Sync support files

Copy contents of `$TB_ROOT/{support_files_src}/` → `{repo_path}/{support_files_dest}/`, overwriting existing files. Also copy `{dev_skills_folder}/{shared_folder}/` contents into `{repo_path}/{support_files_dest}/` (shared CSVs, SQL templates, etc. that ship with the plugin).

### 2D. Update marketplace.json

Read `{repo_path}/{marketplace_json_path}`. For each NEW skill, add its path to the `plugins[0].skills` array:
```json
"./{skills_dir}/{published_prefix}{stem}"
```

Do not duplicate existing entries. Sort the array alphabetically for consistency.

### 2E. Bump plugin version

Read current version from `{repo_path}/{plugin_json_path}`. Ask user: *"Current plugin version is X.Y.Z. Bump type? (patch / minor / major)"*

Apply the bump to **both** `plugin.json` (`version` field) and `marketplace.json` (`metadata.version` field). These must stay in sync.

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

## Step 4: Verify Marketplace Clone & Instruct User

**Important:** Do NOT run `claude plugins update` or `claude plugins install` from within a running Claude Code session. These CLI subcommands update filesystem state (cache directories, `installed_plugins.json`) but the parent Claude Code process does not reload its in-memory plugin registry. The result is a silent version mismatch — the cache files look correct but `/plugin` still shows the old version and new skills never appear.

After push succeeds:

1. **Verify the marketplace clone is current.** The marketplace clone is the local git repo that `/plugin` → "Update now" reads from:
   ```bash
   marketplace_path="$HOME/.claude/plugins/marketplaces/{marketplace_name}"
   git -C "$marketplace_path" log --oneline -1
   ```
   Confirm the HEAD commit SHA matches the push from Step 3. If it doesn't (remote hasn't been fetched yet):
   ```bash
   git -C "$marketplace_path" pull origin main
   ```
   Re-verify HEAD matches. Where `{marketplace_name}` comes from the config (it's the marketplace portion of `plugin_id`, i.e. the part after `@`).

2. **Report and instruct the user.** The marketplace clone is now current — all the filesystem work is done. The in-memory plugin reload cannot be triggered programmatically; only the interactive `/plugin` UI can do it. Show the user this prompt:

   ```
   Published v{X.Y.Z} @ {sha}

   Two steps to activate:
     /plugin  →  "{plugin_id}"  →  "Update now"
     Then restart Claude Code (/exit + relaunch)
   ```

   Do NOT add caveats, explanations, or apologies to the user prompt. Keep it exactly this concise.

3. **Do NOT** modify `installed_plugins.json` directly, run `claude plugins update`, or attempt any other automated cache refresh from within the session.

---

## Step 5: Report & Log

**Final summary:**

```
GitHub Update — YYYY-MM-DD HH:MM

Plugin version: X.Y.Z → X.Y.Z
  Updated: {published_prefix}skill-a (1.0 → 3.0)
  Added:   {published_prefix}skill-b (2.0), {published_prefix}skill-c (1.0)
  Skipped: N (no changes), M (excluded)
Pushed: main @ abc1234
Cache: run /plugin → Update now, then restart to activate vX.Y.Z
```

**Append to `$TB_ROOT/alex_github_update_log.md`:**

```markdown
## YYYY-MM-DD HH:MM
- Plugin version: X.Y.Z → X.Y.Z
- Updated: {published_prefix}skill-a (1.0 → 3.0)
- Added: {published_prefix}skill-b (2.0)
- Skipped: N unchanged, M excluded
- Pushed: main @ abc1234
- Cache: run /plugin → Update now, then restart to activate vX.Y.Z
```

Create the log file if it doesn't exist. Append-only — never truncate.

---

## What NOT to Do

- Do not modify dev SKILL.md files except for version bumps the user explicitly approves.
- Do not push without explicit user confirmation.
- Do not overwrite `alex_github_update_config.md` after first creation.
- Do not publish skills listed in `exclude_skills`.
- Do not modify the skill body content during sync — only transform frontmatter fields (name, description prefix, version suffix).
- Do not delete files in the repo that aren't in the dev folder (README, LICENSE, .gitignore, etc.).
- Do not hardcode user-specific values (paths, repo names, prefixes) in this skill file. All user-specific values come from the config.
- Do not run `claude plugins update`, `claude plugins install`, or `claude plugins uninstall` from within a Claude Code session. These update filesystem state but the running process doesn't reload — causing a silent version mismatch. Always direct the user to `/plugin` → "Update now" instead.
