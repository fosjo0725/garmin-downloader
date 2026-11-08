#!/usr/bin/env python3
"""
Переносит сессии из garmin_sessions_new.json в garmin_sessions.json.
После переноса в garmin_sessions_new.json остаются только сессии,
добавленные в этот запуск (которых ещё не было в основном файле).

Использование:
    python merge_sessions.py
    python merge_sessions.py --master garmin_sessions.json --new garmin_sessions_new.json
"""

import argparse
import json
import os
from datetime import datetime

DEFAULT_MASTER = "garmin_sessions.json"
DEFAULT_NEW = "garmin_sessions_new.json"


def load(path):
    if not os.path.exists(path):
        return {"metadata": {}, "sessions": [], "parse_errors": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, sessions, errors):
    sessions_sorted = sorted(sessions, key=lambda x: x["date"])
    data = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "total_sessions": len(sessions_sorted),
            "errors": len(errors),
            "date_range": {
                "first": sessions_sorted[0]["date"] if sessions_sorted else None,
                "last": sessions_sorted[-1]["date"] if sessions_sorted else None,
            },
        },
        "sessions": sessions_sorted,
        "parse_errors": errors,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def run(master_path, new_path):
    master = load(master_path)
    new = load(new_path)

    master_files = {s["file"] for s in master["sessions"]}

    truly_new = [s for s in new["sessions"] if s["file"] not in master_files]
    already_known = [s for s in new["sessions"] if s["file"] in master_files]

    if not truly_new:
        print("Нет новых сессий для переноса.")
        return

    # Переносим новые в основной файл
    merged_sessions = master["sessions"] + truly_new
    merged_errors = master.get("parse_errors", []) + new.get("parse_errors", [])
    save(master_path, merged_sessions, merged_errors)

    # В new оставляем только то, что только что добавлено
    save(new_path, truly_new, new.get("parse_errors", []))

    print(f"Перенесено в {master_path}:  {len(truly_new)}")
    if already_known:
        print(f"Уже были в основном файле: {len(already_known)} (удалены из new)")
    print(f"Итого в {master_path}: {len(merged_sessions)} сессий")
    print(f"Осталось в {new_path}: {len(truly_new)} сессий")
    for s in truly_new:
        print(f"  {s['date']} {s['activity_type']} {s['file']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--master", default=DEFAULT_MASTER)
    parser.add_argument("--new", default=DEFAULT_NEW)
    args = parser.parse_args()

    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    run(args.master, args.new)
