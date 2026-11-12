#!/data/data/com.termux/files/usr/bin/env python3
"""
Name:          agy_slot_manager.py
Description:   10-Slot Disc Changer & Emergency Backup Management System for Antigravity (AGY)
Version:       10100
Date Created:  2026-11-12
Author Credit: Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
License:       PolyForm Noncommercial License 1.0.0 (PolyForm-Noncommercial-1.0.0)
RELATIONAL_ID: 9c5e317b-23a4-4f8e-8bf0-89025171e1de
"""

import argparse
import datetime
import json
import logging
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Import core backup engine
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from backup_tool_agy import (
    DIVIDER_49,
    SUBDIVIDER_49,
    HOME_DIR,
    GEMINI_DIR,
    CONFIG_DIR,
    CLI_DIR,
    INTERNAL_DIR,
    bejson_get_field_map,
    bejson_create_104a,
    bejson_atomic_write,
    bejson_load_104a,
    perform_backup,
    perform_restore,
    perform_verify,
    print_49,
    render_banner,
    render_footer,
    resolve_sd_card_path,
    C_RESET,
    C_RED,
    C_BOLD_RED,
    C_WHITE,
    C_GRAY,
    C_CYAN,
    C_GREEN,
    C_YELLOW,
)

# Constants
SLOTS_ROOT: Path = HOME_DIR / "agy-slots"
REGISTRY_FILE: Path = SLOTS_ROOT / "slots_registry.104a.bejson"
TOTAL_REGULAR_SLOTS = 10
EMERGENCY_SLOT_ID = 11

logger = logging.getLogger("agy_slot_manager")

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
# Registry Initialization & Management
# ---------------------------------------------------------------------------
def get_slot_name(slot_id: int) -> str:
    """Return canonical directory name for slot ID."""
    if slot_id == EMERGENCY_SLOT_ID:
        return "Agy-Emergency"
    return f"Agy-Slot{slot_id}"

def init_registry() -> Dict[str, Any]:
    """Initialize or load the 11-slot BEJSON 104a registry."""
    SLOTS_ROOT.mkdir(parents=True, exist_ok=True)
    if REGISTRY_FILE.exists():
        doc = bejson_load_104a(REGISTRY_FILE)
        if doc and "Values" in doc:
            return doc

    values: List[List[Any]] = []
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Regular slots 1-10
    for sid in range(1, TOTAL_REGULAR_SLOTS + 1):
        sname = get_slot_name(sid)
        sdir = SLOTS_ROOT / sname
        sdir.mkdir(parents=True, exist_ok=True)
        # Check if initialized
        manifest = sdir / "manifest.104a.bejson"
        cnt = 0
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

    # Emergency slot 11
    em_name = get_slot_name(EMERGENCY_SLOT_ID)
    em_dir = SLOTS_ROOT / em_name
    em_dir.mkdir(parents=True, exist_ok=True)
    em_manifest = em_dir / "manifest.104a.bejson"
    em_cnt = 0
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
        Active_Slot_ID=1 if values[0][4] else 0,
        Emergency_Restored_Flag=False,
        Last_Updated=now
    )
    bejson_atomic_write(REGISTRY_FILE, doc)
    return doc

