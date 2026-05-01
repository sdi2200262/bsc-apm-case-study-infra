# Mock environment

The mock environment is a self-contained, containerised stack the participant runs locally during each session. It exposes the surfaces the implementation needs to integrate with, pre-loaded with seeded data so every participant runs against identical state.

## Download and install

The mock environment ships from the `sdi2200262/bsc-apm-case-study-env` GitHub repository as two architecture-specific releases, each with a single tarball asset:

- Tag `bsc-apm-case-study-env` ships `bsc-apm-amd64.tar.gz` for x86_64 hosts (most Intel and AMD Linux machines, and the Linux VM on an Intel Mac).
- Tag `bsc-apm-case-study-env-arm64` ships `bsc-apm-arm64.tar.gz` for arm64 hosts (Apple Silicon Macs running a Linux VM, arm64 Linux servers, Raspberry Pi 4/5).

Identify architecture with `uname -m`: `x86_64` means amd64, `aarch64` or `arm64` means arm64. Pick a prefix on disk for the mock environment, separate from the workspace (`<mock>` is the placeholder; `~/.bsc-apm` is a reasonable default). Run *one* of the two download commands below, the one that matches the architecture:

```
mkdir -p <mock> && cd <mock>

# x86_64 hosts:
gh release download bsc-apm-case-study-env \
    -R sdi2200262/bsc-apm-case-study-env \
    -p 'bsc-apm-amd64.tar.gz'

# arm64 hosts:
gh release download bsc-apm-case-study-env-arm64 \
    -R sdi2200262/bsc-apm-case-study-env \
    -p 'bsc-apm-arm64.tar.gz'
```

Then unpack and bring the stack up. `./install` loads the bundled Docker images, generates self-signed TLS certificates into `./certs/`, and writes a pre-configured `.env` alongside. `./scripts/up` brings the three containers up, performs openeclass's first-time install on first run, and applies the test data; this takes a few minutes on a clean host.

```
tar -xzf bsc-apm-*.tar.gz
./install
./scripts/up
```

The stack listens on two URLs once it is ready:

- `http://localhost/` for the openeclass instance.
- `https://localhost:18443/` for the mock authentication service.

Ports 80 and 18443 must be free on the Linux environment. Port 80 is the default HTTP port and is more commonly held by another service than 18443 is; before running `./scripts/up`, check both with `ss -ltn '( sport = :80 or sport = :18443 )'`. If either is held, identify the holder (`sudo lsof -iTCP:<port> -sTCP:LISTEN` or `sudo fuser <port>/tcp`), state a concise plan for freeing it, and ask the participant for permission before stopping anything. Do not propose changing the port mapping; the env package depends on these specific ports.

## Lifecycle commands

Once installed, manage the environment from its prefix:

- `./scripts/up`: bring the stack up. Idempotent.
- `./scripts/down`: stop the stack; named volumes survive.
- `./scripts/status`: probe each service from the mock side and report whether the stack itself is healthy.
- `./scripts/verify-mcp --mcp-root <path>`: consumer-side complement to `status`; probes whether an `eclass-mcp-server` checkout authenticates against the mock with the `.env` and `certs/` it has been given, and prints `wiring ok` on success. Run only at initial setup or after a between-sessions reset, when the checkout is at the pinned baseline (`dbd2d16`) with no tracked-file changes; the script verifies wiring against the baseline auth code only and refuses to run otherwise.
- `./scripts/logs`: tail container logs.
- `./scripts/reset`: drop database state and re-apply the test data.

A reset during a session is unusual and reserved for unusual situations (for instance, recovering after a destructive experiment by the AI); when needed, `./scripts/reset` returns the environment to its initial state.

## MCP server configuration

The `.env` and `certs/` that `./install` wrote are everything the implementation needs to authenticate against the mock. Copy both into the `eclass-mcp-server/` checkout, preserving the `certs/` subdirectory:

```
cp <mock>/.env <workspace>/eclass-mcp-server/.env
cp -r <mock>/certs <workspace>/eclass-mcp-server/certs
```

The `.env` references the certificate by relative path, so no further configuration is required. Verify the wiring with the env package's `verify-mcp` script, which does a single SSO login and logout using the credentials in the just-copied `.env`:

```
<mock>/scripts/verify-mcp --mcp-root <workspace>/eclass-mcp-server
```

It prints `wiring ok` on success and names the missing file or environment variable on failure.

## Uninstall

To remove the mock environment from the machine after the study, stop the stack and drop its volumes (`down -v`), remove the loaded images, and delete the prefix:

```
docker compose -f <mock>/compose.yaml down -v
docker rmi bsc-apm/openeclass:dev bsc-apm/mock-cas:dev
rm -rf <mock>
```
