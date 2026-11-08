"""Local persistence: users.json plus one face photo per user in imagenes/ (both git-ignored)."""
import json
import uuid
from pathlib import Path

import cv2

BASE_DIR = Path(__file__).resolve().parent.parent
USERS_FILE = BASE_DIR / "users.json"
IMAGES_DIR = BASE_DIR / "imagenes"


def load_users():
    try:
        data = USERS_FILE.read_text(encoding="utf-8")
        return json.loads(data)["users"] if data.strip() else []
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return []


def save_users(users):
    USERS_FILE.write_text(json.dumps({"users": users}, indent=4, ensure_ascii=False), encoding="utf-8")


def find_user(users, name):
    return next((u for u in users if u["name"].strip().lower() == name.strip().lower()), None)


def photo_path(user):
    path = Path(user["photo"])
    return path if path.is_absolute() else BASE_DIR / path


def register_user(name, frame):
    """Save the face photo and create the user. Returns the new user dict."""
    IMAGES_DIR.mkdir(exist_ok=True)
    relative = Path("imagenes") / f"{uuid.uuid4()}.jpg"
    cv2.imwrite(str(BASE_DIR / relative), frame)
    user = {"name": name.strip(), "photo": relative.as_posix(), "medicamentos": {}}
    users = load_users()
    users.append(user)
    save_users(users)
    return user


def save_medications(user):
    """Persist the medication schedule of `user`."""
    users = load_users()
    stored = find_user(users, user["name"])
    if stored is not None:
        stored["medicamentos"] = user["medicamentos"]
        save_users(users)
