#!/usr/bin/env python3
"""
Garmin FIT Parser
Парсит FIT-файлы и сохраняет сессии в JSON.

Использование:
    python parse_fits.py                        # парсит новые файлы, обновляет JSON
    python parse_fits.py --force                # перепарсить все файлы заново
    python parse_fits.py --fits ~/other_fits    # другая папка с FIT-файлами
    python parse_fits.py --output sessions.json # другой путь для JSON
"""

import argparse
import glob
import json
import os
from datetime import datetime
from pathlib import Path

try:
    import fitparse
except ImportError:
    print("Установи: pip install fitparse")
    raise SystemExit(1)


ACTIVITY_TYPE_MAP = {
    "cycling": "cycling",
    "strength_training": "strength_training",
    "running": "running",
    "walking": "walking",
    "swimming": "swimming",
    "squash": "squash",
    "hiit": "hiit",
    "pilates": "pilates",
    "yoga": "yoga_breathwork",
    "breathwork": "yoga_breathwork",
    "indoor_cardio": "indoor_cardio",
    "mobility": "mobility",
    "hiking": "hiking",
}


def classify_activity(activity_name: str, sport: str) -> str:
    name = activity_name.lower()
    for key, label in ACTIVITY_TYPE_MAP.items():
        if key in name:
            return label
    sport_clean = sport.lower().replace("sport.", "")
    for key, label in ACTIVITY_TYPE_MAP.items():
        if key in sport_clean:
            return label
    return name or sport_clean or "unknown"


# HRmax used for zone computation (from observed data, not 220-age formula)
HRMAX = 183

# Zone boundaries as fractions of HRmax
HR_ZONES = [
    ("z1_recovery",  0.00, 0.50),
    ("z2_aerobic",   0.50, 0.60),
    ("z3_moderate",  0.60, 0.70),
    ("z4_threshold", 0.70, 0.80),
    ("z5_anaerobic", 0.80, 1.00),
]


def _compute_hr_zones(hr_values: list, hrmax: int = HRMAX) -> dict:
    if not hr_values:
        return {name: None for name, *_ in HR_ZONES}
    zones = {name: 0 for name, *_ in HR_ZONES}
    for hr in hr_values:
        pct = hr / hrmax
        for name, lo, hi in HR_ZONES:
            if lo <= pct < hi:
                zones[name] += 1
                break
        else:
            zones["z5_anaerobic"] += 1  # above 80% still counts as z5
    # Convert sample counts to seconds (1 sample ≈ 1 second)
    return {name: zones[name] for name, *_ in HR_ZONES}


def _parse_sets(fit: fitparse.FitFile) -> tuple:
    """Returns (workout_name, sets_list) from workout/workout_step/set messages."""
    workout_name = None
    steps: dict[int, dict] = {}
    raw_sets = []

    for record in fit.get_messages():
        if record.name == "workout":
            workout_name = record.get_value("wkt_name")

        elif record.name == "workout_step":
            idx = record.get_value("message_index")
            if idx is not None:
                raw_cat = record.get_value("exercise_category")
                # fitparse returns a string for known categories, int for unknown ones
                cat = str(raw_cat).lower() if raw_cat is not None and not isinstance(raw_cat, int) else None
                steps[idx] = {
                    "exercise": cat,
                    "exercise_variant": record.get_value("exercise_name"),
                    "planned_weight_kg": record.get_value("exercise_weight"),
                    "planned_reps": record.get_value("duration_reps"),
                }

        elif record.name == "set":
            raw_sets.append({f.name: f.value for f in record})

    sets = []
    for s in raw_sets:
        set_type = str(s.get("set_type", "")).lower()
        if set_type == "rest":
            dur = s.get("duration")
            sets.append({"type": "rest", "duration_s": round(dur, 1) if dur is not None else None})
        elif set_type == "active":
            step_info = steps.get(s.get("wkt_step_index"), {})
            ts = s.get("start_time")
            sets.append({
                "type": "active",
                "exercise": step_info.get("exercise") or None,
                "exercise_variant": step_info.get("exercise_variant"),
                "weight_kg": s.get("weight"),
                "reps": s.get("repetitions"),
                "duration_s": round(s["duration"], 1) if s.get("duration") is not None else None,
                "start_time": ts.isoformat() if hasattr(ts, "isoformat") else None,
            })

    return workout_name, sets


