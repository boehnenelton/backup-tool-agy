#!/data/data/com.termux/files/usr/bin/env python3
"""
Name:          universal_snapshot_engine.py
Description:   Config-Driven Universal Snapshot & Slot Changer Engine with BEJSON 104a MFDB State Management
Version:       10400
Date Created:  2026-11-12
Author Credit: Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
License:       PolyForm Noncommercial License 1.0.0 (PolyForm-Noncommercial-1.0.0)
RELATIONAL_ID: 9c5e317b-23a4-4f8e-8bf0-89025171e1de
"""

import argparse
import datetime
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# 49-character viewport ceiling constants for mobile portrait compliance
DIVIDER_49: str = "=" * 49
SUBDIVIDER_49: str = "-" * 49

# Tri-Color ANSI Styling Palette (Policy §8.1 / design-terminal-cli / design-terminal-menu)
C_RESET: str = "\033[0m"
C_RED: str = "\033[38;5;196m"         # Policy §8.1 #DE2626 Primary Accent
C_BOLD_RED: str = "\033[1;38;5;196m"  # Frame titles, alert highlights
C_WHITE: str = "\033[1;37m"           # High-contrast bold white
C_GRAY: str = "\033[90m"             # Framing borders and subtle dividers
C_CYAN: str = "\033[36m"             # Values, counts, file paths
C_GREEN: str = "\033[1;32m"          # Active markers, positive feedback
C_YELLOW: str = "\033[33m"           # Warnings, emergency states
C_CLEAR: str = "\033[2J\033[H"       # Pre-render console clear

# Default System Paths
HOME_DIR: Path = Path(os.path.expanduser("~"))
SLOTS_BASE_DIR: Path = HOME_DIR / "agy-slots"
PROFILES_REGISTRY_PATH: Path = SLOTS_BASE_DIR / "profiles_registry.104a.bejson"

TOTAL_REGULAR_SLOTS = 10
EMERGENCY_SLOT_ID = 11

