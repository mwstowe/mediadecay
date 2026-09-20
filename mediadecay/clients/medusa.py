import time
import threading

import requests

from mediadecay.config import get_config

DEFAULT_TIMEOUT = (10, 30)

_cache = {"shows": None, "shows_time": 0}
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


def _base() -> tuple[str, dict, bool]:
    cfg = get_config()["medusa"]
    verify_ssl = cfg.get("verify_ssl", False)
    return cfg["url"].rstrip("/"), {"X-Api-Key": cfg["api_key"]}, verify_ssl


def _get(url, headers, verify=False):
    return requests.get(url, headers=headers, verify=verify, timeout=DEFAULT_TIMEOUT)


def get_all_shows() -> list[dict]:
    now = time.time()
    with _cache_lock:
        if _cache["shows"] is not None and (now - _cache["shows_time"]) < 60:
            return _cache["shows"]
    url, headers, verify = _base()
    r = _request_with_retry(requests.get, f"{url}/api/v2/series?limit=1000", headers=headers, verify=verify)
    r.raise_for_status()
    data = r.json()
    with _cache_lock:
        _cache["shows"] = data
        _cache["shows_time"] = time.time()
    return data


def get_show_by_path(path: str) -> dict | None:
    for s in get_all_shows():
        show_path = s.get("config", {}).get("location", s.get("location", ""))
        if path.startswith(show_path):
            return s
    return None


def delete_show(show_slug: str, remove_files: bool = True):
    url, headers, verify = _base()
    r = requests.delete(
        f"{url}/api/v2/series/{show_slug}",
        headers=headers,
        json={"remove": True, "removeFiles": remove_files},
        verify=verify,
        timeout=DEFAULT_TIMEOUT,
    )
    r.raise_for_status()
    with _cache_lock:
        _cache["shows"] = None


def ignore_episode(show_slug: str, season: int, episode: int):
    """Mark an episode as Ignored and clear its quality and release info."""
    url, headers, verify = _base()
    ep_id = f"s{season:02d}e{episode:02d}"
    r = requests.patch(
        f"{url}/api/v2/series/{show_slug}/episodes/{ep_id}",
        headers=headers,
        json={"status": 7, "quality": 0, "release": {"name": ""}},
        verify=verify,
        timeout=DEFAULT_TIMEOUT,
    )
    r.raise_for_status()


def refresh_show(show_slug: str):
    """Trigger a show refresh to clear stale file info."""
    url, headers, verify = _base()
    cfg = get_config()["medusa"]
    # Extract TVDB ID from slug (e.g., "tvdb448176" -> 448176)
    tvdb_id = show_slug.replace("tvdb", "")
    r = requests.get(
        f"{url}/api/v1/{cfg['api_key']}/?cmd=show.refresh&tvdbid={tvdb_id}",
        verify=verify,
        timeout=DEFAULT_TIMEOUT,
    )
    r.raise_for_status()


def get_root_folders() -> list[str]:
    """Get unique root folders from Medusa's managed shows."""
    folders = set()
    for s in get_all_shows():
        path = s.get("config", {}).get("location", "")
        if path:
            # Root folder is the parent of the show folder
            parent = "/".join(path.rstrip("/").split("/")[:-1])
            folders.add(parent)
    return sorted(folders)


def add_show(tvdb_id: int, location: str, anime: bool = False, show_list: str = None, default_status: str = "Wanted"):
    """Add a show to Medusa, then patch its config (Medusa ignores config at add time)."""
    url, headers, verify = _base()

    # Step 1: Add the show (Medusa ignores config in POST)
    r = requests.post(
        f"{url}/api/v2/series",
        headers=headers,
        json={"id": {"tvdb": tvdb_id}},
        verify=verify,
        timeout=DEFAULT_TIMEOUT,
    )
    r.raise_for_status()

    # Step 2: Wait for Medusa to process the add (poll until show appears)
    slug = f"tvdb{tvdb_id}"
    deadline = time.time() + 30
    while time.time() < deadline:
        with _cache_lock:
            _cache["shows"] = None  # bust cache
        try:
            if any(s.get("id", {}).get("slug") == slug for s in get_all_shows()):
                break
        except Exception:
            pass
        time.sleep(3)

    # Step 3: Patch config — set defaultEpisodeStatus to Ignored first to prevent downloads
    config_patch = {"config": {
        "location": location,
        "anime": anime,
        "defaultEpisodeStatus": "Ignored",
        "paused": True,
    }}
    if show_list:
        config_patch["config"]["showLists"] = [show_list]
    elif anime:
        config_patch["config"]["showLists"] = ["anime"]
    requests.patch(f"{url}/api/v2/series/{slug}", headers=headers, json=config_patch, verify=verify, timeout=DEFAULT_TIMEOUT)
    if anime:
        requests.patch(f"{url}/api/v2/series/{slug}", headers=headers, json={"showType": "anime"}, verify=verify, timeout=DEFAULT_TIMEOUT)

    # Step 4: Refresh to detect existing files (sets them to Downloaded)
    refresh_show(slug)
    # Poll until the show's episode data is populated (indicates refresh complete)
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            ep_r = _get(f"{url}/api/v2/series/{slug}/episodes?limit=1", headers, verify=verify)
            if ep_r.status_code == 200 and ep_r.json():
                break
        except Exception:
            pass
        time.sleep(3)

    # Step 5: Unpause and set the real defaultEpisodeStatus for future episodes
    requests.patch(f"{url}/api/v2/series/{slug}", headers=headers,
                   json={"config": {"defaultEpisodeStatus": default_status, "paused": False}}, verify=verify, timeout=DEFAULT_TIMEOUT)


def get_wanted_shows() -> list[dict]:
    """Get shows with wanted episodes."""
    return get_all_shows()
