import time
import threading

import requests

from mediapurge.config import get_config

DEFAULT_TIMEOUT = (10, 30)

_cache = {"movies": None, "movies_time": 0}
_cache_lock = threading.Lock()


def _request_with_retry(method, url, retries=2, **kwargs):
    """Retry on ConnectionError, Timeout, or 502/503/504 with 2-second backoff."""
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    last_exc = None
    for attempt in range(1 + retries):
        try:
            r = method(url, **kwargs)
            if r.status_code in (502, 503, 504) and attempt < retries:
                time.sleep(2)
                continue
            return r
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            if attempt < retries:
                time.sleep(2)
    raise last_exc


def _base() -> tuple[str, dict]:
    cfg = get_config()["radarr"]
    return cfg["url"].rstrip("/"), {"X-Api-Key": cfg["api_key"]}


def get_all_movies() -> list[dict]:
    now = time.time()
    with _cache_lock:
        if _cache["movies"] is not None and (now - _cache["movies_time"]) < 60:
            return _cache["movies"]
    url, headers = _base()
    r = _request_with_retry(requests.get, f"{url}/api/v3/movie", headers=headers)
    r.raise_for_status()
    data = r.json()
    with _cache_lock:
        _cache["movies"] = data
        _cache["movies_time"] = time.time()
    return data


def get_movie_by_path(path: str) -> dict | None:
    for m in get_all_movies():
        if path.startswith(m.get("path", "")):
            return m
    return None


def delete_movie(movie_id: int, delete_files: bool = True):
    url, headers = _base()
    r = requests.delete(
        f"{url}/api/v3/movie/{movie_id}",
        headers=headers,
        params={"deleteFiles": str(delete_files).lower()},
        timeout=DEFAULT_TIMEOUT,
    )
    r.raise_for_status()
    with _cache_lock:
        _cache["movies"] = None


def get_root_folders() -> list[str]:
    url, headers = _base()
    r = requests.get(f"{url}/api/v3/rootfolder", headers=headers, timeout=DEFAULT_TIMEOUT)
    r.raise_for_status()
    return [f["path"] for f in r.json()]


def move_movie(movie_id: int, new_root_folder: str):
    """Move a movie to a new root folder."""
    url, headers = _base()
    r = requests.get(f"{url}/api/v3/movie/{movie_id}", headers=headers, timeout=DEFAULT_TIMEOUT)
    r.raise_for_status()
    movie = r.json()
    old_path = movie["path"]
    movie_folder = old_path.rstrip("/").split("/")[-1]
    movie["path"] = f"{new_root_folder.rstrip('/')}/{movie_folder}"
    movie["rootFolderPath"] = new_root_folder
    r = requests.put(f"{url}/api/v3/movie/{movie_id}?moveFiles=true", headers=headers, json=movie, timeout=DEFAULT_TIMEOUT)
    r.raise_for_status()


def get_wanted_movies() -> list[dict]:
    """Get monitored movies without files."""
    return [m for m in get_all_movies() if not m.get('hasFile') and m.get('monitored')]


def command_complete(command_id: int, timeout: int = 60) -> bool:
    """Poll until a Radarr command completes."""
    url, headers = _base()
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(f"{url}/api/v3/command/{command_id}", headers=headers, timeout=DEFAULT_TIMEOUT)
        if r.status_code == 200:
            status = r.json().get("status", "")
            if status in ("completed", "failed"):
                return status == "completed"
        time.sleep(3)
    return False
