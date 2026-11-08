#!/usr/bin/env python3
"""
Парсит только новые FIT-файлы (которых нет в garmin_sessions.json)
и сохраняет их в garmin_sessions_new.json.

Использование:
    python parse_new_fits.py
    python parse_new_fits.py --master garmin_sessions.json --output garmin_sessions_new.json
"""

import argparse
import json
import os
import glob
from datetime import datetime
from pathlib import Path

# Переиспользуем логику из parse_fits.py
from parse_fits import parse_fit_file, classify_activity, save


def load_already_parsed(master_path: str) -> set:
    if not os.path.exists(master_path):
        return set()
    with open(master_path, encoding="utf-8") as f:
        data = json.load(f)
    return {s["file"] for s in data.get("sessions", [])}


def run(fits_dir: str, master_path: str, output_path: str):
    fit_files = sorted(glob.glob(os.path.join(fits_dir, "*.fit")))
    if not fit_files:
        print(f"FIT-файлы не найдены в: {fits_dir}")
        return

    already_parsed = load_already_parsed(master_path)
    new_files = [f for f in fit_files if os.path.basename(f) not in already_parsed]

    if not new_files:
        print(f"Новых FIT-файлов нет — всё уже в {master_path}")
        return

    print(f"Найдено новых файлов: {len(new_files)}")

    # Загружаем уже накопленные новые сессии (если файл существует)
    existing_new = []
    if os.path.exists(output_path):
        with open(output_path, encoding="utf-8") as f:
            existing_new = json.load(f).get("sessions", [])
        existing_new_files = {s["file"] for s in existing_new}
        new_files = [f for f in new_files if os.path.basename(f) not in existing_new_files]
        if not new_files:
            print(f"Все новые файлы уже в {output_path} ({len(existing_new)} сессий)")
            return

    sessions = list(existing_new)
    errors = []
    parsed_ok = parsed_err = 0

    for filepath in new_files:
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
    print(f"Добавлено новых: {parsed_ok}")
    print(f"Ошибок:          {parsed_err}")
    print(f"Итого в файле:   {len(sessions)} сессий")
    print(f"Файл: {output_path} ({size_kb} КБ)")
    print(f"─────────────────────────────────")


def main():
    base = Path(__file__).parent
    parser = argparse.ArgumentParser(description="Парсер только новых FIT-файлов → garmin_sessions_new.json")
    parser.add_argument("--fits",   default=str(base / "garmin_fits"),            help="Папка с FIT-файлами")
    parser.add_argument("--master", default=str(base / "garmin_sessions.json"),   help="Основной JSON (уже разобранные)")
    parser.add_argument("--output", default=str(base / "garmin_sessions_new.json"), help="Выходной файл для новых")
    args = parser.parse_args()

    run(args.fits, args.master, args.output)


if __name__ == "__main__":
    main()
