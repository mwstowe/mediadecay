# MediaDecay

<p align="center"><img src="https://raw.githubusercontent.com/mwstowe/mediadecay/master/MediaDecay.png" alt="MediaDecay" width="200"></p>

Automated media lifecycle management for Plex. Manages deletion and relocation of media across Plex, Sonarr, Radarr, Medusa, and Ombi based on configurable rules.

## What It Does

- Evaluates rules against your Plex libraries to determine what media should be cleaned up or moved
- Deletes media through the managing application (Sonarr, Radarr, or Medusa) so downloads don't recur
- Moves media between libraries and managers (e.g., Medusa → Sonarr, or between Radarr root folders)
- Cleans up associated Ombi requests when media is deleted
- Auto-approves Ombi requests for media already in Plex (matched by TVDB/IMDB/TMDB ID)
- Detects orphaned media (exists in Plex but isn't managed by any app)
- Removes empty Plex collections left behind after their members are deleted (optional)
- Confirms with users via email before acting, with configurable grace periods and keep methods
- Provides a web UI for browsing Plex libraries, managing rules, and running maintenance
- Reports space recovered after maintenance runs

## How Rules Work

### Scopes

Rules are evaluated from most specific to least specific. The first matching scope wins:

1. **Episode** — applies to a single episode
2. **Season** — applies to all episodes in a specific season
3. **Show / Movie** — applies to a specific show or movie
4. **Library** — applies to everything in a Plex library

Multiple rules can exist at the same scope (e.g., two library rules for "Movies"). Each is evaluated independently — first trigger that fires wins.

If no rule matches, the default action is **keep**.

### Actions

| Action | Description |
|--------|-------------|
| **Keep** | Protect this media from broader delete/move rules |
| **Delete** | Remove media when trigger conditions are met |
| **Move** | Relocate media to a different library/manager when conditions are met |

### Triggers

Each rule has one or more triggers that determine *when* the action fires:

| Trigger Type | Fires when... |
|-------------|---------------|
| **After watched** | Specified user(s) have watched the media, and a grace period has passed |
| **After inactivity** | No one has watched anything in the show/movie for N days |
| **After age** | N days have passed since the media was added to Plex |

Each trigger independently specifies whether to act immediately or confirm first.

### Episode Handling (shows only, delete action)

| Option | Description |
|--------|-------------|
| **Processing mode** | Per episode (delete individual episodes) or per season (delete whole seasons when all episodes qualify) |
| **Min episodes/seasons** | Always keep the latest N, even if they qualify |
| **Protect On Deck** | Skip items on a user's on-deck list |
| **Remove show when empty** | After all episodes are deleted: never / if ended / always remove the show from its manager |

Move rules always operate on the entire show — no per-episode moves.

### Confirmation Workflow

When a trigger is set to "Confirm first":

1. Media becomes eligible per the trigger condition
2. An email is sent to the configured user(s) with available keep methods
3. The system waits N days for a response
4. **If the user acts** → deletion/move is cancelled, a "kept" confirmation email is sent
5. **If no response** → action proceeds

Available keep methods (depends on trigger type):

| Trigger Type | Valid keep methods |
|-------------|-------------------|
| After watched | Mark as unwatched, Snooze (reset timer), Disable trigger |
| After inactivity | Start watching, Snooze, Disable trigger |
| After age | Snooze, Disable trigger |

Confirmation emails include clickable links and an explicit deletion date.

### Move Feature

Moves relocate media between libraries or managers:

- **Radarr → Radarr**: Uses Radarr's native move API (atomic)
- **Sonarr → Sonarr**: Uses Sonarr's native move API (atomic)
- **Sonarr ↔ Medusa**: Moves files, adds to new manager, removes from old manager with rollback on failure
- **Episode status is preserved**: Ignored/Skipped → Unmonitored (and vice versa)

Safety features:
- Pre-flight checks (disk space, permissions, destination manager reachability)
- Source show is unmonitored before file moves to prevent redownloads
- Rollback if the destination manager rejects the show
- Same-filesystem moves are instant (rename, not copy)
- Crash recovery: incomplete moves from a previous run (e.g., interrupted by a crash) are detected and reconciled at the start of the next maintenance run

**Note on watch status after moves:** Plex watch status is preserved across moves, but the "last watched" timestamp resets to the time of the move (Plex API limitation). This means any "after watched" triggers in the destination library's rules will start their countdown from when the move happened, not when the media was originally watched.

## Configuration

Copy `config.yaml.example` to `config.yaml` and fill in your values.

### Connections

```yaml
plex:
  url: http://127.0.0.1:32400
  token: "YOUR_PLEX_TOKEN"
  user_tokens:
    alice: "ALICE_PLEX_TOKEN"
    bob: "BOB_PLEX_TOKEN"
  user_emails:
    admin: admin@example.com
    alice: alice@example.com

sonarr:
  url: http://127.0.0.1:8989
  api_key: "YOUR_KEY"

radarr:
  url: http://127.0.0.1:7878
  api_key: "YOUR_KEY"

medusa:
  url: https://127.0.0.1:8081
  api_key: "YOUR_KEY"

ombi:
  url: http://127.0.0.1:5000
  api_key: "YOUR_KEY"
```

`user_emails` maps Plex usernames to email addresses for confirmation emails. Entries that aren't Plex users are still available as email destinations.

#### User Tokens

`user_tokens` provides per-user Plex tokens so MediaDecay can check watch status for individual users. Without a token for a user, it falls back to the admin token — which gives incorrect results.

The admin/server owner doesn't need an entry — the main `token` is used for them.

To get a user's token:
```bash
python3 -c "
from plexapi.server import PlexServer
s = PlexServer('http://127.0.0.1:32400', 'YOUR_ADMIN_TOKEN')
for u in s.myPlexAccount().users():
    print(f'{u.username or u.title}: {u.get_token(s.machineIdentifier)}')
"
```

### Web UI

```yaml
web:
  secret_key: "RANDOM_SECRET"
  admin_password: "$2b$12$..."  # bcrypt hash
  base_url: "https://mediadecay.example.com:9393"
  port: 9393
  ssl_cert: /etc/mediadecay/ssl/fullchain.pem
  ssl_key: /etc/mediadecay/ssl/privkey.pem
```

Generate a password hash:
```bash
python3 -c "import bcrypt; print(bcrypt.hashpw(b'yourpassword', bcrypt.gensalt()).decode())"
```

### Notifications

```yaml
notifications:
  enabled: true
  method: email
  email:
    from: mediadecay@example.com
    admin: admin@example.com
    smtp_host: smtp.example.com
    smtp_port: 587
    smtp_user: ""
    smtp_pass: ""
  discord:
    webhook_url: ""
```

### Maintenance

```yaml
maintenance:
  dry_run: false
  schedule: "03:00"
  log_file: /var/log/mediadecay/mediadecay.log
  remove_empty_collections: true   # delete Plex collections that have no members
  excluded_libraries:
    - "3D Movies"
```

The database path defaults to `mediadecay.db` relative to the working
directory. For a packaged install, set it explicitly:

```yaml
database:
  path: /var/lib/mediadecay/mediadecay.db
```

## Installation

MediaDecay installs as a Python package providing two entry points,
`mediadecay-web` (web UI + scheduler) and `mediadecay-maintenance` (CLI
maintenance run). There are two supported install paths: a Gentoo ebuild
(recommended on Gentoo) and a manual install anywhere else.

> **Important — which user runs it:** MediaDecay deletes and moves your media
> files, so the service **must run as the user/group that owns those files**
> (for example `sabnzbd`, `plex`, or a dedicated `media` user). This is the one
> setting you must get right regardless of install method.

### Option A — Gentoo (ebuild)

MediaDecay is packaged as `media-video/mediadecay` in the
[stowe-verlay](https://github.com/mwstowe/stowe-verlay) overlay. The overlay
also ships `dev-python/PlexAPI`, so no additional overlay is required.

```bash
# 1. Add the overlay (if not already present), then sync.
#    (eselect repository needs app-eselect/eselect-repository)
sudo eselect repository add stowe-verlay git https://github.com/mwstowe/stowe-verlay.git
sudo emerge --sync stowe-verlay
```

(No `eselect-repository`? Add it manually by creating
`/etc/portage/repos.conf/stowe-verlay.conf` with a `[stowe-verlay]` section
pointing `sync-uri` at the repo, then `emerge --sync stowe-verlay`.)

```bash
# 2. Accept the ~arch keywords (overlay packages are ~amd64)
sudo tee /etc/portage/package.accept_keywords/mediadecay >/dev/null <<'EOF'
media-video/mediadecay ~amd64
dev-python/PlexAPI ~amd64
EOF

# 3. Install
sudo emerge -av media-video/mediadecay
```

The ebuild pulls every dependency, installs the code into site-packages, creates
`/etc/mediadecay`, `/var/lib/mediadecay`, and `/var/log/mediadecay`, and installs
both a systemd unit and an OpenRC service.

**Runtime user via the `sabnzbd` USE flag.** The package defaults to
`USE="sabnzbd"`: it depends on the sabnzbd account, owns the data/log dirs as
`sabnzbd`, and drops in `User=sabnzbd`/`Group=sabnzbd` for the systemd unit. If
your media is owned by a different user, build with `USE="-sabnzbd"` and set the
runtime user yourself (see the post-install notes and "Choosing the runtime
user" below).

Then configure (see [Configuration](#configuration)):

```bash
sudo cp /etc/mediadecay/config.yaml.example /etc/mediadecay/config.yaml
sudo $EDITOR /etc/mediadecay/config.yaml
# Set database.path: /var/lib/mediadecay/mediadecay.db and your credentials.
# Secure it — it contains secrets:
sudo chown root:sabnzbd /etc/mediadecay/config.yaml   # use your runtime group
sudo chmod 0640 /etc/mediadecay/config.yaml
```

Updating later is just `sudo emerge --sync stowe-verlay && sudo emerge -u1 media-video/mediadecay`.

### Option B — manual install (any OS, pip)

Install the package and its dependencies, then set up the directories, config,
and a service yourself.

```bash
# 1. Install dependencies + MediaDecay (from a release tag or a checkout)
pip install flask sqlalchemy pyyaml ruamel.yaml requests bcrypt plexapi cheroot
pip install git+https://github.com/mwstowe/mediadecay.git@v1.0.0
# (or, from a local checkout:  pip install .)

# 2. Create the directories, owned by the user that owns your media
sudo install -d -o MEDIAUSER -g MEDIAGROUP -m 0750 /var/lib/mediadecay /var/log/mediadecay
sudo install -d -o root -g MEDIAGROUP -m 0750 /etc/mediadecay

# 3. Configuration
sudo cp config.yaml.example /etc/mediadecay/config.yaml
sudo $EDITOR /etc/mediadecay/config.yaml          # set credentials + database.path
sudo chown root:MEDIAGROUP /etc/mediadecay/config.yaml
sudo chmod 0640 /etc/mediadecay/config.yaml
```

Create a systemd unit at `/etc/systemd/system/mediadecay.service` (replace
`MEDIAUSER`/`MEDIAGROUP` with the account that owns your media):

```ini
[Unit]
Description=MediaDecay — media lifecycle management for Plex
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=MEDIAUSER
Group=MEDIAGROUP
Environment=MEDIACLEANER_CONFIG=/etc/mediadecay/config.yaml
WorkingDirectory=/var/lib/mediadecay
ExecStart=/usr/bin/mediadecay-web
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

`MEDIACLEANER_CONFIG` tells MediaDecay where the config lives (it otherwise looks
for `config.yaml` in the working directory). If `pip` installed the entry points
somewhere other than `/usr/bin` (e.g. a virtualenv), adjust `ExecStart`
accordingly — or run `python -m mediadecay.web.app`.

### Choosing the runtime user

MediaDecay must run as the account that owns the media it manages, or deletes
and moves will fail with permission errors (the move pre-flight check refuses a
destination it cannot write). Point the service at that user:

- **systemd:** `sudo systemctl edit mediadecay` and add, under `[Service]`,
  `User=youruser` and `Group=yourgroup`.
- **OpenRC:** set `MEDIADECAY_USER` / `MEDIADECAY_GROUP` in
  `/etc/conf.d/mediadecay`.

Also ensure `/var/lib/mediadecay`, `/var/log/mediadecay`, and the config file
are owned/readable by that user.

## Running

Enable and start the service (it runs both the web UI and the scheduled
maintenance):

```bash
# systemd
sudo systemctl enable --now mediadecay
# OpenRC
sudo rc-update add mediadecay default && sudo rc-service mediadecay start
```

Access the web UI at `https://your-host:9393`.

MediaDecay serves with [cheroot](https://cheroot.cherrypy.dev/), a
production-grade pure-Python WSGI server, terminating TLS in-process when
`web.ssl_cert`/`web.ssl_key` are set — no reverse proxy required. It runs as a
single threaded process, which the scheduler and in-process maintenance lock
depend on; do not run multiple instances against the same database.

For local development, `--dev` swaps cheroot for Flask's Werkzeug server
(auto-reloader and debugger). Do not use `--dev` in production:
```bash
mediadecay-web --dev
```

### Manual Maintenance

From the web UI: **Maintenance** → **Preview (Dry Run)** or **Run Now (Live)**.

From the command line (runs as whatever user owns the media/config — use
`sudo -u` to match your runtime user):
```bash
sudo -u MEDIAUSER MEDIACLEANER_CONFIG=/etc/mediadecay/config.yaml mediadecay-maintenance --dry-run
sudo -u MEDIAUSER MEDIACLEANER_CONFIG=/etc/mediadecay/config.yaml mediadecay-maintenance
```

## Web UI Pages

| Page | Purpose |
|------|---------|
| Dashboard | Summary stats, recent actions |
| Browse | Navigate Plex libraries with thumbnails, watch status, manager info, existing rules |
| Wanted | Items monitored in managers but not yet in Plex — create pending rules for upcoming media |
| Rules | List/create/edit/delete rules with triggers |
| Orphans | Async scan for media in Plex not managed by any app |
| Maintenance | Dry-run preview and live execution with space reporting |
| Log | Action history |
| Config | Edit configuration, test connections, test email, change password (passwords masked) |

### Immediate Actions

From the Browse page, clicking "+" on an item opens the rule form with **Delete Now** and **Move Now** buttons. These execute immediately without creating a rule — useful for one-off cleanup.

### Pending Rules

Rules can be created for media that hasn't arrived in Plex yet (e.g., a movie requested in Ombi but not yet available). These "pending rules" store a TVDB/IMDB/TMDB ID and automatically activate when the media appears in Plex during a maintenance run.

### Automatic Cleanup

- **Rule auto-retirement**: Show-scoped rules are automatically deleted after their target is fully removed
- **Orphaned rule detection**: Rules whose targets no longer exist in Plex or any manager are cleaned up during maintenance
- **Empty collection removal**: When `remove_empty_collections` is enabled, Plex collections left with no members (e.g., after all their movies are deleted) are removed during maintenance. Removed collections are listed in the maintenance summary email.
- **Ombi sync**: Requests for media already in Plex are auto-approved (by TVDB/IMDB/TMDB ID match)
