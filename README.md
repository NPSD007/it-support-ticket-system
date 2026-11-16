# IT Support Ticket System

A containerized IT help-desk application built with **Python Flask** and **SQLite** and packaged with **Podman**. Users can create support tickets, search them by keyword, filter them by priority or status, move them through a status workflow and close them. All data is stored in a SQLite file on a **persistent Podman volume**, so tickets survive container removal and re-creation.

> University capstone project: containerization with Podman (Containerfile, named volume, custom network, registry push/pull).

---

## Features

| Feature | Description |
|---|---|
| Create ticket | Auto-generated ID (`TKT-0001`, `TKT-0002`, ...), category, description, priority (Low / Medium / High / Critical), status **Open** by default, UTC timestamp |
| List tickets | Table view, newest first, with live counters per status |
| Search | Keyword search across **category + description** (multi-word searches must match every word) |
| **Filter (assigned variation)** | **Filter by Priority or Status** with dropdowns on the main page. Pick one, or combine both |
| Change status | Open -> In Progress -> Resolved, one step at a time |
| Close ticket | Sets the status to **Closed** from any other status |
| Reopen ticket | Sends a **Resolved** or **Closed** ticket back to **Open** |
| Persistence | SQLite database at `/data/tickets.db`, stored on a Podman named volume |
| Self-contained | Plain HTML/CSS with no JavaScript libraries or CDN assets. The only external request is the optional Inter web font, which loads in the background and falls back to system fonts when offline |

## Project Structure

```text
it-support-ticket-system/
├── app.py                # Flask application (routes + SQLite access)
├── templates/
│   ├── base.html         # Layout, navigation and all CSS
│   ├── index.html        # Ticket table, search bar, priority/status filters
│   └── create.html       # New-ticket form
├── Containerfile         # Podman/OCI build instructions (python:3.11-slim)
├── requirements.txt      # Python dependencies
├── README.md             # This file
└── .gitignore
```

## Application Routes

| Method | Route | Description |
|---|---|---|
| GET | `/` | List all tickets |
| GET, POST | `/create` | Show the new-ticket form / save a ticket |
| GET | `/search?q=<keyword>` | Search category + description |
| GET | `/filter?priority=<p>&status=<s>` | Filter by priority and/or status |
| POST | `/update_status/<id>` | Advance status: Open -> In Progress -> Resolved |
| POST | `/close/<id>` | Set status to Closed |
| POST | `/reopen/<id>` | Send a Resolved or Closed ticket back to Open |

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_PATH` | `/data/tickets.db` | Location of the SQLite file (also set with `ENV` in the Containerfile) |
| `SECRET_KEY` | random at startup | Signs the session cookie used for flash messages (optional) |

If the database file or its directory does not exist, the app creates them and the `tickets` table on first start.

## Prerequisites

- **Podman 4.0 or newer** (`podman --version`)
- macOS / Windows only: start the Podman VM once with `podman machine init` and `podman machine start`
- Host port **8080** must be free

---

## Podman Commands

Run every command from the project directory (the folder that contains the `Containerfile`).

### 1. Build the image

```bash
# 1. Build the image
podman build -t it-support-tickets:v1.0 .
```

- `podman build` reads the `Containerfile` in the current directory (`.`) and builds an OCI image from it.
- `-t it-support-tickets:v1.0` names (tags) the image `it-support-tickets` with version `v1.0`.
- Check the result with `podman images`.

### 2. Create a persistent volume

```bash
# 2. Create a persistent volume
podman volume create tickets-data
```

- Creates a named volume managed by Podman. It lives outside any container, so the SQLite database in it survives `podman rm`.
- List volumes with `podman volume ls`; see where it is stored with `podman volume inspect tickets-data`.

### 3. Create a custom network

```bash
# 3. Create a custom network
podman network create tickets-net
```

- Creates an isolated bridge network. Containers on a user-defined network can reach each other **by container name** through Podman's built-in DNS.
- List networks with `podman network ls`; details with `podman network inspect tickets-net`.

### 4. Run the container

```bash
# 4. Run the container
podman run -d \
  --name ticket-system \
  --network tickets-net \
  -p 8080:5000 \
  -v tickets-data:/data \
  it-support-tickets:v1.0
```

| Option | Meaning |
|---|---|
| `-d` | Run in the background (detached) |
| `--name ticket-system` | Give the container a fixed name used by the other commands |
| `--network tickets-net` | Attach it to the custom network from step 3 |
| `-p 8080:5000` | Publish container port **5000** on host port **8080** |
| `-v tickets-data:/data` | Mount the named volume at `/data`, where `tickets.db` is stored |

Open **http://localhost:8080** in your browser. Confirm it is running with `podman ps`.

Optional: add `-e SECRET_KEY="a-long-random-string"` to keep flash-message cookies valid across restarts.

### 5. Inspect the container

```bash
# 5. Inspect the container
podman inspect ticket-system
```

Prints the full JSON configuration and state. Things worth finding in the output:

| JSON section | What it shows |
|---|---|
| `State.Status` | `running` |
| `Mounts` | volume `tickets-data` mounted at `/data` |
| `NetworkSettings.Networks` | attached to `tickets-net`, with its IP address |
| `HostConfig.PortBindings` / `NetworkSettings.Ports` | container port `5000/tcp` mapped to host port `8080` |
| `Config.Env` | includes `DATABASE_PATH=/data/tickets.db` |

Handy single-value queries:

```bash
podman inspect --format '{{.State.Status}}' ticket-system
podman inspect --format '{{json .Mounts}}' ticket-system
podman inspect --format '{{(index .NetworkSettings.Networks "tickets-net").IPAddress}}' ticket-system
```

### 6. View logs

```bash
# 6. View logs
podman logs ticket-system
```

Shows everything the application printed, including each HTTP request. Expected start-up output:

```text
[ticket-system] Using database: /data/tickets.db
 * Serving Flask app 'app'
 * Debug mode: off