def parse_fit_file(filepath: str) -> dict:
    try:
        fit = fitparse.FitFile(filepath)
        session = {}
        hr_values = []

        for record in fit.get_messages():
            if record.name == "session":
                for field in record:
                    if field.value is not None:
                        session[field.name] = field.value
            elif record.name == "record":
                hr = record.get_value("heart_rate")
                if hr and 30 < hr < 250:
                    hr_values.append(hr)

        result = {}

        ts = session.get("start_time")
        result["start_time"] = ts.isoformat() if hasattr(ts, "isoformat") else str(ts) if ts else None

        result["sport"] = str(session.get("sport", "")).replace("Sport.", "")
        result["sub_sport"] = str(session.get("sub_sport", "")).replace("SubSport.", "")

        elapsed = session.get("total_elapsed_time") or session.get("total_timer_time")
        timer = session.get("total_timer_time")
        result["duration_s"] = round(elapsed, 1) if elapsed else None
        result["duration_active_s"] = round(timer, 1) if timer else None
        result["duration_min"] = round(elapsed / 60, 1) if elapsed else None

        dist = session.get("total_distance")
        result["distance_m"] = round(dist, 1) if dist else 0
        result["distance_km"] = round(dist / 1000, 3) if dist else 0

        result["calories"] = session.get("total_calories", 0)

        result["avg_hr"] = int(session["avg_heart_rate"]) if session.get("avg_heart_rate") else (
            round(sum(hr_values) / len(hr_values)) if hr_values else None
        )
        result["max_hr"] = int(session["max_heart_rate"]) if session.get("max_heart_rate") else (
            max(hr_values) if hr_values else None
        )
        result["min_hr"] = session.get("min_heart_rate") or (min(hr_values) if hr_values else None)
        result["hr_samples"] = len(hr_values)

        # Zones computed from raw HR records (not session summary fields, which are often empty)
        result["hr_zones"] = _compute_hr_zones(hr_values)

        avg_speed = session.get("avg_speed")
        max_speed = session.get("max_speed")
        result["avg_speed_kmh"] = round(avg_speed * 3.6, 2) if avg_speed else None
        result["max_speed_kmh"] = round(max_speed * 3.6, 2) if max_speed else None

        result["avg_power_w"] = session.get("avg_power")
        result["max_power_w"] = session.get("max_power")
        result["normalized_power_w"] = session.get("normalized_power")

        result["training_effect_aerobic"] = session.get("aerobic_training_effect")
        result["training_effect_anaerobic"] = session.get("anaerobic_training_effect")
        result["training_stress_score"] = session.get("training_stress_score")

        result["total_ascent_m"] = session.get("total_ascent")
        result["total_descent_m"] = session.get("total_descent")

        result["avg_cadence"] = session.get("avg_cadence")
        result["max_cadence"] = session.get("max_cadence")

        # Strength-specific: workout name + sets with exercises, weight, reps
        fit2 = fitparse.FitFile(filepath)
        workout_name, sets = _parse_sets(fit2)
        result["workout_name"] = workout_name
        result["sets"] = sets if sets else None

        return result

    except Exception as e:
        return {"_error": str(e)}


def load_existing(output_path: str) -> dict:
    if os.path.exists(output_path):
        with open(output_path, encoding="utf-8") as f:
            return json.load(f)
    return {"metadata": {}, "sessions": [], "parse_errors": []}


def save(output_path: str, sessions: list, errors: list, fits_dir: str):
    sessions_sorted = sorted(sessions, key=lambda x: x["date"])
    output = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "total_sessions": len(sessions_sorted),
            "errors": len(errors),
            "date_range": {
                "first": sessions_sorted[0]["date"] if sessions_sorted else None,
                "last": sessions_sorted[-1]["date"] if sessions_sorted else None,
            },
            "source_dir": str(fits_dir),
        },
        "sessions": sessions_sorted,
        "parse_errors": errors,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)


def run(fits_dir: str, output_path: str, force: bool):
    fit_files = sorted(glob.glob(os.path.join(fits_dir, "*.fit")))
    if not fit_files:
        print(f"FIT-файлы не найдены в: {fits_dir}")
        return

    existing = load_existing(output_path)
    existing_sessions = existing.get("sessions", [])
    existing_errors = existing.get("parse_errors", [])

    already_parsed = {s["file"] for s in existing_sessions}

    if force:
        to_parse = fit_files
        sessions = []
        errors = []
        print(f"--force: перепаршиваем все {len(to_parse)} файлов")
    else:
        to_parse = [f for f in fit_files if os.path.basename(f) not in already_parsed]
        sessions = list(existing_sessions)
        errors = list(existing_errors)
        if not to_parse:
            print(f"Новых файлов нет. JSON актуален ({len(sessions)} сессий).")
            return
        print(f"Найдено новых файлов: {len(to_parse)} (уже в JSON: {len(already_parsed)})")

    parsed_ok = parsed_err = 0

    for filepath in to_parse:
        fname = os.path.basename(filepath)
        parts = fname.split("_")
        date_str = parts[0]
        activity_name = "_".join(parts[1:-1])
        file_id = parts[-1].replace(".fit", "")

        print(f"  Парсю {fname}", end="", flush=True)
        result = parse_fit_file(filepath)

        if "_error" in result:
            print(f" ✗  ({result['_error']})")
            errors.append({"file": fname, "error": result["_error"]})
            parsed_err += 1
            continue

        result["file"] = fname
        result["file_id"] = file_id
        result["date"] = date_str
        result["activity_name"] = activity_name
        result["activity_type"] = classify_activity(activity_name, result.get("sport", ""))

        sessions.append(result)
        print(" ✓")
        parsed_ok += 1

    save(output_path, sessions, errors, fits_dir)

    size_kb = os.path.getsize(output_path) // 1024
    print(f"\n─────────────────────────────────")
    print(f"Добавлено:   {parsed_ok}")
    print(f"Ошибок:      {parsed_err}")
    print(f"Итого в JSON: {len(sessions)} сессий")
    print(f"Файл: {output_path} ({size_kb} КБ)")
    print(f"─────────────────────────────────")


def main():
    default_fits = str(Path(__file__).parent / "garmin_fits")
    default_out = str(Path(__file__).parent / "garmin_sessions.json")

    parser = argparse.ArgumentParser(description="Парсер Garmin FIT → JSON")
    parser.add_argument("--fits", default=default_fits, help="Папка с FIT-файлами")
    parser.add_argument("--output", default=default_out, help="Путь для JSON")
    parser.add_argument("--force", action="store_true", help="Перепарсить все файлы заново")
    args = parser.parse_args()

    run(args.fits, args.output, args.force)


if __name__ == "__main__":
    main()
