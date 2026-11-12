#!/data/data/com.termux/files/usr/bin/env python3
"""
# Name:          app.py
# Description:   Flask Web Dashboard & REST API for Loaded Chamber Disc Changer
# Version:       10400
# Date Created:  2026-11-12
# Author Credit: Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
# License:       PolyForm Noncommercial License 1.0.0 (PolyForm-Noncommercial-1.0.0)
# RELATIONAL_ID: ed36bda3-5342-4636-bca1-30c58a7c08c8
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from flask import Flask, jsonify, render_template, request

# Setup path and engine imports
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import universal_snapshot_engine as engine

app = Flask(
    __name__,
    template_folder=str(SCRIPT_DIR / "templates"),
    static_folder=str(SCRIPT_DIR / "static")
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("chamber_web")


def get_current_dashboard_data(profile_name: str | None = None) -> dict:
    """Compile dictionary of profiles, active profile, slots, and path rules."""
    active_prof = profile_name or engine.get_active_profile_name()
    profiles_doc = engine.init_master_profiles_registry()
    p_map = engine.bejson_get_field_map(profiles_doc)

    profiles_list = []
    for r in profiles_doc.get("Values", []):
        profiles_list.append({
            "name": r[p_map["profile_name"]],
            "label": r[p_map["profile_label"]],
            "is_active": (r[p_map["profile_name"]] == active_prof),
            "created_at": r[p_map["created_at"]]
        })

    # Slots for active profile
    slots_doc = engine.init_profile_slots_registry(active_prof)
    s_map = engine.bejson_get_field_map(slots_doc)
    active_slot_id = slots_doc.get("Active_Slot_ID", 0)
    emergency_restored = slots_doc.get("Emergency_Restored_Flag", False)

    slots_list = []
    for r in slots_doc.get("Values", []):
        sid = r[s_map["slot_id"]]
        slots_list.append({
            "slot_id": sid,
            "slot_name": r[s_map["slot_name"]],
            "slot_label": r[s_map["slot_label"]],
            "is_active": r[s_map["is_active"]],
            "is_emergency": r[s_map["is_emergency"]],
            "item_count": r[s_map["item_count"]],
            "last_saved": r[s_map["last_saved"]],
            "last_loaded": r[s_map["last_loaded"]]
        })

    # Path rules for active profile
    cfg_doc = engine.bejson_load_104a(engine.SLOTS_BASE_DIR / active_prof / "config.104a.bejson")
    rules_list = []
    if cfg_doc:
        r_map = engine.bejson_get_field_map(cfg_doc)
        for r in cfg_doc.get("Values", []):
            rules_list.append({
                "rule_id": r[r_map["rule_id"]],
                "category": r[r_map["category"]],
                "source_path": r[r_map["source_path"]],
                "extension_filter": r[r_map["extension_filter"]] or "*",
                "is_recursive": r[r_map["is_recursive"]],
                "pack_type": r[r_map["pack_type"]],
                "target_subfolder": r[r_map["target_subfolder"]]
            })

    return {
        "active_profile": active_prof,
        "active_slot_id": active_slot_id,
        "emergency_restored": emergency_restored,
        "profiles": profiles_list,
        "slots": slots_list,
        "rules": rules_list
    }


# ---------------------------------------------------------------------------
# HTML Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    prof = request.args.get("profile", None)
    data = get_current_dashboard_data(prof)
    return render_template("index.html", **data)


# ---------------------------------------------------------------------------
# REST API Endpoints
# ---------------------------------------------------------------------------
@app.route("/api/status", methods=["GET"])
def api_status():
    prof = request.args.get("profile", None)
    try:
        data = get_current_dashboard_data(prof)
        return jsonify({"status": "success", "data": data})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.route("/api/slot/load", methods=["POST"])
def api_slot_load():
    req = request.get_json() or {}
    slot_id = int(req.get("slot_id", 1))
    profile_name = req.get("profile", engine.get_active_profile_name())
    auto_save = bool(req.get("auto_save", False))
    force = bool(req.get("force", False))

    try:
        res = engine.universal_slot_load(
            profile_name=profile_name,
            slot_id=slot_id,
            auto_save_current=auto_save,
            force=force
        )
        return jsonify({"status": "success", "result": res})
    except Exception as exc:
        logger.error("api_slot_load failed: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 400


@app.route("/api/slot/save", methods=["POST"])
def api_slot_save():
    req = request.get_json() or {}
    slot_id = int(req.get("slot_id", 1))
    profile_name = req.get("profile", engine.get_active_profile_name())
    label = req.get("label", None)

    try:
        res = engine.universal_slot_save(profile_name=profile_name, slot_id=slot_id, label=label)
        return jsonify({"status": "success", "result": res})
    except Exception as exc:
        logger.error("api_slot_save failed: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 400


@app.route("/api/slot/copy", methods=["POST"])
def api_slot_copy():
    req = request.get_json() or {}
    src_id = int(req.get("src_id", 1))
    dst_id = int(req.get("dst_id", 2))
    profile_name = req.get("profile", engine.get_active_profile_name())

    try:
        res = engine.universal_slot_copy(profile_name=profile_name, src_id=src_id, dst_id=dst_id)
        return jsonify({"status": "success", "result": res})
    except Exception as exc:
        logger.error("api_slot_copy failed: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 400


@app.route("/api/slot/emergency-restore", methods=["POST"])
def api_slot_emergency_restore():
    req = request.get_json() or {}
    profile_name = req.get("profile", engine.get_active_profile_name())

    try:
        res = engine.universal_slot_emergency_restore(profile_name=profile_name)
        return jsonify({"status": "success", "result": res})
    except Exception as exc:
        logger.error("api_slot_emergency_restore failed: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 400


@app.route("/api/profile/select", methods=["POST"])
def api_profile_select():
    req = request.get_json() or {}
    profile_name = req.get("profile_name", "").strip()
    if not profile_name:
        return jsonify({"status": "error", "message": "profile_name required"}), 400

    try:
        engine.set_active_profile_name(profile_name)
        return jsonify({"status": "success", "active_profile": profile_name})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400


@app.route("/api/profile/create", methods=["POST"])
def api_profile_create():
    req = request.get_json() or {}
    profile_name = req.get("profile_name", "").strip()
    label = req.get("label", "").strip()
    if not profile_name:
        return jsonify({"status": "error", "message": "profile_name required"}), 400

    try:
        res = engine.create_new_profile(profile_name=profile_name, label=label)
        return jsonify({"status": "success", "result": res})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400


@app.route("/api/profile/add-path", methods=["POST"])
def api_profile_add_path():
    req = request.get_json() or {}
    profile_name = req.get("profile", engine.get_active_profile_name())
    category = req.get("category", "").strip()
    source_path = req.get("source_path", "").strip()
    extension_filter = req.get("extension_filter", "").strip()
    is_recursive = bool(req.get("is_recursive", False))
    pack_type = req.get("pack_type", "file")
    target_subfolder = req.get("target_subfolder", "")

    if not category or not source_path:
        return jsonify({"status": "error", "message": "category and source_path required"}), 400

    try:
        res = engine.profile_add_path(
            profile_name=profile_name,
            category=category,
            source_path=source_path,
            extension_filter=extension_filter,
            is_recursive=is_recursive,
            pack_type=pack_type,
            target_subfolder=target_subfolder
        )
        return jsonify({"status": "success", "result": res})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400


# ---------------------------------------------------------------------------
# CLI Direct Launch Runner
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Loaded Chamber Flask Web Application")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host address to bind")
    parser.add_argument("--port", type=int, default=5080, help="Port to listen on")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    logger.info("Starting Loaded Chamber Web Server on http://%s:%d", args.host, args.port)
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