PRUNE_DIRS: Set[str] = {
    ".git", "node_modules", "__pycache__", ".pytest_cache", "cache",
    "data_temp", "brain", "android-sdk", "site-packages", ".gradle",
    "build", "dist", "backup-nov11", "backup-tool-agy", ".cargo",
    "skills_backup_20261103_101328", ".script_commander", "Android"
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("universal_snapshot_engine")

# ---------------------------------------------------------------------------
# BEJSON 104a Core Primitives with O(1) Field Map Cache
# ---------------------------------------------------------------------------
_FIELD_MAP_CACHE: Dict[Tuple[str, ...], Dict[str, int]] = {}

def bejson_get_field_map(doc: Dict[str, Any]) -> Dict[str, int]:
    """Retrieve or build O(1) field map for canonical BEJSON document."""
    fields = doc.get("Fields", [])
    if not isinstance(fields, list):
        return {}
    field_names = tuple(f.get("name") if isinstance(f, dict) else str(f) for f in fields)
    if field_names not in _FIELD_MAP_CACHE:
        _FIELD_MAP_CACHE[field_names] = {name: idx for idx, name in enumerate(field_names)}
    return _FIELD_MAP_CACHE[field_names]

def bejson_create_104a(record_type: str, fields: List[Dict[str, str]], values: List[List[Any]], **custom: Any) -> Dict[str, Any]:
    """Factory creating canonical BEJSON 104a document envelope."""
    doc: Dict[str, Any] = {
        "Format": "BEJSON",
        "Format_Version": "104a",
        "Format_Creator": "Elton Boehnen",
        "Records_Type": [record_type],
        "Fields": fields,
        "Values": values
    }
    doc.update(custom)
    return doc

def bejson_atomic_write(file_path: Path, doc: Dict[str, Any]) -> bool:
    """Atomic write replacement using NamedTemporaryFile and os.replace."""
    target_dir = file_path.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    clean_doc = {k: v for k, v in doc.items() if not k.startswith("_")}
    try:
        with tempfile.NamedTemporaryFile("w", dir=target_dir, delete=False, encoding="utf-8") as tf:
            json.dump(clean_doc, tf, indent=2, ensure_ascii=False)
            tf.flush()
            os.fsync(tf.fileno())
            temp_name = tf.name
        os.replace(temp_name, file_path)
        return True
    except Exception as exc:
        logger.error("Atomic write failed for %s: %s", file_path, exc)
        return False

def bejson_load_104a(file_path: Path) -> Optional[Dict[str, Any]]:
    """Load BEJSON 104a document and strip in-memory field map cache if present."""
    if not file_path.exists():
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        if isinstance(doc, dict):
            doc.pop("_bejson_field_map", None)
            return doc
    except Exception as exc:
        logger.error("Failed loading manifest %s: %s", file_path, exc)
    return None

# Schemas
MANIFEST_FIELDS: List[Dict[str, str]] = [
    {"name": "record_uuid", "type": "string"},
    {"name": "category", "type": "string"},
    {"name": "item_name", "type": "string"},
    {"name": "original_path", "type": "string"},
    {"name": "backup_path", "type": "string"},
    {"name": "backup_filename", "type": "string"},
    {"name": "item_type", "type": "string"},
    {"name": "sha256", "type": "string"},
    {"name": "byte_size", "type": "integer"},
    {"name": "file_mode", "type": "string"},
    {"name": "timestamp", "type": "string"}
]

PROFILE_REGISTRY_FIELDS: List[Dict[str, str]] = [
    {"name": "profile_name", "type": "string"},
    {"name": "profile_label", "type": "string"},
    {"name": "profile_dir", "type": "string"},
    {"name": "config_path", "type": "string"},
    {"name": "is_active", "type": "boolean"},
    {"name": "created_at", "type": "string"},
    {"name": "last_used", "type": "string"}
]

CONFIG_RULE_FIELDS: List[Dict[str, str]] = [
    {"name": "rule_id", "type": "string"},
    {"name": "category", "type": "string"},
    {"name": "source_path", "type": "string"},
    {"name": "extension_filter", "type": "string"},
    {"name": "is_recursive", "type": "boolean"},
    {"name": "pack_type", "type": "string"},
    {"name": "target_subfolder", "type": "string"}
]

SLOT_REGISTRY_FIELDS: List[Dict[str, str]] = [
    {"name": "slot_id", "type": "integer"},
    {"name": "slot_name", "type": "string"},
    {"name": "slot_dir", "type": "string"},
    {"name": "slot_label", "type": "string"},
    {"name": "is_active", "type": "boolean"},
    {"name": "is_emergency", "type": "boolean"},
    {"name": "item_count", "type": "integer"},
    {"name": "last_saved", "type": "string"},
    {"name": "last_loaded", "type": "string"}
]

# ---------------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------------
def compute_sha256(file_path: Path) -> str:
    """Compute SHA256 checksum of a file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()

def zip_directory(source_dir: Path, output_zip: Path) -> None:
    """Create a deterministic single-tier ZIP archive from a directory."""
    temp_zip = output_zip.with_suffix(".tmp.zip")
    if temp_zip.exists():
        temp_zip.unlink()
    with zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(source_dir):
            dirs[:] = [d for d in dirs if d not in PRUNE_DIRS]
            for file in sorted(files):
                if file.endswith((".pyc", ".pyo", ".tmp")):
                    continue
                file_path = Path(root) / file
                archive_name = file_path.relative_to(source_dir)
                zf.write(file_path, archive_name)
    os.replace(temp_zip, output_zip)

ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;]*[mK]')

def strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences from string."""
    return ANSI_ESCAPE_RE.sub('', text)

def visible_length(text: str) -> int:
    """Calculate visible string length excluding ANSI escape codes."""
    return len(strip_ansi(text))

def clip_ansi_49(text: str, max_visible: int = 49) -> str:
    """Clip formatted string to max_visible columns preserving ANSI styling."""
    if visible_length(text) <= max_visible:
        return text
    tokens = ANSI_ESCAPE_RE.split(text)
    escapes = ANSI_ESCAPE_RE.findall(text)
    result: List[str] = []
    vis_count = 0
    for i, tok in enumerate(tokens):
        if vis_count + len(tok) <= max_visible:
            result.append(tok)
            vis_count += len(tok)
        else:
            remaining = max_visible - vis_count
            result.append(tok[:remaining])
            vis_count += remaining
            break
        if i < len(escapes):
            result.append(escapes[i])
    result.append(C_RESET)
    return "".join(result)

def print_49(line: str) -> None:
    """Format and print text clipped to 49 visible characters."""
    sys.stdout.write(clip_ansi_49(line, 49) + "\n")

def format_positive_feedback(msg: str) -> str:
    """Bold White, ALL CAPS with [✓] per design-terminal-cli."""
    return f"{C_WHITE}[✓] {msg.upper()}{C_RESET}"

def format_error_feedback(msg: str) -> str:
    """Bold Red, lowercase with [X] per design-terminal-cli."""
    return f"{C_BOLD_RED}[X] {msg.lower()}{C_RESET}"

def format_neutral_feedback(msg: str) -> str:
    """Neutral status with [*] per design-terminal-cli."""
    return f"{C_CYAN}[*]{C_RESET} {msg}"

def render_banner(title: str) -> None:
    """Render 49-column title banner with Tri-Color red accenting."""
    print_49(f"{C_GRAY}{DIVIDER_49}{C_RESET}")
    clean_title = strip_ansi(title)
    pad_left = max(0, (49 - len(clean_title)) // 2)
    pad_right = max(0, 49 - len(clean_title) - pad_left)
    print_49(f"{' ' * pad_left}{C_BOLD_RED}{clean_title}{C_RESET}{' ' * pad_right}")
    print_49(f"{C_GRAY}{SUBDIVIDER_49}{C_RESET}")

def render_footer() -> None:
    """Render 49-column footer."""
    print_49(f"{C_GRAY}{DIVIDER_49}{C_RESET}")

# ---------------------------------------------------------------------------
# Profile Management & MFDB Registry
# ---------------------------------------------------------------------------
def get_slot_folder_name(profile_name: str, slot_id: int) -> str:
    """Return slot folder name formatted as <profile>-Slot<id> or <profile>-Emergency."""
    if slot_id == EMERGENCY_SLOT_ID:
        return f"{profile_name}-Emergency"
    return f"{profile_name}-Slot{slot_id}"

def init_master_profiles_registry() -> Dict[str, Any]:
    """Initialize or load the master profiles registry."""
    SLOTS_BASE_DIR.mkdir(parents=True, exist_ok=True)
    if PROFILES_REGISTRY_PATH.exists():
        doc = bejson_load_104a(PROFILES_REGISTRY_PATH)
        if doc and "Values" in doc:
            return doc

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    # Default profiles: 'agy' and 'skills'
    agy_dir = SLOTS_BASE_DIR / "agy"
    skills_dir = SLOTS_BASE_DIR / "skills"

    values = [
        [
            "agy",
            "Antigravity Ecosystem",
            str(agy_dir),
            str(agy_dir / "config.104a.bejson"),
            True,
            now,
            now
        ],
        [
            "skills",
            "Dedicated Skills Suite",
            str(skills_dir),
            str(skills_dir / "config.104a.bejson"),
            False,
            now,
            ""
        ]
    ]

    doc = bejson_create_104a(
        record_type="ProfileRecord",
        fields=PROFILE_REGISTRY_FIELDS,
        values=values,
        Active_Profile="agy",
        Last_Updated=now
    )
    bejson_atomic_write(PROFILES_REGISTRY_PATH, doc)

    # Initialize default profile configs
    init_profile_config("agy", "Antigravity Ecosystem")
    init_profile_config("skills", "Dedicated Skills Suite")

    return doc

def init_profile_config(profile_name: str, label: str = "") -> Path:
    """Create or load the profile's config.104a.bejson specifying path rules."""
    prof_dir = SLOTS_BASE_DIR / profile_name
    prof_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = prof_dir / "config.104a.bejson"

    if cfg_path.exists():
        return cfg_path

    values: List[List[Any]] = []
    if profile_name == "skills":
        values = [
            ["rule_skills_home", "skills", str(HOME_DIR / ".gemini/config/skills"), "", False, "dir_zip", "skills"],
            ["rule_skills_internal", "skills", "/storage/emulated/0/Documents/AGY/skills", "", False, "dir_zip", "skills"],
            ["rule_skills_dev", "skills", "/storage/emulated/0/Admin/Dev/Skills/agy-consolidated/skills", "", False, "dir_zip", "skills"],
        ]
    elif profile_name == "agy":
        values = [
            ["rule_agy_skills", "skills", str(HOME_DIR / ".gemini/config/skills"), "", False, "dir_zip", "skills"],
            ["rule_agy_hooks", "hooks", str(HOME_DIR / ".gemini/config/.agents/hooks"), ".py", False, "file", "hooks"],
            ["rule_agy_hooks_json", "hooks", str(HOME_DIR / ".gemini/config/.agents/hooks.json"), ".json", False, "file", "hooks"],
            ["rule_agy_rules", "rules", str(HOME_DIR / ".gemini/GEMINI.md"), ".md", False, "file", "rules"],
            ["rule_agy_subagents", "subagents", str(HOME_DIR / ".gemini/antigravity-cli/agents"), ".md", False, "file", "subagents"],
            ["rule_agy_markdown", "markdown", str(HOME_DIR / ".gemini"), ".md", True, "file", "markdown"],
        ]
    else:
        # Default starter rule
        values = [
            [f"rule_{profile_name}_default", "data", str(HOME_DIR), "", False, "file", "data"]
        ]

    doc = bejson_create_104a(
        record_type="PathRuleRecord",
        fields=CONFIG_RULE_FIELDS,
        values=values,
        Profile_Name=profile_name,
        Profile_Label=label or profile_name,
        Created_At=datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    bejson_atomic_write(cfg_path, doc)
    return cfg_path

def init_profile_slots_registry(profile_name: str) -> Dict[str, Any]:
    """Initialize or load the slots registry for a specific profile."""
    prof_dir = SLOTS_BASE_DIR / profile_name
    reg_path = prof_dir / "slots_registry.104a.bejson"
    if reg_path.exists():
        doc = bejson_load_104a(reg_path)
        if doc and "Values" in doc:
            return doc

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    values: List[List[Any]] = []

    # Migrate old legacy slots if profile is 'agy' and old slots exist in ~/agy-slots
    for sid in range(1, TOTAL_REGULAR_SLOTS + 1):
        sname = get_slot_folder_name(profile_name, sid)
        sdir = prof_dir / sname
        sdir.mkdir(parents=True, exist_ok=True)

        # Check for legacy root slot to migrate
        legacy_dir = SLOTS_BASE_DIR / f"Agy-Slot{sid}"
        if profile_name == "agy" and legacy_dir.exists() and not (sdir / "manifest.104a.bejson").exists():
            shutil.copytree(legacy_dir, sdir, dirs_exist_ok=True)

        cnt = 0
        manifest = sdir / "manifest.104a.bejson"
        if manifest.exists():
            mdoc = bejson_load_104a(manifest)
            cnt = len(mdoc.get("Values", [])) if mdoc else 0

        is_act = (sid == 1 and cnt > 0)
        label = "Production Baseline" if sid == 1 else f"Empty Slot {sid}"
        values.append([
            sid,
            sname,
            str(sdir),
            label,
            is_act,
            False,
            cnt,
            now if cnt > 0 else "",
            now if is_act else ""
        ])

    # Emergency slot
    em_name = get_slot_folder_name(profile_name, EMERGENCY_SLOT_ID)
    em_dir = prof_dir / em_name
    em_dir.mkdir(parents=True, exist_ok=True)

    legacy_em = SLOTS_BASE_DIR / "Agy-Emergency"
    if profile_name == "agy" and legacy_em.exists() and not (em_dir / "manifest.104a.bejson").exists():
        shutil.copytree(legacy_em, em_dir, dirs_exist_ok=True)

    em_cnt = 0
    em_manifest = em_dir / "manifest.104a.bejson"
    if em_manifest.exists():
        em_doc = bejson_load_104a(em_manifest)
        em_cnt = len(em_doc.get("Values", [])) if em_doc else 0

    values.append([
        EMERGENCY_SLOT_ID,
        em_name,
        str(em_dir),
        "Master Emergency Golden Image",
        False,
        True,
        em_cnt,
        now if em_cnt > 0 else "",
        ""
    ])

    doc = bejson_create_104a(
        record_type="SlotRecord",
        fields=SLOT_REGISTRY_FIELDS,
        values=values,
        Profile_Name=profile_name,
        Active_Slot_ID=1 if values[0][4] else 0,
        Emergency_Restored_Flag=False,
        Last_Updated=now
    )
    bejson_atomic_write(reg_path, doc)
    return doc

def get_active_profile_name() -> str:
    """Retrieve name of current active profile from master registry."""
    doc = init_master_profiles_registry()
    return doc.get("Active_Profile", "agy")

def set_active_profile_name(profile_name: str) -> None:
    """Set active profile in master registry."""
    doc = init_master_profiles_registry()
    field_map = bejson_get_field_map(doc)
    p_idx = field_map["profile_name"]
    act_idx = field_map["is_active"]
    found = False

    for row in doc.get("Values", []):
        if row[p_idx] == profile_name:
            row[act_idx] = True
            row[field_map["last_used"]] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            found = True
        else:
            row[act_idx] = False

    if not found:
        raise ValueError(f"Profile '{profile_name}' does not exist.")

    doc["Active_Profile"] = profile_name
    doc["Last_Updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    bejson_atomic_write(PROFILES_REGISTRY_PATH, doc)

# ---------------------------------------------------------------------------
# Config-Driven Snapshot Discovery Engine
# ---------------------------------------------------------------------------
def execute_config_discovery(config_doc: Dict[str, Any]) -> Dict[str, List[Path]]:
    """Scan file system strictly adhering to path rules and extension filters."""
    field_map = bejson_get_field_map(config_doc)
    categories: Dict[str, List[Path]] = {}

    for row in config_doc.get("Values", []):
        cat = row[field_map["category"]]
        src_str = row[field_map["source_path"]]
        ext_filter = (row[field_map["extension_filter"]] or "").strip().lower()
        is_rec = bool(row[field_map["is_recursive"]])
        pack_type = row[field_map["pack_type"]]

        src_path = Path(src_str).resolve()
        if not src_path.exists():
            continue

        if cat not in categories:
            categories[cat] = []

        if src_path.is_file():
            # Single file rule
            if not ext_filter or src_path.name.lower().endswith(ext_filter):
                if src_path not in categories[cat]:
                    categories[cat].append(src_path)

        elif src_path.is_dir():
            if pack_type == "dir_zip":
                # Treat subdirectories as standalone packages (e.g. skills)
                for item in src_path.iterdir():
                    if item.name.startswith("skills_backup_") or item.name in PRUNE_DIRS:
                        continue
                    if item not in categories[cat]:
                        categories[cat].append(item.resolve())
            else:
                # Regular directory scanning
                if is_rec:
                    for root, dirs, files in os.walk(src_path):
                        dirs[:] = [d for d in dirs if d not in PRUNE_DIRS]
                        for file in files:
                            fl = file.lower()
                            if not ext_filter or fl.endswith(ext_filter):
                                p = Path(root) / file
                                if p.is_file() and not p.is_symlink() and "backup-nov11" not in str(p) and "agy-slots" not in str(p):
                                    resolved = p.resolve()
                                    if resolved not in categories[cat]:
                                        categories[cat].append(resolved)
                else:
                    for item in src_path.iterdir():
                        if item.is_file() and not item.is_symlink():
                            fl = item.name.lower()
                            if not ext_filter or fl.endswith(ext_filter):
                                resolved = item.resolve()
                                if resolved not in categories[cat]:
                                    categories[cat].append(resolved)

    return categories

# ---------------------------------------------------------------------------
# Universal Slot Operations (Load, Save, Copy, Export, Import)
# ---------------------------------------------------------------------------
def get_slot_record(doc: Dict[str, Any], slot_id: int) -> Optional[List[Any]]:
    """Retrieve row for slot_id from slots registry document."""
    field_map = bejson_get_field_map(doc)
    id_idx = field_map.get("slot_id", 0)
    for row in doc.get("Values", []):
        if row[id_idx] == slot_id:
            return row
    return None

def universal_slot_save(profile_name: str, slot_id: int, label: Optional[str] = None) -> Dict[str, Any]:
    """Execute snapshot against profile configuration and save into slot."""
    doc = init_profile_slots_registry(profile_name)
    field_map = bejson_get_field_map(doc)

    if slot_id == EMERGENCY_SLOT_ID:
        active_id = doc.get("Active_Slot_ID", 0)
        em_restored = doc.get("Emergency_Restored_Flag", False)
        if active_id != 0 or not em_restored:
            raise PermissionError(
                f"E_EMERGENCY_PROTECTION: {profile_name}-Emergency is write-protected. "
                f"You can only overwrite it after running emergency-restore and "
                f"ensuring no experimental slot is active."
            )

    # Locate slot row
    id_idx = field_map["slot_id"]
    target_row = None
    for row in doc.get("Values", []):
        if row[id_idx] == slot_id:
            target_row = row
            break
    if not target_row:
        raise ValueError(f"Invalid slot ID {slot_id} for profile {profile_name}")

    slot_dir = Path(target_row[field_map["slot_dir"]])
    slot_dir.mkdir(parents=True, exist_ok=True)

    # Load profile config
    prof_dir = SLOTS_BASE_DIR / profile_name
    cfg_doc = bejson_load_104a(prof_dir / "config.104a.bejson")
    if not cfg_doc:
        raise FileNotFoundError(f"Missing configuration for profile {profile_name}")

    categories = execute_config_discovery(cfg_doc)
    master_records: List[List[Any]] = []
    category_summary: Dict[str, int] = {}

    for cat_name, source_paths in categories.items():
        cat_dir = slot_dir / cat_name
        cat_dir.mkdir(parents=True, exist_ok=True)
        cat_records: List[List[Any]] = []

        for src in source_paths:
            rec_uuid = str(uuid.uuid4())
            item_name = src.name
            timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

            if src.is_dir():
                backup_filename = f"{src.name}_{rec_uuid}.zip"
                dest_path = cat_dir / backup_filename
                item_type = "directory_zip"
                file_mode = "0755"
                zip_directory(src, dest_path)
                sha256_val = compute_sha256(dest_path)
                byte_size = dest_path.stat().st_size
            else:
                stem = src.stem
                suffix = src.suffix
                backup_filename = f"{stem}_{rec_uuid}{suffix}"
                dest_path = cat_dir / backup_filename
                item_type = "file"
                shutil.copy2(src, dest_path)
                sha256_val = compute_sha256(dest_path)
                byte_size = dest_path.stat().st_size
                file_mode = oct(src.stat().st_mode & 0o777)

            row = [
                rec_uuid,
                cat_name,
                item_name,
                str(src),
                str(dest_path),
                backup_filename,
                item_type,
                sha256_val,
                byte_size,
                file_mode,
                timestamp
            ]
            cat_records.append(row)
            master_records.append(row)

        category_summary[cat_name] = len(cat_records)

        # Write category manifest
        if cat_records:
            cat_manifest = bejson_create_104a(
                record_type="BackupRecord",
                fields=MANIFEST_FIELDS,
                values=cat_records,
                Category=cat_name,
                Total_Records=len(cat_records),
                Backup_Timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
            )
            bejson_atomic_write(cat_dir / "manifest.104a.bejson", cat_manifest)

    # Write Master Slot Manifest
    if master_records:
        master_manifest = bejson_create_104a(
            record_type="BackupRecord",
            fields=MANIFEST_FIELDS,
            values=master_records,
            Profile=profile_name,
            Slot_ID=slot_id,
            Backup_Root=str(slot_dir),
            Total_Records=len(master_records),
            Category_Summary=category_summary,
            Backup_Timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
        )
        bejson_atomic_write(slot_dir / "manifest.104a.bejson", master_manifest)

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    target_row[field_map["item_count"]] = len(master_records)
    target_row[field_map["last_saved"]] = now
    if label:
        target_row[field_map["slot_label"]] = label

    doc["Last_Updated"] = now
    bejson_atomic_write(prof_dir / "slots_registry.104a.bejson", doc)

    return {
        "status": "success",
        "profile": profile_name,
        "slot_id": slot_id,
        "items": len(master_records),
        "summary": category_summary
    }

def universal_slot_load(profile_name: str, slot_id: int, auto_save_current: bool = False, force: bool = False) -> Dict[str, Any]:
    """Disc Changer: Unload live components and load selected slot for profile."""
    prof_dir = SLOTS_BASE_DIR / profile_name
    doc = init_profile_slots_registry(profile_name)
    field_map = bejson_get_field_map(doc)

    id_idx = field_map["slot_id"]
    target_row = None
    for row in doc.get("Values", []):
        if row[id_idx] == slot_id:
            target_row = row
            break
    if not target_row:
        raise ValueError(f"Invalid slot ID {slot_id} for profile {profile_name}")

    slot_dir = Path(target_row[field_map["slot_dir"]])
    manifest_path = slot_dir / "manifest.104a.bejson"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Slot {slot_id} is empty (no manifest at {manifest_path})")

    active_id = doc.get("Active_Slot_ID", 0)
    if auto_save_current and active_id in range(1, TOTAL_REGULAR_SLOTS + 1):
        universal_slot_save(profile_name, active_id)

    # Load slot manifest
    m_doc = bejson_load_104a(manifest_path)
    if not m_doc:
        raise ValueError(f"Corrupt manifest in {manifest_path}")

    m_map = bejson_get_field_map(m_doc)
    restored_count = 0

    # Unload & Restore tracked files
    for row in m_doc.get("Values", []):
        orig_path = Path(row[m_map["original_path"]])
        backup_path = Path(row[m_map["backup_path"]])
        item_type = row[m_map["item_type"]]
        expected_sha = row[m_map["sha256"]]
        file_mode_str = row[m_map["file_mode"]]

        if not backup_path.exists():
            continue

        actual_sha = compute_sha256(backup_path)
        if actual_sha != expected_sha and not force:
            continue

        orig_path.parent.mkdir(parents=True, exist_ok=True)
        if item_type == "directory_zip":
            if orig_path.exists():
                shutil.rmtree(orig_path, ignore_errors=True)
            orig_path.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(backup_path, "r") as zf:
                zf.extractall(orig_path)
        else:
            with tempfile.NamedTemporaryFile("wb", dir=orig_path.parent, delete=False) as tf:
                with open(backup_path, "rb") as bf:
                    shutil.copyfileobj(bf, tf)
                temp_name = tf.name
            os.replace(temp_name, orig_path)
            try:
                orig_path.chmod(int(file_mode_str, 8))
            except Exception:
                pass

        restored_count += 1

    # Update slot registry active states
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for row in doc.get("Values", []):
        sid = row[id_idx]
        if sid == slot_id:
            row[field_map["is_active"]] = True
            row[field_map["last_loaded"]] = now
        else:
            row[field_map["is_active"]] = False

    doc["Active_Slot_ID"] = slot_id
    if slot_id != EMERGENCY_SLOT_ID:
        doc["Emergency_Restored_Flag"] = False

    doc["Last_Updated"] = now
    bejson_atomic_write(prof_dir / "slots_registry.104a.bejson", doc)
    set_active_profile_name(profile_name)

    return {
        "status": "success",
        "profile": profile_name,
        "previous_slot": active_id,
        "active_slot": slot_id,
        "restored": restored_count
    }

def universal_slot_emergency_restore(profile_name: str) -> Dict[str, Any]:
    """Restore Emergency Slot 11, setting active slot to 0 and unlocking emergency-save."""
    res = universal_slot_load(profile_name, EMERGENCY_SLOT_ID, auto_save_current=False, force=True)
    prof_dir = SLOTS_BASE_DIR / profile_name
    doc = init_profile_slots_registry(profile_name)
    field_map = bejson_get_field_map(doc)

    for row in doc.get("Values", []):
        row[field_map["is_active"]] = False

    doc["Active_Slot_ID"] = 0
    doc["Emergency_Restored_Flag"] = True
    doc["Last_Updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    bejson_atomic_write(prof_dir / "slots_registry.104a.bejson", doc)

    return {
        "status": "success",
        "profile": profile_name,
        "restored": res["restored"],
        "message": f"Restored {profile_name}-Emergency. Neutral baseline active."
    }

def create_new_profile(profile_name: str, label: str = "") -> Dict[str, Any]:
    """Create a new profile set with its own 10 slots + 1 emergency slot and config."""
    clean_name = profile_name.strip().lower().replace(" ", "_")
    doc = init_master_profiles_registry()
    field_map = bejson_get_field_map(doc)

    for row in doc.get("Values", []):
        if row[field_map["profile_name"]] == clean_name:
            raise ValueError(f"Profile '{clean_name}' already exists.")

    prof_dir = SLOTS_BASE_DIR / clean_name
    prof_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = init_profile_config(clean_name, label or clean_name)
    init_profile_slots_registry(clean_name)

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    doc.get("Values", []).append([
        clean_name,
        label or clean_name,
        str(prof_dir),
        str(cfg_path),
        False,
        now,
        ""
    ])
    doc["Last_Updated"] = now
    bejson_atomic_write(PROFILES_REGISTRY_PATH, doc)

    return {
        "status": "success",
        "profile_name": clean_name,
        "profile_dir": str(prof_dir),
        "config_path": str(cfg_path)
    }

def delete_profile(profile_name: str) -> bool:
    """Delete a profile and its slot directories (cannot delete 'agy')."""
    clean_name = profile_name.strip().lower()
    if clean_name == "agy":
        raise ValueError("Cannot delete core system profile 'agy'")
    doc = init_master_profiles_registry()
    field_map = bejson_get_field_map(doc)
    p_idx = field_map["profile_name"]

    orig_len = len(doc.get("Values", []))
    doc["Values"] = [r for r in doc.get("Values", []) if r[p_idx] != clean_name]
    if len(doc["Values"]) < orig_len:
        if doc.get("Active_Profile") == clean_name:
            doc["Active_Profile"] = "agy"
        doc["Last_Updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        bejson_atomic_write(PROFILES_REGISTRY_PATH, doc)
        prof_dir = SLOTS_BASE_DIR / clean_name
        if prof_dir.exists():
            shutil.rmtree(prof_dir, ignore_errors=True)
        return True
    return False

def universal_slot_copy(profile_name: str, src_id: int, dst_id: int) -> Dict[str, Any]:
    """Copy contents of one slot to another within the profile."""
    if dst_id == EMERGENCY_SLOT_ID:
        raise PermissionError("E_EMERGENCY_PROTECTION: Cannot copy directly into Slot 11.")
    prof_dir = SLOTS_BASE_DIR / profile_name
    doc = init_profile_slots_registry(profile_name)
    field_map = bejson_get_field_map(doc)

    src_row = get_slot_record(doc, src_id)
    dst_row = get_slot_record(doc, dst_id)
    if not src_row or not dst_row:
        raise ValueError("Source or destination slot ID is invalid.")

    src_dir = Path(src_row[field_map["slot_dir"]])
    dst_dir = Path(dst_row[field_map["slot_dir"]])

    if not (src_dir / "manifest.104a.bejson").exists():
        raise FileNotFoundError(f"Source slot {src_id} is empty.")

    if dst_dir.exists():
        shutil.rmtree(dst_dir, ignore_errors=True)
    shutil.copytree(src_dir, dst_dir)

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    dst_row[field_map["item_count"]] = src_row[field_map["item_count"]]
    dst_row[field_map["last_saved"]] = now
    dst_row[field_map["slot_label"]] = f"Copy of Slot {src_id} ({src_row[field_map['slot_label']]})"

    doc["Last_Updated"] = now
    bejson_atomic_write(prof_dir / "slots_registry.104a.bejson", doc)
    return {
        "status": "success",
        "profile": profile_name,
        "src_id": src_id,
        "dst_id": dst_id,
        "items": dst_row[field_map["item_count"]]
    }

def universal_slot_export(profile_name: str, slot_id: int, out_zip: Path) -> Path:
    """Export slot to a portable ZIP package."""
    prof_dir = SLOTS_BASE_DIR / profile_name
    doc = init_profile_slots_registry(profile_name)
    field_map = bejson_get_field_map(doc)
    row = get_slot_record(doc, slot_id)
    if not row:
        raise ValueError(f"Invalid slot ID: {slot_id}")
    slot_dir = Path(row[field_map["slot_dir"]])
    if not (slot_dir / "manifest.104a.bejson").exists():
        raise FileNotFoundError(f"Slot {slot_id} is empty.")

    out_zip.parent.mkdir(parents=True, exist_ok=True)
    temp_zip = out_zip.with_suffix(".tmp.zip")
    with zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(slot_dir):
            for file in files:
                fpath = Path(root) / file
                arcname = fpath.relative_to(slot_dir)
                zf.write(fpath, arcname)
    os.replace(temp_zip, out_zip)
    return out_zip

def universal_slot_import(profile_name: str, in_zip: Path, slot_id: int, label: Optional[str] = None) -> Dict[str, Any]:
    """Import a slot ZIP package into designated slot."""
    if slot_id == EMERGENCY_SLOT_ID:
        raise PermissionError("E_EMERGENCY_PROTECTION: Direct zip import into Slot 11 is forbidden.")
    if not in_zip.exists():
        raise FileNotFoundError(f"Input package does not exist: {in_zip}")

    prof_dir = SLOTS_BASE_DIR / profile_name
    doc = init_profile_slots_registry(profile_name)
    field_map = bejson_get_field_map(doc)
    row = get_slot_record(doc, slot_id)
    if not row:
        raise ValueError(f"Invalid slot ID: {slot_id}")

    slot_dir = Path(row[field_map["slot_dir"]])
    if slot_dir.exists():
        shutil.rmtree(slot_dir, ignore_errors=True)
    slot_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(in_zip, "r") as zf:
        zf.extractall(slot_dir)

    manifest_path = slot_dir / "manifest.104a.bejson"
    if not manifest_path.exists():
        raise ValueError("Invalid slot archive: missing manifest.104a.bejson")

    mdoc = bejson_load_104a(manifest_path)
    cnt = len(mdoc.get("Values", [])) if mdoc else 0

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    row[field_map["item_count"]] = cnt
    row[field_map["last_saved"]] = now
    if label:
        row[field_map["slot_label"]] = label

    doc["Last_Updated"] = now
    bejson_atomic_write(prof_dir / "slots_registry.104a.bejson", doc)
    return {
        "status": "success",
        "profile": profile_name,
        "slot_id": slot_id,
        "items": cnt
    }

def universal_slot_label(profile_name: str, slot_id: int, label: str) -> None:
    """Set descriptive user label for a slot."""
    prof_dir = SLOTS_BASE_DIR / profile_name
    doc = init_profile_slots_registry(profile_name)
    field_map = bejson_get_field_map(doc)
    row = get_slot_record(doc, slot_id)
    if not row:
        raise ValueError(f"Invalid slot ID: {slot_id}")
    row[field_map["slot_label"]] = label
    doc["Last_Updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    bejson_atomic_write(prof_dir / "slots_registry.104a.bejson", doc)

def profile_add_path(
    profile_name: str,
    category: str,
    source_path: str,
    extension_filter: str = "",
    is_recursive: bool = False,
    pack_type: str = "file",
    target_subfolder: str = ""
) -> Dict[str, Any]:
    """Add a new path rule to the profile's config.104a.bejson."""
    prof_dir = SLOTS_BASE_DIR / profile_name
    cfg_path = prof_dir / "config.104a.bejson"
    doc = bejson_load_104a(cfg_path)
    if not doc:
        raise FileNotFoundError(f"Configuration not found for profile '{profile_name}'")

    field_map = bejson_get_field_map(doc)
    rule_id = f"rule_{profile_name}_{category}_{int(datetime.datetime.now().timestamp())}"
    subfolder = target_subfolder or category

    new_row = [
        rule_id,
        category,
        source_path,
        extension_filter,
        is_recursive,
        pack_type,
        subfolder
    ]
    doc.get("Values", []).append(new_row)
    doc["Last_Updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    bejson_atomic_write(cfg_path, doc)
    return {
        "status": "success",
        "rule_id": rule_id,
        "category": category,
        "source_path": source_path,
        "extension_filter": extension_filter
    }

def profile_remove_path(profile_name: str, rule_id: str) -> bool:
    """Remove a path rule from profile's config.104a.bejson."""
    prof_dir = SLOTS_BASE_DIR / profile_name
    cfg_path = prof_dir / "config.104a.bejson"
    doc = bejson_load_104a(cfg_path)
    if not doc:
        raise FileNotFoundError(f"Configuration not found for profile '{profile_name}'")

    field_map = bejson_get_field_map(doc)
    r_idx = field_map["rule_id"]
    orig_len = len(doc.get("Values", []))
    doc["Values"] = [r for r in doc.get("Values", []) if r[r_idx] != rule_id]

    if len(doc["Values"]) < orig_len:
        doc["Last_Updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        bejson_atomic_write(cfg_path, doc)
        return True
    return False

# ---------------------------------------------------------------------------
# 49-Column Mobile Portrait CLI Views
# ---------------------------------------------------------------------------
def render_profiles_table() -> None:
    """Render 49-column table of available profiles with ANSI Tri-Color styling."""
    doc = init_master_profiles_registry()
    field_map = bejson_get_field_map(doc)
    active_prof = doc.get("Active_Profile", "agy")

    render_banner("UNIVERSAL SNAPSHOT PROFILES")
    print_49(f" {C_WHITE}Active Profile :{C_RESET} {C_CYAN}{active_prof}{C_RESET}")
    print_49(f"{C_GRAY}{SUBDIVIDER_49}{C_RESET}")
    print_49(f"{C_BOLD_RED}ACT  NAME         LABEL{C_RESET}")
    print_49(f"{C_GRAY}{SUBDIVIDER_49}{C_RESET}")

    for row in doc.get("Values", []):
        pname = row[field_map["profile_name"]]
        plabel = row[field_map["profile_label"]]
        is_act = (pname == active_prof)
        act_mark = f"{C_GREEN}[*]{C_RESET}" if is_act else f"{C_GRAY}[ ]{C_RESET}"
        name_str = f"{C_WHITE}{pname:<12}{C_RESET}"
        lbl_str = f"{C_CYAN}{plabel[:28]}{C_RESET}" if is_act else f"{C_GRAY}{plabel[:28]}{C_RESET}"
        print_49(f"{act_mark}  {name_str} {lbl_str}")

    render_footer()

def render_profile_slots_table(profile_name: Optional[str] = None) -> None:
    """Render 49-column slot table for a profile with ANSI Tri-Color styling."""
    if not profile_name:
        profile_name = get_active_profile_name()
    doc = init_profile_slots_registry(profile_name)
    field_map = bejson_get_field_map(doc)
    active_id = doc.get("Active_Slot_ID", 0)
    em_ok = doc.get("Emergency_Restored_Flag", False)

    render_banner(f"PROFILE: {profile_name.upper()} SLOTS")
    act_str = f"{C_GREEN}Slot {active_id}{C_RESET}" if active_id > 0 else f"{C_YELLOW}None (Neutral Baseline){C_RESET}"
    em_str = f"{C_GREEN}True{C_RESET}" if em_ok else f"{C_BOLD_RED}False (Locked){C_RESET}"
    print_49(f" {C_WHITE}Active Slot :{C_RESET} {act_str}")
    print_49(f" {C_WHITE}Emergency OK:{C_RESET} {em_str}")
    print_49(f"{C_GRAY}{SUBDIVIDER_49}{C_RESET}")
    print_49(f"{C_BOLD_RED} #  ACT  ITEMS  NAME         LABEL{C_RESET}")
    print_49(f"{C_GRAY}{SUBDIVIDER_49}{C_RESET}")

    for row in doc.get("Values", []):
        sid = row[field_map["slot_id"]]
        sname = row[field_map["slot_name"]]
        slabel = row[field_map["slot_label"]]
        is_act = row[field_map["is_active"]]
        cnt = row[field_map["item_count"]]

        act_mark = f"{C_GREEN}[*]{C_RESET}" if is_act else f"{C_GRAY}[ ]{C_RESET}"
        num_str = f"{C_WHITE}{sid:>2}{C_RESET}" if sid <= 10 else f"{C_BOLD_RED}EM{C_RESET}"
        cnt_str = f"{C_CYAN}{cnt:>5}{C_RESET}" if cnt > 0 else f"{C_GRAY}    0{C_RESET}"
        name_str = f"{C_WHITE}{sname[:11]:<11}{C_RESET}"
        lbl_str = f"{C_WHITE}{slabel[:16]}{C_RESET}" if is_act else f"{C_GRAY}{slabel[:16]}{C_RESET}"
        print_49(f"{num_str}  {act_mark}  {cnt_str}  {name_str} {lbl_str}")

    render_footer()

def render_profile_paths_table(profile_name: Optional[str] = None) -> None:
    """Render 49-column table of path rules and extension filters with ANSI styling."""
    if not profile_name:
        profile_name = get_active_profile_name()
    prof_dir = SLOTS_BASE_DIR / profile_name
    cfg_doc = bejson_load_104a(prof_dir / "config.104a.bejson")
    if not cfg_doc:
        print_49(format_error_feedback(f"no config found for profile '{profile_name}'"))
        return

    field_map = bejson_get_field_map(cfg_doc)
    render_banner(f"PATHS: {profile_name.upper()} CONFIG")
    print_49(f" {C_WHITE}Config:{C_RESET} {C_CYAN}{prof_dir / 'config.104a.bejson'}{C_RESET}")
    print_49(f"{C_GRAY}{SUBDIVIDER_49}{C_RESET}")
    print_49(f"{C_BOLD_RED}CAT      EXT   REC  PACK      PATH{C_RESET}")
    print_49(f"{C_GRAY}{SUBDIVIDER_49}{C_RESET}")

    for row in cfg_doc.get("Values", []):
        cat = row[field_map["category"]][:7]
        ext = row[field_map["extension_filter"]] or "*"
        rec = "Y" if row[field_map["is_recursive"]] else "N"
        ptype = row[field_map["pack_type"]][:7]
        sp = Path(row[field_map["source_path"]]).name
        print_49(f"{C_WHITE}{cat:<7}{C_RESET}  {C_YELLOW}{ext:<4}{C_RESET}  {C_CYAN}{rec:<3}{C_RESET}  {C_GRAY}{ptype:<7}{C_RESET}   {C_WHITE}{sp}{C_RESET}")

    render_footer()

def run_tui_menu() -> int:
    """Interactive 49-column mobile portrait TUI menu (design-terminal-menu Archetype 2)."""
    while True:
        sys.stdout.write(C_CLEAR)
        active_prof = get_active_profile_name()
        slots_doc = init_profile_slots_registry(active_prof)
        active_id = slots_doc.get("Active_Slot_ID", 0)
        act_slot_str = f"Slot {active_id}" if active_id > 0 else "Baseline"

        print_49(f"{C_GRAY}{DIVIDER_49}{C_RESET}")
        title = "CHAMBER CLI: LOADED DISC CHANGER"
        pad = max(0, (49 - len(title)) // 2)
        print_49(f"{' ' * pad}{C_BOLD_RED}{title}{C_RESET}")
        print_49(f"{C_GRAY}{SUBDIVIDER_49}{C_RESET}")
        print_49(f" {C_WHITE}Profile:{C_RESET} {C_CYAN}{active_prof:<10}{C_RESET} | {C_WHITE}Active:{C_RESET} {C_GREEN}{act_slot_str:<12}{C_RESET}")
        print_49(f"{C_GRAY}{SUBDIVIDER_49}{C_RESET}")
        print_49(f" {C_BOLD_RED}[1]{C_RESET} {C_WHITE}Slot Inventory{C_RESET}     {C_BOLD_RED}[5]{C_RESET} {C_WHITE}Export Slot Zip{C_RESET}")
        print_49(f" {C_BOLD_RED}[2]{C_RESET} {C_WHITE}Load / Switch Slot{C_RESET} {C_BOLD_RED}[6]{C_RESET} {C_WHITE}Import Slot Zip{C_RESET}")
        print_49(f" {C_BOLD_RED}[3]{C_RESET} {C_WHITE}Save Active State{C_RESET}  {C_BOLD_RED}[7]{C_RESET} {C_WHITE}Rename Label{C_RESET}")
        print_49(f" {C_BOLD_RED}[4]{C_RESET} {C_WHITE}Clone / Copy Slot{C_RESET}  {C_BOLD_RED}[8]{C_RESET} {C_WHITE}Emergency Restor{C_RESET}")
        print_49(f"{C_GRAY}{SUBDIVIDER_49}{C_RESET}")
        print_49(f" {C_BOLD_RED}[P]{C_RESET} {C_WHITE}Switch Profile{C_RESET}    {C_BOLD_RED}[V]{C_RESET} {C_WHITE}View Path Rules{C_RESET}")
        print_49(f" {C_BOLD_RED}[N]{C_RESET} {C_WHITE}New Profile{C_RESET}       {C_BOLD_RED}[A]{C_RESET} {C_WHITE}Add Path Rule{C_RESET}")
        print_49(f" {C_BOLD_RED}[Q]{C_RESET} {C_WHITE}Quit Chamber CLI{C_RESET}")
        print_49(f"{C_GRAY}{DIVIDER_49}{C_RESET}")

        try:
            choice = input(f" {C_BOLD_RED}Action (Enter choice) > {C_RESET}").strip().upper()
        except (KeyboardInterrupt, EOFError):
            print("\n")
            return 0

        if choice == "Q":
            sys.stdout.write(f"\n{format_neutral_feedback('Exiting Chamber CLI. Standing by.')}\n")
            return 0
        elif choice == "1":
            sys.stdout.write(C_CLEAR)
            render_profile_slots_table(active_prof)
            input(f"\n {C_GRAY}Press [Enter] to return to menu...{C_RESET}")
        elif choice == "2":
            sys.stdout.write(C_CLEAR)
            render_profile_slots_table(active_prof)
            try:
                s_in = input(f"\n {C_WHITE}Enter Slot number to load (1-10 or 11): {C_RESET}").strip()
                if s_in.isdigit():
                    sid = int(s_in)
                    res = universal_slot_load(active_prof, sid)
                    print(format_positive_feedback(f"LOADED SLOT {sid} ({res['restored']} RECORDS)"))
                else:
                    print(format_error_feedback("invalid slot number"))
            except Exception as e:
                print(format_error_feedback(str(e)))
            input(f"\n {C_GRAY}Press [Enter] to continue...{C_RESET}")
        elif choice == "3":
            sys.stdout.write(C_CLEAR)
            render_profile_slots_table(active_prof)
            try:
                s_in = input(f"\n {C_WHITE}Enter Slot number to save into (1-10 or 11): {C_RESET}").strip()
                if s_in.isdigit():
                    sid = int(s_in)
                    lbl = input(f" {C_WHITE}Enter optional label (or leave blank): {C_RESET}").strip()
                    res = universal_slot_save(active_prof, sid, label=lbl or None)
                    print(format_positive_feedback(f"SAVED ACTIVE STATE TO SLOT {sid} ({res['items']} ITEMS)"))
                else:
                    print(format_error_feedback("invalid slot number"))
            except Exception as e:
                print(format_error_feedback(str(e)))
            input(f"\n {C_GRAY}Press [Enter] to continue...{C_RESET}")
        elif choice == "4":
            sys.stdout.write(C_CLEAR)
            render_profile_slots_table(active_prof)
            try:
                src_in = input(f"\n {C_WHITE}Source Slot (1-11): {C_RESET}").strip()
                dst_in = input(f" {C_WHITE}Destination Slot (1-10): {C_RESET}").strip()
                if src_in.isdigit() and dst_in.isdigit():
                    res = universal_slot_copy(active_prof, int(src_in), int(dst_in))
                    print(format_positive_feedback(f"COPIED SLOT {res['src_id']} TO SLOT {res['dst_id']}"))
                else:
                    print(format_error_feedback("invalid slot IDs"))
            except Exception as e:
                print(format_error_feedback(str(e)))
            input(f"\n {C_GRAY}Press [Enter] to continue...{C_RESET}")
        elif choice == "5":
            sys.stdout.write(C_CLEAR)
            render_profile_slots_table(active_prof)
            try:
                s_in = input(f"\n {C_WHITE}Slot number to export (1-11): {C_RESET}").strip()
                out_p = input(f" {C_WHITE}Output ZIP path: {C_RESET}").strip()
                if s_in.isdigit() and out_p:
                    out_path = universal_slot_export(active_prof, int(s_in), Path(out_p))
                    print(format_positive_feedback(f"EXPORTED TO {out_path.name}"))
                else:
                    print(format_error_feedback("invalid slot or zip path"))
            except Exception as e:
                print(format_error_feedback(str(e)))
            input(f"\n {C_GRAY}Press [Enter] to continue...{C_RESET}")
        elif choice == "6":
            sys.stdout.write(C_CLEAR)
            render_profile_slots_table(active_prof)
            try:
                in_p = input(f"\n {C_WHITE}Input ZIP path: {C_RESET}").strip()
                s_in = input(f" {C_WHITE}Target Slot (1-10): {C_RESET}").strip()
                lbl = input(f" {C_WHITE}Optional Label: {C_RESET}").strip()
                if in_p and s_in.isdigit():
                    res = universal_slot_import(active_prof, Path(in_p), int(s_in), label=lbl or None)
                    print(format_positive_feedback(f"IMPORTED {res['items']} ITEMS INTO SLOT {res['slot_id']}"))
                else:
                    print(format_error_feedback("invalid slot or zip path"))
            except Exception as e:
                print(format_error_feedback(str(e)))
            input(f"\n {C_GRAY}Press [Enter] to continue...{C_RESET}")
        elif choice == "7":
            sys.stdout.write(C_CLEAR)
            render_profile_slots_table(active_prof)
            try:
                s_in = input(f"\n {C_WHITE}Slot number (1-11): {C_RESET}").strip()
                lbl = input(f" {C_WHITE}New Label: {C_RESET}").strip()
                if s_in.isdigit() and lbl:
                    universal_slot_label(active_prof, int(s_in), lbl)
                    print(format_positive_feedback("UPDATED SLOT LABEL"))
                else:
                    print(format_error_feedback("invalid slot or label"))
            except Exception as e:
                print(format_error_feedback(str(e)))
            input(f"\n {C_GRAY}Press [Enter] to continue...{C_RESET}")
        elif choice == "8":
            sys.stdout.write(C_CLEAR)
            try:
                conf = input(f" {C_BOLD_RED}Restore Emergency Baseline and Unlock Slot 11? (y/N): {C_RESET}").strip().lower()
                if conf == "y":
                    res = universal_slot_emergency_restore(active_prof)
                    print(format_positive_feedback(f"EMERGENCY RESTORE COMPLETE ({res['restored']} RECORDS)"))
                else:
                    print(format_neutral_feedback("Emergency restore cancelled."))
            except Exception as e:
                print(format_error_feedback(str(e)))
            input(f"\n {C_GRAY}Press [Enter] to continue...{C_RESET}")
        elif choice == "P":
            sys.stdout.write(C_CLEAR)
            render_profiles_table()
            try:
                p_in = input(f"\n {C_WHITE}Enter profile name to activate: {C_RESET}").strip()
                if p_in:
                    set_active_profile_name(p_in)
                    print(format_positive_feedback(f"SWITCHED ACTIVE PROFILE TO '{p_in}'"))
            except Exception as e:
                print(format_error_feedback(str(e)))
            input(f"\n {C_GRAY}Press [Enter] to continue...{C_RESET}")
        elif choice == "V":
            sys.stdout.write(C_CLEAR)
            render_profile_paths_table(active_prof)
            input(f"\n {C_GRAY}Press [Enter] to continue...{C_RESET}")
        elif choice == "N":
            sys.stdout.write(C_CLEAR)
            try:
                n_name = input(f" {C_WHITE}New Profile Name: {C_RESET}").strip()
                n_lbl = input(f" {C_WHITE}Descriptive Label: {C_RESET}").strip()
                if n_name:
                    res = create_new_profile(n_name, label=n_lbl)
                    print(format_positive_feedback(f"CREATED PROFILE '{res['profile_name']}'"))
            except Exception as e:
                print(format_error_feedback(str(e)))
            input(f"\n {C_GRAY}Press [Enter] to continue...{C_RESET}")
        elif choice == "A":
            sys.stdout.write(C_CLEAR)
            try:
                cat = input(f" {C_WHITE}Category (e.g. skills, hooks, rules): {C_RESET}").strip()
                sp = input(f" {C_WHITE}Source Path: {C_RESET}").strip()
                ext = input(f" {C_WHITE}Extension Filter (e.g. .py or empty): {C_RESET}").strip()
                if cat and sp:
                    res = profile_add_path(active_prof, cat, sp, extension_filter=ext)
                    print(format_positive_feedback(f"PATH RULE ADDED ({res['rule_id']})"))
                else:
                    print(format_error_feedback("category and source path required"))
            except Exception as e:
                print(format_error_feedback(str(e)))
            input(f"\n {C_GRAY}Press [Enter] to continue...{C_RESET}")
        else:
            print(format_error_feedback(f"unknown command: '{choice}'. select from menu options."))
            input(f"\n {C_GRAY}Press [Enter] to continue...{C_RESET}")

# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Universal Config-Driven Snapshot & 10-Slot Disc Changer CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=False)

    # Menu command
    subparsers.add_parser("menu", help="Launch interactive 49-column TUI disc changer menu")

    # Profiles commands
    p_prof = subparsers.add_parser("profile", help="Manage snapshot profiles")
    prof_sub = p_prof.add_subparsers(dest="action", required=True)
    prof_sub.add_parser("list", help="List all profiles")
    
    p_sel = prof_sub.add_parser("select", help="Select active profile")
    p_sel.add_argument("name", type=str, help="Profile name")

    p_new = prof_sub.add_parser("create", help="Create new profile set with 10 slots")
    p_new.add_argument("name", type=str, help="New profile name")
    p_new.add_argument("-l", "--label", type=str, default="", help="Profile descriptive label")

    p_del = prof_sub.add_parser("delete", help="Delete a profile and its slots")
    p_del.add_argument("name", type=str, help="Profile name")

    p_paths = prof_sub.add_parser("paths", help="View path rules and extension filters")
    p_paths.add_argument("-p", "--profile", type=str, default=None, help="Profile name")

    p_addp = prof_sub.add_parser("add-path", help="Add path rule with extension filter")
    p_addp.add_argument("category", type=str, help="Category name (e.g. skills, hooks, rules)")
    p_addp.add_argument("source_path", type=str, help="Source path to back up")
    p_addp.add_argument("-p", "--profile", type=str, default=None, help="Profile name")
    p_addp.add_argument("-e", "--ext", type=str, default="", help="Extension filter (e.g. .py, .md or empty)")
    p_addp.add_argument("-r", "--recursive", action="store_true", help="Recursive search flag")
    p_addp.add_argument("-t", "--type", choices=["file", "dir_zip"], default="file", help="Pack type")
    p_addp.add_argument("-s", "--subfolder", type=str, default="", help="Target backup subfolder")

    p_rmp = prof_sub.add_parser("remove-path", help="Remove path rule by rule_id")
    p_rmp.add_argument("rule_id", type=str, help="Rule ID to remove")
    p_rmp.add_argument("-p", "--profile", type=str, default=None, help="Profile name")

    # Slot commands
    p_slot = subparsers.add_parser("slot", help="Slot operations (disc changer)")
    slot_sub = p_slot.add_subparsers(dest="action", required=True)

    p_sstatus = slot_sub.add_parser("status", help="Show slots for profile")
    p_sstatus.add_argument("-p", "--profile", type=str, default=None, help="Profile name")

    p_sload = slot_sub.add_parser("load", help="Load slot profile (disc changer switch)")
    p_sload.add_argument("slot", type=int, choices=range(1, 12), help="Slot number (1-10 or 11)")
    p_sload.add_argument("-p", "--profile", type=str, default=None, help="Profile name")
    p_sload.add_argument("--auto-save", action="store_true", help="Auto-save current slot before switch")
    p_sload.add_argument("-f", "--force", action="store_true", help="Force overwrite on restore")

    p_ssave = slot_sub.add_parser("save", help="Snapshot active state into slot")
    p_ssave.add_argument("slot", type=int, choices=range(1, 12), help="Slot number (1-10 or 11)")
    p_ssave.add_argument("-p", "--profile", type=str, default=None, help="Profile name")
    p_ssave.add_argument("-l", "--label", type=str, default=None, help="Slot descriptive label")

    p_scopy = slot_sub.add_parser("copy", help="Copy one slot to another")
    p_scopy.add_argument("src", type=int, choices=range(1, 12), help="Source slot ID")
    p_scopy.add_argument("dst", type=int, choices=range(1, 11), help="Destination slot ID (1-10)")
    p_scopy.add_argument("-p", "--profile", type=str, default=None, help="Profile name")

    p_sexp = slot_sub.add_parser("export", help="Export slot to zip package")
    p_sexp.add_argument("slot", type=int, choices=range(1, 12), help="Slot number")
    p_sexp.add_argument("out_zip", type=str, help="Destination ZIP path")
    p_sexp.add_argument("-p", "--profile", type=str, default=None, help="Profile name")

    p_simp = slot_sub.add_parser("import", help="Import zip package into slot")
    p_simp.add_argument("in_zip", type=str, help="Input ZIP path")
    p_simp.add_argument("slot", type=int, choices=range(1, 11), help="Target slot (1-10)")
    p_simp.add_argument("-l", "--label", type=str, default=None, help="Slot descriptive label")
    p_simp.add_argument("-p", "--profile", type=str, default=None, help="Profile name")

    p_slabel = slot_sub.add_parser("label", help="Set user label for slot")
    p_slabel.add_argument("slot", type=int, choices=range(1, 12), help="Slot number")
    p_slabel.add_argument("label", type=str, help="Descriptive label")
    p_slabel.add_argument("-p", "--profile", type=str, default=None, help="Profile name")

    p_sem_res = slot_sub.add_parser("emergency-restore", help="Restore Slot 11 and set neutral baseline")
    p_sem_res.add_argument("-p", "--profile", type=str, default=None, help="Profile name")

    p_sem_save = slot_sub.add_parser("emergency-save", help="Update Slot 11 (Allowed ONLY in neutral baseline)")
    p_sem_save.add_argument("-p", "--profile", type=str, default=None, help="Profile name")
    p_sem_save.add_argument("-l", "--label", type=str, default="Master Emergency Golden Image")

    args = parser.parse_args()

    if not args.subcommand or args.subcommand == "menu":
        return run_tui_menu()

    try:
        if args.subcommand == "profile":
            if args.action == "list":
                render_profiles_table()
                return 0
            elif args.action == "select":
                set_active_profile_name(args.name)
                print_49(format_positive_feedback(f"SWITCHED ACTIVE PROFILE TO '{args.name}'"))
                return 0
            elif args.action == "create":
                res = create_new_profile(args.name, label=args.label)
                render_banner("PROFILE CREATED")
                print_49(f"Name   : {res['profile_name']}")
                print_49(f"Slots  : {res['profile_name']}-Slot1 .. 10 + EM")
                render_footer()
                return 0
            elif args.action == "delete":
                ok = delete_profile(args.name)
                render_banner("PROFILE DELETED")
                print_49(f"Profile: {args.name} ({'DELETED' if ok else 'NOT FOUND'})")
                render_footer()
                return 0
            elif args.action == "paths":
                render_profile_paths_table(args.profile)
                return 0
            elif args.action == "add-path":
                prof = args.profile or get_active_profile_name()
                res = profile_add_path(
                    profile_name=prof,
                    category=args.category,
                    source_path=args.source_path,
                    extension_filter=args.ext,
                    is_recursive=args.recursive,
                    pack_type=args.type,
                    target_subfolder=args.subfolder
                )
                render_banner("PATH RULE ADDED")
                print_49(f"Profile: {prof}")
                print_49(f"Rule ID: {res['rule_id'][:38]}")
                print_49(f"Ext    : {res['extension_filter'] or '*'}")
                render_footer()
                return 0
            elif args.action == "remove-path":
                prof = args.profile or get_active_profile_name()
                ok = profile_remove_path(prof, args.rule_id)
                render_banner("PATH RULE REMOVAL")
                print_49(f"Status : {'REMOVED' if ok else 'NOT FOUND'}")
                render_footer()
                return 0

        elif args.subcommand == "slot":
            prof = args.profile or get_active_profile_name()
            if args.action == "status":
                render_profile_slots_table(prof)
                return 0
            elif args.action == "load":
                render_banner(f"LOADING {prof.upper()} SLOT {args.slot}")
                res = universal_slot_load(prof, args.slot, auto_save_current=args.auto_save, force=args.force)
                print_49(f"Prev: Slot {res['previous_slot']} -> Active: Slot {res['active_slot']}")
                print_49(f"Restored: {res['restored']:>5} records")
                render_footer()
                return 0
            elif args.action == "save":
                render_banner(f"SAVING {prof.upper()} SLOT {args.slot}")
                res = universal_slot_save(prof, args.slot, label=args.label)
                print_49(f"Items Backed Up: {res['items']:>5}")
                print_49("Status: SUCCESS")
                render_footer()
                return 0
            elif args.action == "copy":
                render_banner(f"COPYING {prof.upper()} SLOT")
                res = universal_slot_copy(prof, args.src, args.dst)
                print_49(f"Slot {res['src_id']} -> Slot {res['dst_id']} ({res['items']} items)")
                print_49("Status: SUCCESS")
                render_footer()
                return 0
            elif args.action == "export":
                render_banner(f"EXPORTING {prof.upper()} SLOT {args.slot}")
                out_path = universal_slot_export(prof, args.slot, Path(args.out_zip))
                print_49(f"Exported to: {out_path.name}")
                render_footer()
                return 0
            elif args.action == "import":
                render_banner(f"IMPORTING {prof.upper()} SLOT {args.slot}")
                res = universal_slot_import(prof, Path(args.in_zip), args.slot, label=args.label)
                print_49(f"Imported {res['items']} items into Slot {res['slot_id']}")
                render_footer()
                return 0
            elif args.action == "label":
                universal_slot_label(prof, args.slot, args.label)
                print_49(f"Slot {args.slot} label updated: '{args.label[:30]}'")
                return 0
            elif args.action == "emergency-restore":
                render_banner(f"EMERGENCY RESTORE: {prof.upper()}")
                res = universal_slot_emergency_restore(prof)
                print_49(f"Restored: {res['restored']:>5} records")
                print_49("Lock: UNLOCKED (Neutral Baseline Active)")
                render_footer()
                return 0
            elif args.action == "emergency-save":
                render_banner(f"EMERGENCY SAVE: {prof.upper()}")
                res = universal_slot_save(prof, EMERGENCY_SLOT_ID, label=args.label)
                print_49(f"Golden Master: {res['items']:>5} items saved")
                render_footer()
                return 0

    except Exception as exc:
        render_banner("OPERATION ERROR")
        print_49(f"ERROR: {str(exc)[:40]}")
        render_footer()
        logger.error("Operation failed: %s", exc)
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())
