#!/usr/bin/env python3
"""
Garmin FIT Downloader
Скачивает FIT-файлы тренировок из Garmin Connect.

Использование:
    python download_garmin.py
    python download_garmin.py --start 2024-01-01 --end 2024-12-31
    python download_garmin.py --output ~/my_fits
"""

import io
import os
import time
import zipfile
import argparse
import getpass
import warnings
from datetime import date
from pathlib import Path

warnings.filterwarnings("ignore")

import requests

try:
    import garth
except ImportError:
    print("Установи: pip install garminconnect")
    raise SystemExit(1)


BATCH_SIZE = 100
SESSION_DIR = Path.home() / ".garmin_session"
API_BASE = "https://connectapi.garmin.com"
DOWNLOAD_BASE = "https://connectapi.garmin.com"


def get_session(email: str, password: str) -> tuple[str, requests.Session]:
    """Возвращает (access_token, requests.Session с куками SSO)."""
    garth.configure(domain="garmin.com")

    if SESSION_DIR.exists():
        try:
            garth.client.load(str(SESSION_DIR))
            # Проверяем что токен ещё живой
            token = garth.client.oauth2_token
            if token and token.access_token:
                print("Использую сохранённую сессию.")
                return _make_session(token.access_token)
        except Exception:
            print("Сохранённая сессия устарела, логинюсь заново...")

    garth.login(email, password)

    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    garth.client.dump(str(SESSION_DIR))
    print("Сессия сохранена.\n")

    return _make_session(garth.client.oauth2_token.access_token)


def _make_session(access_token: str) -> tuple[str, requests.Session]:
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {access_token}",
        "NK": "NT",
        "Accept": "application/json",
        "User-Agent": "GarminConnect/4.70 (Android)",
    })
    return access_token, s


def fetch_activities(sess: requests.Session, start: int, limit: int) -> list:
    resp = sess.get(
        f"{API_BASE}/activitylist-service/activities/search/activities",
        params={"start": start, "limit": limit},
    )
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def download_fit(sess: requests.Session, activity_id: int, filepath: Path):
    resp = sess.get(
        f"{DOWNLOAD_BASE}/download-service/files/activity/{activity_id}",
        headers={"Accept": "*/*"},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.content

    # Garmin отдаёт ZIP с FIT внутри
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            fit_names = [n for n in z.namelist() if n.lower().endswith(".fit")]
            if fit_names:
                filepath.write_bytes(z.read(fit_names[0]))
                return
    except zipfile.BadZipFile:
        pass

    filepath.write_bytes(data)


def run(email: str, password: str, output_dir: Path, start_date: date, end_date: date):
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Логинюсь в Garmin Connect...")
    _, sess = get_session(email, password)
    print("Успешно!\n")

    print(f"Скачиваю активности с {start_date} по {end_date}")
    print(f"Папка: {output_dir.resolve()}\n")

    downloaded = skipped = errors = 0
    offset = 0

    while True:
        try:
            batch = fetch_activities(sess, offset, BATCH_SIZE)
        except Exception as e:
            print(f"Ошибка при получении списка: {e}")
            break

        if not batch:
            break

        stop_early = False
        for activity in batch:
            raw_date = activity.get("startTimeLocal", "")[:10]
            try:
                a_date = date.fromisoformat(raw_date)
            except ValueError:
                continue

            if a_date < start_date:
                stop_early = True
                break
            if a_date > end_date:
                continue

            activity_id = activity["activityId"]
            activity_type = (
                activity.get("activityType", {})
                .get("typeKey", "unknown")
                .replace(" ", "_")
            )
            filename = f"{raw_date}_{activity_type}_{activity_id}.fit"
            filepath = output_dir / filename

            if filepath.exists():
                print(f"  [пропуск]  {filename}")
                skipped += 1
                continue

            print(f"  [скачиваю] {filename}", end="", flush=True)
            try:
                download_fit(sess, activity_id, filepath)
                print(" ✓")
                downloaded += 1
                time.sleep(0.3)
            except Exception as e:
                print(f" ✗  ({e})")
                errors += 1

        if stop_early:
            break

        offset += BATCH_SIZE
        time.sleep(0.5)

    print(f"\n─────────────────────────────────")
    print(f"Скачано:            {downloaded}")
    print(f"Пропущено (есть):   {skipped}")
    print(f"Ошибок:             {errors}")
    print(f"─────────────────────────────────")
    print(f"FIT-файлы в: {output_dir.resolve()}")


def main():
    parser = argparse.ArgumentParser(description="Скачать FIT-файлы из Garmin Connect")
    parser.add_argument("--email", help="Email от Garmin Connect")
    parser.add_argument("--password", help="Пароль")
    parser.add_argument("--output", default="garmin_fits", help="Папка для сохранения")
    parser.add_argument("--start", default="2000-01-01", help="Начальная дата YYYY-MM-DD")
    parser.add_argument("--end", default=str(date.today()), help="Конечная дата YYYY-MM-DD")
    args = parser.parse_args()

    email = args.email or os.environ.get("GARMIN_EMAIL") or input("Garmin email: ")
    password = args.password or os.environ.get("GARMIN_PASSWORD") or getpass.getpass("Garmin пароль: ")

    try:
        start_date = date.fromisoformat(args.start)
        end_date = date.fromisoformat(args.end)
    except ValueError as e:
        print(f"Неверный формат даты: {e}")
        raise SystemExit(1)

    run(email, password, Path(args.output), start_date, end_date)


if __name__ == "__main__":
    main()
