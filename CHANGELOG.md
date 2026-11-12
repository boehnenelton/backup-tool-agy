# Changelog — Backup Tool AGY (`backup-tool-agy`)

All notable changes to this project are documented in this file.
The format is based on Keep a Changelog, and this project adheres to Policy §3 Versioning and PolyForm Noncommercial 1.0.0.

## [1.0.0] - 2026-11-12
### Added
- **Multi-Scope Ecosystem Backup Engine (`backup_tool_agy.py`)**:
  - Scans and archives components across `~/` (Termux Home), `/storage/emulated/0` (Internal Storage Admin & Documents), and SD Card mount (`/storage/emulated/0/Admin/SD_Fallback`).
  - Automatically appends unique UUIDv4 to backup filenames (`<stem>_<uuid><ext>` for files, `<name>_<uuid>.zip` for directories).
  - Tracks all originals in canonical `manifest.104a.bejson` manifests with SHA-256 integrity hashes.
- **10-Slot Disc Changer & Protected Emergency Golden Master (`agy_slot_manager.py`)**:
  - Implements 10 hot-swappable experimental slots (`Agy-Slot1` through `Agy-Slot10`).
  - Protected Slot 11 (`Agy-Emergency`) master golden image with write-lock protection (`E_EMERGENCY_PROTECTION`). Overwrite permitted strictly in neutral baseline after emergency restoration.
  - Slot actions: `load`, `save`, `copy`, `export`, `import`, `label`, `emergency-restore`, `emergency-save`.
- **Universal Config-Driven Loaded Chamber CLI (`universal_snapshot_engine.py` / `chamber-cli`)**:
  - Config-driven multi-profile architecture (`profiles_registry.104a.bejson`) supporting arbitrary profiles (e.g. `agy`, `skills`, or custom).
  - Declarative path rules with extension filtering (`config.104a.bejson`).
  - Dedicated 10 slots + 1 emergency slot per profile (`<profile>-Slot1..10` and `<profile>-Emergency`).
  - Interactive 49-column mobile portrait TUI menu (`chamber-cli menu`) adhering to `design-terminal-menu` (Archetype 2: Loaded Chamber).
- **Presentation & Ergonomics (`design-terminal-cli` & `design-terminal-menu`)**:
  - Tri-Color ANSI palette (`#DE2626` red accent, bold white text, subtle gray boundaries).
  - True ANSI-aware visible width calculation ensuring strict 49-column ceiling across mobile portrait terminals.
  - Deterministic status feedback (`[✓]` positive in ALL CAPS, `[X]` error in lowercase, `[*]`).
- **Packaging & Delivery**:
  - PolyForm Noncommercial 1.0.0 license.
  - Strict `.gitignore` and `.beignore` filtering out all backup archives, snapshot dumps, and temporary files.
  - Canonical `bejson_project.json` manifest.
