# Grader setup

The grader runs against a separately-installed testing environment
(the `bsc-apm-case-study-env` package) and grades a participant's
patch by applying it to the pinned `eclass-mcp-server` baseline and
running the rubric phases against the live environment.

## Grading machine prerequisites

**Operating system.** Linux (native, WSL2, or a Linux VM on macOS).

**Required software.**

- Python 3.10 or newer with `uv` on `PATH`.
- Docker Engine plus Compose v2 (consumed by the testing environment).
- Git.

**Required for C tests.**

- `gcc` (>= 9.0 for C11 support).
- `libcurl4-openssl-dev` (libcurl >= 7.81.0).
- `libxml2-dev` (libxml2 >= 2.9.13).
- `valgrind`.
- `make`.

Ubuntu install line:

```bash
sudo apt-get install -y python3 git docker.io docker-compose-plugin \
    build-essential libcurl4-openssl-dev libxml2-dev valgrind
```

Install `uv` if not already present:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Testing environment install

The `bsc-apm-case-study-env` package is published as a GitHub
release. Download the tarball matching the grading machine's
architecture, extract into a prefix of your choice (recommended:
`~/.bsc-apm/`), and run the install plus up scripts:

```bash
ARCH=$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')
mkdir -p ~/.bsc-apm
curl -L https://github.com/sdi2200262/bsc-apm-case-study-env/releases/download/bsc-apm-case-study-env/bsc-apm-${ARCH}.tar.gz \
    | tar -xz -C ~/.bsc-apm
cd ~/.bsc-apm
./install
./scripts/up
```

See the env package's
[INSTALL.md](https://github.com/sdi2200262/bsc-apm-case-study-env/blob/main/docs/INSTALL.md)
for the full lifecycle reference, including reset and tear-down
commands.

## Baseline reference

| Component | Pinned at |
|---|---|
| `eclass-mcp-server` | commit `8b4e39c` on the `main` branch |
| Testing environment | `bsc-apm-case-study-env` release tag `bsc-apm-case-study-env` |

Expected baseline score (no patch applied): 12/100. A grading
machine that produces a different baseline against the pinned
references is misconfigured.
