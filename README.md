# AGY Ecosystem Multi-Scope Backup & 10-Slot Disc Changer System (`backup-tool-agy`)

**Version**: `10300`  
**License**: PolyForm Noncommercial License 1.0.0 (`PolyForm-Noncommercial-1.0.0`)  
**Author**: Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton  
**RELATIONAL_ID**: `8a48b59e-e6a2-4a0b-801b-90f727b140cb`

---

## 1. Architectural Overview

`backup_tool_agy.py` and `agy_slot_manager.py` form the canonical management, backup, and restoration suite for Antigravity (AGY) customizations, rules, markdown assets, and declarative subagent specifications.

The system features:
1. **Multi-Scope Ecosystem Backup**: Scans and mirrors assets across **Termux Home (`~/`)**, **Internal Storage (`/storage/emulated/0`)**, and the **SD Card (`/storage/emulated/0/Admin/SD_Fallback`)** with UUIDv4 filenames and BEJSON 104a manifests.
2. **10-Slot Disc Changer Architecture**: Provides 10 user-selectable experimental profile slots (`Agy-Slot1` through `Agy-Slot10`) plus a protected 11th master emergency slot (`Agy-Emergency`).
3. **Emergency Lockout Protection**: Slot 11 (Emergency Golden Image) cannot be overwritten while any experimental slot is active. It can ONLY be updated after a full emergency restoration into a neutral baseline.
4. **Deterministic Profile Switching**: Switching slots clears active customizations (`skills/`, `hooks/`, `agents/`, rules) and cleanly loads the selected slot's exact snapshot.

---

## 2. Slot Architecture & Storage Hierarchy

All slot profiles reside at `~/agy-slots/`:

| Slot | Directory | Type | Purpose |
|---|---|---|---|
| **Slot 1** | `~/agy-slots/Agy-Slot1/` | Regular Slot | Default Production Baseline Profile |
| **Slot 2** | `~/agy-slots/Agy-Slot2/` | Regular Slot | Experimental Profile (e.g. React Dev) |
| **Slot 3** | `~/agy-slots/Agy-Slot3/` | Regular Slot | Experimental Profile (e.g. Import / Audit) |
| **Slots 4–10** | `~/agy-slots/Agy-Slot4/` .. `Agy-Slot10/` | Regular Slots | Available Experimental Slots |
| **Slot 11 (EM)** | `~/agy-slots/Agy-Emergency/` | Master Golden Image | Protected Emergency Restore Baseline |

Root Slot Registry: `~/agy-slots/slots_registry.104a.bejson` (Tracks slot states, active slot ID, item counts, labels, and timestamps).

---

## 3. Slot Management CLI (`agy-slots`)

All interfaces adhere to the 49-character mobile portrait terminal ceiling (`DIVIDER_49`).

### Slot Status & Inventory Table
```bash
python3 ~/backup-tool-agy/agy_slot_manager.py status
# or
~/backup-tool-agy/agy-slots status
```

### Switching / Loading Slots ("Disc Changer")
```bash
# Switch to Slot 2 (clears live customizations, restores Slot 2 snapshot)
~/backup-tool-agy/agy-slots load 2

# Switch with auto-saving current active slot before unloading
~/backup-tool-agy/agy-slots load 3 --auto-save
```

### Saving Active State to a Slot
```bash
~/backup-tool-agy/agy-slots save 2 -l "Experimental Rules v2"
```

### Cloning & Managing Slots
```bash
# Clone Slot 1 into Slot 4
~/backup-tool-agy/agy-slots copy 1 4

# Assign custom label
~/backup-tool-agy/agy-slots label 4 "Strict Security Audit Profile"

# Export slot to portable zip archive
~/backup-tool-agy/agy-slots export 2 ~/slot2_bundle.zip

# Import portable zip archive into slot 5
~/backup-tool-agy/agy-slots import ~/slot2_bundle.zip 5 -l "Imported Bundle"
```

### Emergency Restore & Golden Image Protection
```bash
# 1. Restore master emergency baseline (unloads all experimental slots)
~/backup-tool-agy/agy-slots emergency-restore

# 2. Overwrite emergency golden master (ONLY allowed in neutral baseline after emergency-restore)
~/backup-tool-agy/agy-slots emergency-save -l "Golden Master Baseline v2"
```

---

## 4. Multi-Scope Direct Backup CLI (`backup_tool_agy.py`)

```bash
# Full multi-scope backup (~/, Internal, SD)
python3 ~/backup-tool-agy/backup_tool_agy.py backup --include-sd

# Scope selection
python3 ~/backup-tool-agy/backup_tool_agy.py backup --scope home
python3 ~/backup-tool-agy/backup_tool_agy.py backup --scope internal
python3 ~/backup-tool-agy/backup_tool_agy.py backup --scope sd

# Verify integrity against SHA-256 hashes
python3 ~/backup-tool-agy/backup_tool_agy.py verify

# Direct restore to original paths
python3 ~/backup-tool-agy/backup_tool_agy.py restore
```

---

## 5. Universal Config-Driven 10-Slot Loaded Chamber CLI (`chamber-cli`)

`chamber-cli` (powered by `universal_snapshot_engine.py`) transforms the disc changer into an era-neutral, config-driven universal snapshot engine. Each profile maintains its own declarative path rules, extension filters (`.py`, `.md`, etc.), and dedicated set of 10 slots + 1 emergency slot (`<profile>-Slot1` .. `<profile>-Slot10` and `<profile>-Emergency`).

### Profile Management Commands
```bash
# List all profiles
chamber-cli profile list

# Create a new profile with 10 slots + emergency slot
chamber-cli profile create skills -l "Dedicated Skills Suite"

# Select active profile
chamber-cli profile select skills

# View path rules and extension filters for a profile
chamber-cli profile paths -p skills

# Add a path rule with an extension filter
chamber-cli profile add-path skills ~/.gemini/config/skills -e .py -s code

# Remove a path rule
chamber-cli profile remove-path <rule_id> -p skills

# Delete a profile and its slots
chamber-cli profile delete <profile_name>
```

### Universal Slot Operations ("Chamber")
```bash
# View slot status for active profile
chamber-cli slot status

# View slot status for a specific profile
chamber-cli slot status -p skills

# Snapshot active state into a slot
chamber-cli slot save 1 -p skills -l "Skills Baseline"

# Switch / Load slot (disc changer)
chamber-cli slot load 2 -p skills --auto-save

# Copy one slot to another
chamber-cli slot copy 1 3 -p skills

# Export slot to portable zip
chamber-cli slot export 1 ~/skills_slot1.zip -p skills

# Import zip into slot
chamber-cli slot import ~/skills_slot1.zip 4 -l "Imported Skills" -p skills

# Emergency restore and golden image update
chamber-cli slot emergency-restore -p skills
chamber-cli slot emergency-save -p skills -l "Skills Master Image"
```

