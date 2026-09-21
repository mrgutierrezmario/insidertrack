# "error getting credentials" when building or pulling

## The symptom

`deploy/start.sh`, `docker compose up --build` or a plain `docker pull` stops
before any container is touched:

```
 > [mcp internal] load metadata for docker.io/library/python:3.12-slim:
target mcp: failed to solve: error getting credentials - err: exit status 255, out: ``
```

It happens on **public** images that need no login, and it happens on the
very first step (fetching image metadata), so nothing has been changed:
whatever was running is still running.

## The cause

Docker asks a *credential helper* for a login before every registry request.
Inside a VS Code dev container, the Dev Containers extension writes one into
`~/.docker/config.json`:

```json
{ "credsStore": "dev-containers-873605e8-…" }
```

That helper is a small shim that forwards the request to VS Code on the Mac,
which answers from the macOS keychain. When VS Code is not on the other end —
a terminal that VS Code did not open, a Claude Code / SSH session into the
container, or VS Code itself in a bad state — the shim exits with status 255
and Docker gives up, even though no credential was needed.

Confirm it in two seconds:

```bash
helper=$(python3 -c 'import json,os;print(json.load(open(os.path.expanduser("~/.docker/config.json"))).get("credsStore",""))')
echo | "docker-credential-$helper" list; echo "exit=$?"     # 255 = broken
```

## The fix

### Right now (one command)

Point Docker at an empty config for this run. Public images pull fine
anonymously:

```bash
mkdir -p ~/.docker-noauth && echo '{}' > ~/.docker-noauth/config.json
DOCKER_CONFIG=~/.docker-noauth deploy/start.sh
```

`DOCKER_CONFIG` works with every Docker command (`docker build`,
`docker compose …`, `docker pull`). It changes nothing on disk in
`~/.docker`, and it does not affect containers that are already running.

### For the whole shell

```bash
export DOCKER_CONFIG=~/.docker-noauth
```

Put it in `~/.bashrc` if you mostly use Docker from terminals VS Code did not
open. You lose only the ability to pull *private* images from that shell —
this project has none.

### Permanently, in `start.sh` (done)

`deploy/start.sh` carries this fallback right after the "is Docker running"
check (the same block lecture-note-app uses):

```bash
# Every image here is public, so a Docker credential helper that cannot run
# (a dev container's helper outside VS Code, a missing keychain) must not
# stop the pulls: fall back to an empty Docker config for this run.
creds=$(python3 -c "import json,os; print(json.load(open(os.path.expanduser('~/.docker/config.json'))).get('credsStore',''))" 2>/dev/null || true)
if [ -n "$creds" ] && ! echo | "docker-credential-$creds" list >/dev/null 2>&1; then
  log "Docker credential helper '$creds' is not working here; pulling anonymously."
  export DOCKER_CONFIG; DOCKER_CONFIG=$(mktemp -d); echo '{}' > "$DOCKER_CONFIG/config.json"
fi
```

So `deploy/start.sh` just works, and prints one line saying it pulled
anonymously. The `DOCKER_CONFIG` route above is still what to use for a
bare `docker pull` or `docker compose` command.

### Making the helper itself work again

Usually a VS Code restart (or *Dev Containers: Rebuild Container* if that is
not enough) reconnects the shim. Only worth doing if you need a private
registry; otherwise the `DOCKER_CONFIG` route is simpler and permanent.

## What it is not

- Not a Docker Hub rate limit or outage (those say `toomanyrequests` or
  `unauthorized`, and the helper check above exits 0).
- Not a problem with the Dockerfile, the image name or the network — the
  request never left the machine.
- Not related to `deploy/.env` or any project secret.