WARNING: This is a development server. Do not use it in a production deployment. Use a production WSGI server instead.
 * Running on all addresses (0.0.0.0)
 * Running on http://127.0.0.1:5000
 * Running on http://10.89.0.2:5000
Press CTRL+C to quit
```

Useful variations: `podman logs -f ticket-system` (follow live, stop with `Ctrl+C`) and `podman logs --tail 20 ticket-system` (last 20 lines).

### 7. Stop and remove

```bash
# 7. Stop and remove
podman stop ticket-system
podman rm ticket-system
```

- `podman stop` shuts the container down gracefully (the app handles SIGTERM, so it stops immediately).
- `podman rm` deletes the stopped container. **The volume and its tickets are kept.**
- `podman rm -f ticket-system` stops and removes the container in a single step.

### 8. Push to registry (replace USERNAME)

First log in to the registry (Docker Hub asks for your username and password or access token):

```bash
podman login docker.io
```

Then tag and push:

```bash
# 8. Push to registry (replace USERNAME)
podman tag it-support-tickets:v1.0 docker.io/USERNAME/it-support-tickets:v1.0
podman push docker.io/USERNAME/it-support-tickets:v1.0
```

- `podman tag` adds a second name to the local image that includes the registry and your account. Replace `USERNAME` with your own Docker Hub user name.
- `podman push` uploads the image to that repository.

To use **Quay.io** instead, log in with `podman login quay.io` and replace `docker.io` with `quay.io` in both commands. Quay usually creates new repositories as private, so switch the repository to public in the web UI if others need to pull it anonymously.

### 9. Pull from registry

```bash
# 9. Pull from registry
podman pull docker.io/USERNAME/it-support-tickets:v1.0
```

Downloads the image from the registry, for example on another machine. Start it exactly like step 4, using the registry name:

```bash
podman run -d \
  --name ticket-system \
  --network tickets-net \
  -p 8080:5000 \
  -v tickets-data:/data \
  docker.io/USERNAME/it-support-tickets:v1.0
```

To prove the pull really works, delete the local copies first with `podman rmi it-support-tickets:v1.0 docker.io/USERNAME/it-support-tickets:v1.0`.

---

## Verify Data Persistence

1. Start the container (step 4) and create a ticket at http://localhost:8080/create.
2. Destroy the container:
   ```bash
   podman stop ticket-system
   podman rm ticket-system
   ```
3. Start a brand-new container with the same volume (repeat step 4).
4. Reload http://localhost:8080. The ticket is still there because `/data/tickets.db` lives on the `tickets-data` volume.

Inspect the database file directly:

```bash
podman exec ticket-system ls -l /data
podman exec ticket-system python -c "import sqlite3; print(sqlite3.connect('/data/tickets.db').execute('SELECT COUNT(*) FROM tickets').fetchone()[0])"
```

## Test the Custom Network (optional)

Start a throw-away container on `tickets-net` and reach the app by its container name. This reuses the Python base image that is already cached from the build:

```bash
podman run --rm --network tickets-net docker.io/library/python:3.11-slim \
  python -c "import urllib.request as u; print(u.urlopen('http://ticket-system:5000/').status)"
```

Expected output: `200`.

## Run Locally Without Containers (optional)

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
DATABASE_PATH=./tickets.db python app.py     # PowerShell: $env:DATABASE_PATH=".\tickets.db"; python app.py
```

The app then listens on http://localhost:5000.

## Troubleshooting

| Problem | Fix |
|---|---|
| `the container name "ticket-system" is already in use` | Remove the old container: `podman rm -f ticket-system` |
| `address already in use` on port 8080 | Use another host port, e.g. `-p 9090:5000`, and open http://localhost:9090 |
| `network not found` | Create the network first (step 3) and check it with `podman network ls` |
| `Cannot connect to Podman` (macOS / Windows) | Start the VM: `podman machine start` |
| Build asks you to select an image (short-name prompt) | Use fully qualified image names such as `docker.io/library/python:3.11-slim` (already done in the `Containerfile`) |
| `unauthorized` on `podman push` | Log in first: `podman login docker.io` (or `quay.io`) |
| Tickets disappear after restart | Make sure every `podman run` includes `-v tickets-data:/data` |
| `unable to open database file` with a bind mount | Create the folder first (`mkdir -p data`); on SELinux systems add `:Z` (`-v ./data:/data:Z`), or keep using the named volume |

## Clean Up

```bash
podman rm -f ticket-system          # remove the container (if present)
podman network rm tickets-net       # remove the custom network
podman volume rm tickets-data       # DELETES all ticket data permanently
podman rmi it-support-tickets:v1.0  # remove the local image
```

## Notes and Limitations

- The container runs Flask's built-in development server, which is fine for a capstone demo or small internal use. For heavier traffic put the app behind a production WSGI server such as Gunicorn.
- There is no login or user management. Run it on a trusted network.
- With rootless Podman, `root` inside the container maps to your unprivileged host user, so the container has no real root access on the host.
- SQLite supports one writer at a time and is meant for a single container using the volume.
- Timestamps are stored and shown in UTC.
