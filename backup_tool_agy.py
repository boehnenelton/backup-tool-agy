#!/data/data/com.termux/files/usr/bin/env python3
"""
Name:          backup_tool_agy.py
Description:   Antigravity CLI Ecosystem Backup & Restore Tool with Multi-Scope BEJSON 104a Tracking (~/, Internal, SD)
Version:       10200
Date Created:  2026-11-12
Author Credit: Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
License:       PolyForm Noncommercial License 1.0.0 (PolyForm-Noncommercial-1.0.0)
RELATIONAL_ID: ed36bda3-5342-4636-bca1-30c58a7c08c8
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

# Default System Paths
HOME_DIR: Path = Path(os.path.expanduser("~"))
DEFAULT_BACKUP_DIR: Path = HOME_DIR / "backup-nov11"
INTERNAL_DIR: Path = Path("/storage/emulated/0")
DEFINITIONS_FILE: Path = INTERNAL_DIR / ".env/user/definitions.json"

# Antigravity specific directories in HOME
GEMINI_DIR: Path = HOME_DIR / ".gemini"
CONFIG_DIR: Path = GEMINI_DIR / "config"
CLI_DIR: Path = GEMINI_DIR / "antigravity-cli"

# Traversal pruning set for ultra-fast scanning
PRUNE_DIRS: Set[str] = {
    ".git", "node_modules", "__pycache__", ".pytest_cache", "cache",
    "data_temp", "brain", "android-sdk", "site-packages", ".gradle",
    "build", "dist", "backup-nov11", "backup-tool-agy", ".cargo",
    "skills_backup_20261103_101328", ".script_commander", "Android"
}

# Setup non-production print logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("backup_tool_agy")

# ---------------------------------------------------------------------------
# BEJSON 104a Core Implementation with Mandatory O(1) Field Map Cache
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

# Canonical Manifest Schema definition
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

def resolve_sd_card_path(custom_path: Optional[str] = None) -> Optional[Path]:
    """Resolve SD card path from explicit parameter, env var, definitions.json, or fallback."""
    if custom_path:
        p = Path(custom_path).resolve()
        if p.exists():
            return p
    env_sd = os.environ.get("SD_CARD")
    if env_sd:
        p = Path(env_sd).resolve()
        if p.exists():
            return p
    if DEFINITIONS_FILE.exists():
        try:
            with open(DEFINITIONS_FILE, "r", encoding="utf-8") as f:
                doc = json.load(f)
            field_map = bejson_get_field_map(doc)
            val_idx = field_map.get("var_value", 1)
            name_idx = field_map.get("var_name", 0)
            for row in doc.get("Values", []):
                if row[name_idx] == "SD_CARD":
                    p = Path(row[val_idx]).resolve()
                    if p.exists():
                        return p
        except Exception:
            pass
    fallback = INTERNAL_DIR / "Admin/SD_Fallback"
    if fallback.exists():
        return fallback
    return None

def parse_active_scopes(scope_arg: str, include_sd: bool, sd_path: Optional[str]) -> Tuple[Set[str], Optional[Path]]:
    """Determine active scopes and resolved SD card path."""
    scopes: Set[str] = set()
    sd_resolved = resolve_sd_card_path(sd_path) if (include_sd or sd_path) else None

    if scope_arg == "all":
        scopes.add("home")
        scopes.add("internal")
        if include_sd or sd_path or sd_resolved:
            scopes.add("sd")
    else:
        for s in scope_arg.split(","):
            s_clean = s.strip().lower()
            if s_clean in ("home", "internal", "sd"):
                scopes.add(s_clean)

    if "sd" in scopes and not sd_resolved:
        sd_resolved = resolve_sd_card_path(sd_path)

    return scopes, sd_resolved

# ---------------------------------------------------------------------------
# Multi-Scope Discovery Routines (~/, Internal, SD)
# ---------------------------------------------------------------------------
def get_search_roots(scopes: Set[str], sd_resolved: Optional[Path]) -> List[Path]:
    """Return all root search paths according to active scopes."""
    roots: List[Path] = []
    if "home" in scopes and HOME_DIR.exists():
        roots.append(HOME_DIR)
    if "internal" in scopes and INTERNAL_DIR.exists():
        admin_p = INTERNAL_DIR / "Admin"
        docs_p = INTERNAL_DIR / "Documents"
        if admin_p.exists():
            roots.append(admin_p)
        if docs_p.exists():
            roots.append(docs_p)
    if "sd" in scopes and sd_resolved and sd_resolved.exists():
        roots.append(sd_resolved)
    return roots

def discover_markdown_files(scopes: Set[str], sd_resolved: Optional[Path]) -> List[Path]:
    """Discover all Gemini and Agent markdown files across active scopes."""
    candidates: List[Path] = []

    # 1. Explicit high-priority paths in HOME
    if "home" in scopes:
        explicit_home = [
            GEMINI_DIR / "GEMINI.md",
            GEMINI_DIR / "GEMINI.md.bak-20261025",
            GEMINI_DIR / "GEMINI.md.bak_20261105",
            GEMINI_DIR / "backups" / "GEMINI_Release_300_pre_optimization.md",
            GEMINI_DIR / "config" / "efficiency_report.md",
            HOME_DIR / "GEMINI.MD",
            HOME_DIR / "generate" / "prompts" / "gemini.md",
            HOME_DIR / "generate" / "agents.md",
            HOME_DIR / "generate" / "policy" / "drafts" / "AGENT_TEMPLATE.md",
            HOME_DIR / "generate" / "blog_post_ideas" / "AGENTS.MD",
            HOME_DIR / "generate" / "profiles" / "AGENTS.MD",
            HOME_DIR / "generate" / "profiles" / "context" / "105" / "Libraries_105_Agent_Directive-V10100-PKG100.md",
            HOME_DIR / "react_setup" / "test" / "AGENTS.md",
            HOME_DIR / "build_workspace" / "BEJSON_Editor" / "AGENTS.md",
            HOME_DIR / "test" / "libraries_105" / "Lib_JS" / "GEMINI.md",
            HOME_DIR / "test" / "libraries_105" / "Libraries_105_Agent_Directive-V10100-PKG100.md",
        ]
        for loc in explicit_home:
            if loc.is_file() and not loc.is_symlink():
                candidates.append(loc.resolve())

    # 2. Dynamic traversal across all active search roots
    roots = get_search_roots(scopes, sd_resolved)
    for base in roots:
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in PRUNE_DIRS]
            for file in files:
                file_lower = file.lower()
                if (
                    file_lower in ("gemini.md", "agents.md")
                    or (file_lower.startswith("gemini") and file_lower.endswith(".md"))
                    or (file_lower.startswith("agents") and file_lower.endswith(".md"))
                    or "agent_directive" in file_lower
                    or "modern_agent_design" in file_lower
                ):
                    p = Path(root) / file
                    if p.is_file() and not p.is_symlink() and "backup-nov11" not in str(p):
                        resolved = p.resolve()
                        if resolved not in candidates:
                            candidates.append(resolved)

    return sorted(candidates)

def discover_skills(scopes: Set[str], sd_resolved: Optional[Path]) -> List[Path]:
    """Discover active user skills across ~/.gemini, internal AGY mirrors, and optional SD."""
    skill_dirs: List[Path] = []
    
    # 1. Primary HOME skills
    if "home" in scopes:
        home_skills = CONFIG_DIR / "skills"
        if home_skills.exists():
            for item in home_skills.iterdir():
                if item.name.startswith("skills_backup_") or item.name in PRUNE_DIRS:
                    continue
                skill_dirs.append(item.resolve())

    # 2. Internal Storage skills (AGY documents & consolidated archive)
    if "internal" in scopes:
        internal_skill_locs = [
            INTERNAL_DIR / "Documents/AGY/skills",
            INTERNAL_DIR / "Admin/Dev/Skills/agy-consolidated/skills"
        ]
        for is_dir in internal_skill_locs:
            if is_dir.exists():
                for item in is_dir.iterdir():
                    if item.name.startswith("skills_backup_") or item.name in PRUNE_DIRS:
                        continue
                    resolved = item.resolve()
                    if resolved not in skill_dirs:
                        skill_dirs.append(resolved)

    # 3. SD card skills
    if "sd" in scopes and sd_resolved and (sd_resolved / "skills").exists():
        for item in (sd_resolved / "skills").iterdir():
            if item.name.startswith("skills_backup_") or item.name in PRUNE_DIRS:
                continue
            resolved = item.resolve()
            if resolved not in skill_dirs:
                skill_dirs.append(resolved)

    return sorted(skill_dirs)

def discover_hooks(scopes: Set[str], sd_resolved: Optional[Path]) -> List[Path]:
    """Discover lifecycle hooks scripts and config files across scopes."""
    hooks_items: List[Path] = []

    # 1. HOME hooks
    if "home" in scopes:
        home_hooks_dir = CONFIG_DIR / ".agents" / "hooks"
        if home_hooks_dir.exists():
            for item in home_hooks_dir.iterdir():
                if item.is_file() and not item.name.endswith((".pyc", ".pyo")):
                    hooks_items.append(item.resolve())
        agents_hooks_json = CONFIG_DIR / ".agents" / "hooks.json"
        if agents_hooks_json.is_file() and not agents_hooks_json.is_symlink():
            hooks_items.append(agents_hooks_json.resolve())
        root_hooks_json = HOME_DIR / ".agents" / "hooks.json"
        if root_hooks_json.is_file() and not root_hooks_json.is_symlink():
            hooks_items.append(root_hooks_json.resolve())

    # 2. Internal storage hooks
    if "internal" in scopes:
        internal_hook_dirs = [
            INTERNAL_DIR / "Documents/AGY/hooks",
            INTERNAL_DIR / "Admin/Dev/Skills/agy-consolidated/hooks"
        ]
        for ih_dir in internal_hook_dirs:
            if ih_dir.exists():
                for item in ih_dir.iterdir():
                    if item.is_file() and not item.name.endswith((".pyc", ".pyo")):
                        resolved = item.resolve()
                        if resolved not in hooks_items:
                            hooks_items.append(resolved)

    # 3. SD card hooks
    if "sd" in scopes and sd_resolved and (sd_resolved / "hooks").exists():
        for item in (sd_resolved / "hooks").iterdir():
            if item.is_file() and not item.name.endswith((".pyc", ".pyo")):
                resolved = item.resolve()
                if resolved not in hooks_items:
                    hooks_items.append(resolved)

    return sorted(hooks_items)

def discover_rules(scopes: Set[str], sd_resolved: Optional[Path]) -> List[Path]:
    """Discover workspace and global rules files (GEMINI.md, AGENTS.md, .agents/rules/*.md)."""
    rules_items: List[Path] = []

    # 1. High-priority global rule files
    if "home" in scopes:
        primary_gemini = GEMINI_DIR / "GEMINI.md"
        if primary_gemini.is_file():
            rules_items.append(primary_gemini.resolve())
        home_gemini = HOME_DIR / "GEMINI.MD"
        if home_gemini.is_file():
            rules_items.append(home_gemini.resolve())

    if "internal" in scopes:
        internal_rules = [
            INTERNAL_DIR / "Documents/AGY/rules/GEMINI.md",
            INTERNAL_DIR / "Documents/AGY/rules/AGENTS.MD",
            INTERNAL_DIR / "Admin/Dev/Skills/agy-consolidated/rules/GEMINI.md",
            INTERNAL_DIR / "Admin/Dev/Skills/agy-consolidated/rules/AGENTS.MD",
        ]
        for ir in internal_rules:
            if ir.is_file():
                resolved = ir.resolve()
                if resolved not in rules_items:
                    rules_items.append(resolved)

    # 2. Dynamic traversal across all active search roots
    roots = get_search_roots(scopes, sd_resolved)
    for base in roots:
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in PRUNE_DIRS]
            p_root = Path(root)
            for file in files:
                file_lower = file.lower()
                if file_lower in ("gemini.md", "agents.md"):
                    p = (p_root / file).resolve()
                    if p.is_file() and not p.is_symlink() and p not in rules_items and "backup-nov11" not in str(p):
                        rules_items.append(p)
                elif p_root.name == "rules" and ".agents" in str(p_root) and file.endswith(".md"):
                    p = (p_root / file).resolve()
                    if p.is_file() and not p.is_symlink() and p not in rules_items and "backup-nov11" not in str(p):
                        rules_items.append(p)

    return sorted(rules_items)

def discover_subagents(scopes: Set[str], sd_resolved: Optional[Path]) -> List[Path]:
    """Discover declarative subagent markdown files across scopes."""
    subagents_items: List[Path] = []

    # 1. Primary HOME subagents
    if "home" in scopes:
        agents_dir = CLI_DIR / "agents"
        if agents_dir.exists():
            for item in agents_dir.iterdir():
                if item.is_file() and item.name.endswith(".md"):
                    subagents_items.append(item.resolve())

    # 2. Internal storage subagents
    if "internal" in scopes:
        internal_subagent_dirs = [
            INTERNAL_DIR / "Documents/AGY/subagents",
            INTERNAL_DIR / "Admin/Dev/Skills/agy-consolidated/subagents"
        ]
        for is_dir in internal_subagent_dirs:
            if is_dir.exists():
                for item in is_dir.iterdir():
                    if item.is_file() and item.name.endswith(".md"):
                        resolved = item.resolve()
                        if resolved not in subagents_items:
                            subagents_items.append(resolved)

    # 3. SD card subagents
    if "sd" in scopes and sd_resolved and (sd_resolved / "subagents").exists():
        for item in (sd_resolved / "subagents").iterdir():
            if item.is_file() and item.name.endswith(".md"):
                resolved = item.resolve()
                if resolved not in subagents_items:
                    subagents_items.append(resolved)

    return sorted(subagents_items)

# ---------------------------------------------------------------------------
# Core Operations: Backup & Restore
# ---------------------------------------------------------------------------
def perform_backup(
    target_root: Path,
    category_filter: Optional[str] = None,
    scopes: Optional[Set[str]] = None,
    sd_resolved: Optional[Path] = None,
    dry_run: bool = False
) -> Dict[str, Any]:
    """Execute backup copying files, minting UUIDs in filenames, and tracking via BEJSON 104a."""
    if scopes is None:
        scopes = {"home", "internal"}

    categories: Dict[str, List[Path]] = {
        "markdown": discover_markdown_files(scopes, sd_resolved),
        "skills": discover_skills(scopes, sd_resolved),
        "hooks": discover_hooks(scopes, sd_resolved),
        "rules": discover_rules(scopes, sd_resolved),
        "subagents": discover_subagents(scopes, sd_resolved)
    }

    if category_filter and category_filter != "all":
        if category_filter not in categories:
            raise ValueError(f"Invalid category '{category_filter}'. Choose from: {list(categories.keys())}")
        categories = {category_filter: categories[category_filter]}

    master_records: List[List[Any]] = []
    category_summary: Dict[str, int] = {}

    for cat_name, source_paths in categories.items():
        cat_dir = target_root / cat_name
        if not dry_run:
            cat_dir.mkdir(parents=True, exist_ok=True)
        cat_records: List[List[Any]] = []

        for src in source_paths:
            rec_uuid = str(uuid.uuid4())
            item_name = src.name
            timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

            if src.is_dir():
                # Skill or composite directory -> Package as <name>_<uuid>.zip
                backup_filename = f"{src.name}_{rec_uuid}.zip"
                dest_path = cat_dir / backup_filename
                item_type = "directory_zip"
                file_mode = "0755"

                if not dry_run:
                    zip_directory(src, dest_path)
                    sha256_val = compute_sha256(dest_path)
                    byte_size = dest_path.stat().st_size
                else:
                    sha256_val = "DRY_RUN_HASH"
                    byte_size = 0
            else:
                # Regular file -> Copy as <stem>_<uuid><suffix>
                stem = src.stem
                suffix = src.suffix
                backup_filename = f"{stem}_{rec_uuid}{suffix}"
                dest_path = cat_dir / backup_filename
                item_type = "file"

                if not dry_run:
                    shutil.copy2(src, dest_path)
                    sha256_val = compute_sha256(dest_path)
                    byte_size = dest_path.stat().st_size
                    file_mode = oct(src.stat().st_mode & 0o777)
                else:
                    sha256_val = "DRY_RUN_HASH"
                    byte_size = 0
                    file_mode = oct(src.stat().st_mode & 0o777) if src.exists() else "0644"

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

        # Write per-category BEJSON 104a manifest
        if not dry_run and cat_records:
            cat_manifest = bejson_create_104a(
                record_type="BackupRecord",
                fields=MANIFEST_FIELDS,
                values=cat_records,
                Category=cat_name,
                Total_Records=len(cat_records),
                Backup_Timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
            )
            bejson_atomic_write(cat_dir / "manifest.104a.bejson", cat_manifest)

    # Write Master BEJSON 104a manifest
    if not dry_run and master_records:
        master_manifest = bejson_create_104a(
            record_type="BackupRecord",
            fields=MANIFEST_FIELDS,
            values=master_records,
            Backup_Root=str(target_root),
            Total_Records=len(master_records),
            Category_Summary=category_summary,
            Active_Scopes=list(scopes),
            SD_Path=str(sd_resolved) if sd_resolved else None,
            Backup_Timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
        )
        bejson_atomic_write(target_root / "manifest.104a.bejson", master_manifest)

    return {
        "status": "success",
        "dry_run": dry_run,
        "backup_root": str(target_root),
        "total_backed_up": len(master_records),
        "summary": category_summary,
        "scopes": list(scopes)
    }

def perform_restore(target_root: Path, category_filter: Optional[str] = None, item_uuid: Optional[str] = None, dry_run: bool = False, force: bool = False) -> Dict[str, Any]:
    """Restore files back to original state and paths using the BEJSON 104a manifest."""
    master_manifest_path = target_root / "manifest.104a.bejson"
    doc = bejson_load_104a(master_manifest_path)
    if not doc:
        raise FileNotFoundError(f"Master manifest not found or invalid at {master_manifest_path}")

    field_map = bejson_get_field_map(doc)
    values = doc.get("Values", [])
    restored_count = 0
    skipped_count = 0
    restore_details: List[Dict[str, str]] = []

    for row in values:
        rec_uuid = row[field_map["record_uuid"]]
        cat = row[field_map["category"]]
        orig_path = Path(row[field_map["original_path"]])
        backup_path = Path(row[field_map["backup_path"]])
        item_type = row[field_map["item_type"]]
        expected_sha = row[field_map["sha256"]]
        file_mode_str = row[field_map["file_mode"]]

        if category_filter and category_filter != "all" and cat != category_filter:
            continue
        if item_uuid and rec_uuid != item_uuid:
            continue

        if not backup_path.exists():
            logger.warning("Backup file missing: %s (UUID %s)", backup_path, rec_uuid)
            skipped_count += 1
            continue

        actual_sha = compute_sha256(backup_path)
        if actual_sha != expected_sha:
            logger.error("Checksum mismatch for %s! Expected: %s, Found: %s", backup_path, expected_sha, actual_sha)
            if not force:
                skipped_count += 1
                continue

        if not dry_run:
            orig_path.parent.mkdir(parents=True, exist_ok=True)
            if item_type == "directory_zip":
                if orig_path.exists() and not force:
                    bak_dir = orig_path.with_suffix(f".pre_restore_bak_{int(datetime.datetime.now().timestamp())}")
                    shutil.move(orig_path, bak_dir)
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
                    mode_val = int(file_mode_str, 8)
                    orig_path.chmod(mode_val)
                except Exception:
                    pass

        restored_count += 1
        restore_details.append({
            "uuid": rec_uuid,
            "category": cat,
            "original_path": str(orig_path),
            "status": "restored" if not dry_run else "dry_run"
        })

    return {
        "status": "success",
        "dry_run": dry_run,
        "restored_count": restored_count,
        "skipped_count": skipped_count,
        "details": restore_details
    }

def perform_verify(target_root: Path) -> Dict[str, Any]:
    """Verify SHA256 checksums and file presence of all backup records in manifest."""
    master_manifest_path = target_root / "manifest.104a.bejson"
    doc = bejson_load_104a(master_manifest_path)
    if not doc:
        return {"status": "error", "message": f"Manifest not found: {master_manifest_path}"}

    field_map = bejson_get_field_map(doc)
    values = doc.get("Values", [])
    valid_count = 0
    corrupt_count = 0
    missing_count = 0

    for row in values:
        backup_path = Path(row[field_map["backup_path"]])
        expected_sha = row[field_map["sha256"]]

        if not backup_path.exists():
            missing_count += 1
            continue

        actual_sha = compute_sha256(backup_path)
        if actual_sha == expected_sha:
            valid_count += 1
        else:
            corrupt_count += 1

    return {
        "status": "verified" if (corrupt_count == 0 and missing_count == 0) else "degraded",
        "total_records": len(values),
        "valid": valid_count,
        "corrupt": corrupt_count,
        "missing": missing_count
    }

# ---------------------------------------------------------------------------
# 49-Column Mobile Portrait CLI Formatting & Entry Point
# ---------------------------------------------------------------------------
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

def main() -> int:
    parser = argparse.ArgumentParser(
        description="AGY Multi-Scope Ecosystem 104a Backup & Restore Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Backup subcommand
    p_backup = subparsers.add_parser("backup", help="Run ecosystem backup across scopes")
    p_backup.add_argument("-t", "--target", type=str, default=str(DEFAULT_BACKUP_DIR), help="Target backup directory")
    p_backup.add_argument("-c", "--category", type=str, choices=["all", "markdown", "skills", "hooks", "rules", "subagents"], default="all", help="Category filter")
    p_backup.add_argument("--scope", type=str, default="all", help="Scope: all, home, internal, sd (or e.g. home,internal)")
    p_backup.add_argument("--include-sd", action="store_true", help="Explicitly include SD card in discovery")
    p_backup.add_argument("--sd-path", type=str, default=None, help="Explicit path to SD card")
    p_backup.add_argument("--dry-run", action="store_true", help="Simulate backup without copying")

    # Restore subcommand
    p_restore = subparsers.add_parser("restore", help="Restore ecosystem from backup")
    p_restore.add_argument("-t", "--target", type=str, default=str(DEFAULT_BACKUP_DIR), help="Source backup directory")
    p_restore.add_argument("-c", "--category", type=str, choices=["all", "markdown", "skills", "hooks", "rules", "subagents"], default="all", help="Category filter")
    p_restore.add_argument("-u", "--uuid", type=str, default=None, help="Specific record UUID to restore")
    p_restore.add_argument("-f", "--force", action="store_true", help="Force overwrite without confirmation")
    p_restore.add_argument("--dry-run", action="store_true", help="Simulate restore")

    # Verify subcommand
    p_verify = subparsers.add_parser("verify", help="Verify backup integrity against manifest")
    p_verify.add_argument("-t", "--target", type=str, default=str(DEFAULT_BACKUP_DIR), help="Backup directory")

    # List subcommand
    p_list = subparsers.add_parser("list", help="List backed up files")
    p_list.add_argument("-t", "--target", type=str, default=str(DEFAULT_BACKUP_DIR), help="Backup directory")
    p_list.add_argument("-c", "--category", type=str, default="all", help="Category filter")

    args = parser.parse_args()
    target_path = Path(args.target).resolve()

    if args.command == "backup":
        render_banner("AGY MULTI-SCOPE BACKUP (104a)")
        scopes, sd_resolved = parse_active_scopes(args.scope, args.include_sd, args.sd_path)
        print_49(f"Target: {target_path}")
        print_49(f"Scopes: {','.join(sorted(scopes))}")
        if sd_resolved:
            print_49(f"SD Card: {sd_resolved}")
        print_49(SUBDIVIDER_49)
        result = perform_backup(
            target_path,
            category_filter=args.category,
            scopes=scopes,
            sd_resolved=sd_resolved,
            dry_run=args.dry_run
        )
        for cat, cnt in result["summary"].items():
            print_49(f" {cat:<20} : {cnt:>5} records")
        print_49(SUBDIVIDER_49)
        print_49(f"Total Backed Up : {result['total_backed_up']:>5} items")
        render_footer()
        return 0

    elif args.command == "restore":
        render_banner("AGY ECOSYSTEM RESTORE (104a)")
        print_49(f"Source: {target_path}")
        print_49(f"Filter: {args.category} | Force: {args.force}")
        print_49(SUBDIVIDER_49)
        result = perform_restore(target_path, category_filter=args.category, item_uuid=args.uuid, dry_run=args.dry_run, force=args.force)
        print_49(f"Restored: {result['restored_count']:>5} | Skipped: {result['skipped_count']:>5}")
        render_footer()
        return 0

    elif args.command == "verify":
        render_banner("AGY BACKUP INTEGRITY VERIFY")
        print_49(f"Target: {target_path}")
        print_49(SUBDIVIDER_49)
        result = perform_verify(target_path)
        if result["status"] == "error":
            print_49(f"ERROR: {result['message']}")
        else:
            print_49(f"Total Records : {result['total_records']:>5}")
            print_49(f"Valid Checksum: {result['valid']:>5}")
            print_49(f"Corrupted File: {result['corrupt']:>5}")
            print_49(f"Missing File  : {result['missing']:>5}")
            print_49(SUBDIVIDER_49)
            print_49(f"Status        : {result['status'].upper():>5}")
        render_footer()
        return 0 if result.get("status") == "verified" else 1

    elif args.command == "list":
        render_banner("AGY BACKUP INVENTORY")
        manifest_path = target_path / "manifest.104a.bejson"
        doc = bejson_load_104a(manifest_path)
        if not doc:
            print_49(f"No manifest found at {manifest_path}")
            render_footer()
            return 1
        field_map = bejson_get_field_map(doc)
        values = doc.get("Values", [])
        for row in values:
            cat = row[field_map["category"]]
            if args.category != "all" and cat != args.category:
                continue
            fname = row[field_map["backup_filename"]]
            print_49(f"[{cat[:4]}] {fname}")
        print_49(SUBDIVIDER_49)
        print_49(f"Total Listed : {len(values):>5}")
        render_footer()
        return 0

    return 0

if __name__ == "__main__":
    sys.exit(main())