def save_registry(doc: Dict[str, Any]) -> None:
    """Save updated registry document atomically."""
    doc["Last_Updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    bejson_atomic_write(REGISTRY_FILE, doc)

# ---------------------------------------------------------------------------
# Slot Operations
# ---------------------------------------------------------------------------
def get_slot_record(doc: Dict[str, Any], slot_id: int) -> Optional[List[Any]]:
    """Get mutable row for a slot ID from registry document."""
    field_map = bejson_get_field_map(doc)
    id_idx = field_map["slot_id"]
    for row in doc.get("Values", []):
        if row[id_idx] == slot_id:
            return row
    return None

def clear_live_customizations() -> None:
    """Safely clear active customizations before loading a new slot."""
    # 1. Clear skills directory contents
    skills_dir = CONFIG_DIR / "skills"
    if skills_dir.exists():
        for item in skills_dir.iterdir():
            if item.name.startswith("skills_backup_") or item.name == "__pycache__":
                continue
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            elif item.is_file():
                item.unlink(missing_ok=True)

    # 2. Clear subagents in antigravity-cli/agents
    agents_dir = CLI_DIR / "agents"
    if agents_dir.exists():
        for item in agents_dir.iterdir():
            if item.is_file() and item.name.endswith(".md"):
                item.unlink(missing_ok=True)

    # 3. Clear hooks scripts
    hooks_dir = CONFIG_DIR / ".agents" / "hooks"
    if hooks_dir.exists():
        for item in hooks_dir.iterdir():
            if item.is_file() and not item.name.endswith((".pyc", ".pyo")):
                item.unlink(missing_ok=True)

def slot_save(slot_id: int, label: Optional[str] = None, include_sd: bool = False) -> Dict[str, Any]:
    """Backup active ecosystem into specified slot."""
    doc = init_registry()
    field_map = bejson_get_field_map(doc)

    if slot_id == EMERGENCY_SLOT_ID:
        active_id = doc.get("Active_Slot_ID", 0)
        em_restored = doc.get("Emergency_Restored_Flag", False)
        if active_id != 0 or not em_restored:
            raise PermissionError(
                "E_EMERGENCY_PROTECTION: Slot 11 (Emergency) is write-protected. "
                "You can only overwrite it after executing an emergency restore and "
                "ensuring no experimental slot is active."
            )

    row = get_slot_record(doc, slot_id)
    if not row:
        raise ValueError(f"Invalid slot ID: {slot_id}")

    slot_dir = Path(row[field_map["slot_dir"]])
    sd_path = resolve_sd_card_path() if include_sd else None
    scopes = {"home", "internal"}
    if include_sd and sd_path:
        scopes.add("sd")

    result = perform_backup(
        target_root=slot_dir,
        category_filter="all",
        scopes=scopes,
        sd_resolved=sd_path,
        dry_run=False
    )

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    row[field_map["item_count"]] = result["total_backed_up"]
    row[field_map["last_saved"]] = now
    if label:
        row[field_map["slot_label"]] = label

    save_registry(doc)
    return {
        "status": "success",
        "slot_id": slot_id,
        "slot_name": row[field_map["slot_name"]],
        "items": result["total_backed_up"],
        "timestamp": now
    }

def slot_load(slot_id: int, auto_save_current: bool = False, force: bool = False) -> Dict[str, Any]:
    """Disc Changer operation: unload active slot, load target slot."""
    doc = init_registry()
    field_map = bejson_get_field_map(doc)

    target_row = get_slot_record(doc, slot_id)
    if not target_row:
        raise ValueError(f"Invalid slot ID: {slot_id}")

    slot_dir = Path(target_row[field_map["slot_dir"]])
    manifest_path = slot_dir / "manifest.104a.bejson"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Slot {slot_id} is empty (no manifest at {manifest_path})")

    active_id = doc.get("Active_Slot_ID", 0)

    # Auto-save current active slot if requested
    if auto_save_current and active_id in range(1, TOTAL_REGULAR_SLOTS + 1):
        slot_save(active_id)

    # 1. Clear out active customizations (disc changer unload)
    clear_live_customizations()

    # 2. Restore all files from target slot
    res = perform_restore(
        target_root=slot_dir,
        category_filter="all",
        item_uuid=None,
        dry_run=False,
        force=force
    )

    # 3. Update registry active state
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for row in doc.get("Values", []):
        sid = row[field_map["slot_id"]]
        if sid == slot_id:
            row[field_map["is_active"]] = True
            row[field_map["last_loaded"]] = now
        else:
            row[field_map["is_active"]] = False

    doc["Active_Slot_ID"] = slot_id
    if slot_id != EMERGENCY_SLOT_ID:
        doc["Emergency_Restored_Flag"] = False

    save_registry(doc)
    return {
        "status": "success",
        "previous_slot": active_id,
        "active_slot": slot_id,
        "slot_name": target_row[field_map["slot_name"]],
        "restored": res["restored_count"],
        "skipped": res["skipped_count"]
    }

def slot_copy(src_id: int, dst_id: int) -> Dict[str, Any]:
    """Copy full slot contents and manifest from source to destination slot."""
    if dst_id == EMERGENCY_SLOT_ID:
        raise PermissionError("E_EMERGENCY_PROTECTION: Cannot copy arbitrary slots into Slot 11.")

    doc = init_registry()
    field_map = bejson_get_field_map(doc)

    src_row = get_slot_record(doc, src_id)
    dst_row = get_slot_record(doc, dst_id)
    if not src_row or not dst_row:
        raise ValueError("Source or destination slot ID is invalid.")

    src_dir = Path(src_row[field_map["slot_dir"]])
    dst_dir = Path(dst_row[field_map["slot_dir"]])

    if not (src_dir / "manifest.104a.bejson").exists():
        raise FileNotFoundError(f"Source slot {src_id} is empty.")

    # Wipe destination slot directory and mirror
    if dst_dir.exists():
        shutil.rmtree(dst_dir, ignore_errors=True)
    shutil.copytree(src_dir, dst_dir)

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    dst_row[field_map["item_count"]] = src_row[field_map["item_count"]]
    dst_row[field_map["last_saved"]] = now
    dst_row[field_map["slot_label"]] = f"Copy of Slot {src_id} ({src_row[field_map['slot_label']]})"

    save_registry(doc)
    return {
        "status": "success",
        "src_id": src_id,
        "dst_id": dst_id,
        "item_count": dst_row[field_map["item_count"]]
    }

def slot_export(slot_id: int, out_zip: Path) -> Path:
    """Export slot to a portable ZIP package."""
    doc = init_registry()
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

def slot_import(in_zip: Path, slot_id: int, label: Optional[str] = None) -> Dict[str, Any]:
    """Import a slot ZIP package into designated slot."""
    if slot_id == EMERGENCY_SLOT_ID:
        raise PermissionError("E_EMERGENCY_PROTECTION: Direct zip import into Slot 11 is forbidden.")
    if not in_zip.exists():
        raise FileNotFoundError(f"Input package does not exist: {in_zip}")

    doc = init_registry()
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

    save_registry(doc)
    return {
        "status": "success",
        "slot_id": slot_id,
        "items": cnt
    }

def slot_emergency_restore() -> Dict[str, Any]:
    """Emergency restore: restores Slot 11, sets active slot to 0, unlocks emergency-save."""
    doc = init_registry()
    field_map = bejson_get_field_map(doc)
    em_row = get_slot_record(doc, EMERGENCY_SLOT_ID)
    em_dir = Path(em_row[field_map["slot_dir"]])
    manifest_path = em_dir / "manifest.104a.bejson"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Emergency backup manifest missing at {manifest_path}")

    # Unload active slot and restore emergency
    clear_live_customizations()
    res = perform_restore(
        target_root=em_dir,
        category_filter="all",
        item_uuid=None,
        dry_run=False,
        force=True
    )

    # Set all slots to inactive, activate emergency baseline
    for row in doc.get("Values", []):
        row[field_map["is_active"]] = False

    doc["Active_Slot_ID"] = 0
    doc["Emergency_Restored_Flag"] = True
    save_registry(doc)

    return {
        "status": "success",
        "restored": res["restored_count"],
        "message": "Emergency baseline restored. All experimental slots deactivated."
    }

def slot_set_label(slot_id: int, label: str) -> None:
    """Set descriptive user label for a slot."""
    doc = init_registry()
    field_map = bejson_get_field_map(doc)
    row = get_slot_record(doc, slot_id)
    if not row:
        raise ValueError(f"Invalid slot ID: {slot_id}")
    row[field_map["slot_label"]] = label
    save_registry(doc)

# ---------------------------------------------------------------------------
# 49-Column Mobile Portrait CLI Formatting & CLI Interface
# ---------------------------------------------------------------------------
def render_slots_table() -> None:
    """Render 49-column mobile portrait slot changer status table with ANSI Tri-Color styling."""
    doc = init_registry()
    field_map = bejson_get_field_map(doc)
    active_id = doc.get("Active_Slot_ID", 0)
    em_flag = doc.get("Emergency_Restored_Flag", False)

    render_banner("AGY 10-SLOT DISC CHANGER & BACKUP")
    act_str = f"{C_GREEN}Slot {active_id}{C_RESET}" if active_id > 0 else f"{C_YELLOW}None (Neutral Baseline){C_RESET}"
    em_str = f"{C_GREEN}True{C_RESET}" if em_flag else f"{C_BOLD_RED}False (Locked){C_RESET}"
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

def main() -> int:
    parser = argparse.ArgumentParser(
        description="AGY 10-Slot Disc Changer & Emergency Backup System",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Status / List
    subparsers.add_parser("status", help="Display all slots and active selection")
    subparsers.add_parser("list", help="Display all slots and active selection")

    # Load / Switch
    p_load = subparsers.add_parser("load", help="Unload active slot and load selected slot")
    p_load.add_argument("slot", type=int, choices=range(1, 12), help="Slot number (1-10, or 11 for emergency)")
    p_load.add_argument("--auto-save", action="store_true", help="Auto-save current active slot before unloading")
    p_load.add_argument("-f", "--force", action="store_true", help="Force overwrite without confirmation")

    # Save
    p_save = subparsers.add_parser("save", help="Backup active ecosystem to slot")
    p_save.add_argument("slot", type=int, choices=range(1, 12), help="Slot number (1-10, or 11)")
    p_save.add_argument("-l", "--label", type=str, default=None, help="Descriptive label for slot")
    p_save.add_argument("--include-sd", action="store_true", help="Include SD card storage in backup")

    # Copy
    p_copy = subparsers.add_parser("copy", help="Copy one slot to another")
    p_copy.add_argument("src", type=int, choices=range(1, 12), help="Source slot number")
    p_copy.add_argument("dst", type=int, choices=range(1, 11), help="Destination slot number (1-10)")

    # Export
    p_export = subparsers.add_parser("export", help="Export slot to zip archive")
    p_export.add_argument("slot", type=int, choices=range(1, 12), help="Slot number to export")
    p_export.add_argument("output", type=str, help="Output ZIP file path")

    # Import
    p_import = subparsers.add_parser("import", help="Import zip archive into slot")
    p_import.add_argument("input", type=str, help="Input ZIP file path")
    p_import.add_argument("slot", type=int, choices=range(1, 11), help="Target slot number (1-10)")
    p_import.add_argument("-l", "--label", type=str, default=None, help="Label for imported slot")

    # Label
    p_label = subparsers.add_parser("label", help="Assign descriptive label to slot")
    p_label.add_argument("slot", type=int, choices=range(1, 12), help="Slot number")
    p_label.add_argument("text", type=str, help="Label text")

    # Emergency Commands
    subparsers.add_parser("emergency-restore", help="Restore Slot 11 (Emergency) and deactivate experimental slots")
    p_emsave = subparsers.add_parser("emergency-save", help="Overwrite Slot 11 (Allowed ONLY in neutral baseline)")
    p_emsave.add_argument("-l", "--label", type=str, default="Master Emergency Golden Image")
    p_emsave.add_argument("--include-sd", action="store_true", help="Include SD card storage")

    args = parser.parse_args()

    try:
        if args.command in ("status", "list"):
            render_slots_table()
            return 0

        elif args.command == "load":
            render_banner(f"LOADING SLOT {args.slot}")
            print_49(f"Target: {get_slot_name(args.slot)}")
            print_49(f"Auto-save current: {args.auto_save}")
            print_49(SUBDIVIDER_49)
            res = slot_load(args.slot, auto_save_current=args.auto_save, force=args.force)
            print_49(f"Prev Slot: {res['previous_slot']} -> Active: {res['active_slot']}")
            print_49(f"Restored : {res['restored']:>5} records")
            render_footer()
            return 0

        elif args.command == "save":
            render_banner(f"SAVING TO SLOT {args.slot}")
            print_49(f"Target : {get_slot_name(args.slot)}")
            if args.label:
                print_49(f"Label  : {args.label}")
            print_49(SUBDIVIDER_49)
            res = slot_save(args.slot, label=args.label, include_sd=args.include_sd)
            print_49(f"Items  : {res['items']:>5} backed up")
            print_49(f"Status : SUCCESS")
            render_footer()
            return 0

        elif args.command == "copy":
            render_banner("CLONING SLOT")
            print_49(f"Source : Slot {args.src}")
            print_49(f"Dest   : Slot {args.dst}")
            print_49(SUBDIVIDER_49)
            res = slot_copy(args.src, args.dst)
            print_49(f"Copied : {res['item_count']:>5} records")
            render_footer()
            return 0

        elif args.command == "export":
            render_banner(f"EXPORTING SLOT {args.slot}")
            out_p = Path(args.output).resolve()
            print_49(f"Target : {out_p.name}")
            print_49(SUBDIVIDER_49)
            slot_export(args.slot, out_p)
            print_49(f"Exported: {out_p.stat().st_size:>8} bytes")
            render_footer()
            return 0

        elif args.command == "import":
            render_banner(f"IMPORTING INTO SLOT {args.slot}")
            in_p = Path(args.input).resolve()
            print_49(f"Source : {in_p.name}")
            print_49(SUBDIVIDER_49)
            res = slot_import(in_p, args.slot, label=args.label)
            print_49(f"Imported: {res['items']:>5} records")
            render_footer()
            return 0

        elif args.command == "label":
            slot_set_label(args.slot, args.text)
            print_49(f"Slot {args.slot} label updated: '{args.text}'")
            return 0

        elif args.command == "emergency-restore":
            render_banner("EMERGENCY RESTORE (SLOT 11)")
            print_49("Restoring golden master baseline...")
            print_49(SUBDIVIDER_49)
            res = slot_emergency_restore()
            print_49(f"Restored: {res['restored']:>5} records")
            print_49("Status  : ALL EXPERIMENTAL SLOTS CLEARED")
            print_49("Emergency Save Lock: UNLOCKED")
            render_footer()
            return 0

        elif args.command == "emergency-save":
            render_banner("EMERGENCY MASTER UPDATE")
            print_49("Verifying lock status...")
            print_49(SUBDIVIDER_49)
            res = slot_save(EMERGENCY_SLOT_ID, label=args.label, include_sd=args.include_sd)
            print_49(f"Golden Master: {res['items']:>5} items saved")
            render_footer()
            return 0

    except Exception as exc:
        render_banner("SLOT OPERATION ERROR")
        print_49(f"ERROR: {str(exc)[:40]}")
        render_footer()
        logger.error("Slot operation failed: %s", exc)
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())
