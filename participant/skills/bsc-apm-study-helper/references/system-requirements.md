# System requirements

## Operating system

A Linux environment is required. Two paths are supported:

- **Native Linux** (Ubuntu 22.04 or 24.04, or an equivalent distribution).
- **Linux virtual machine** on a non-Linux host. The VM must satisfy every other requirement in this section; the work happens entirely inside it. The recommended setup is Multipass (Apple Silicon and Intel Macs supported, one-command launch, free).

Multipass is installed via Homebrew on macOS, so Homebrew (https://brew.sh) must be present first. Once Homebrew is in place, the three commands below install Multipass, launch an Ubuntu LTS VM with enough resources for the task, and drop the participant into a shell inside the VM. All study work happens inside that shell.

```
brew install --cask multipass
multipass launch lts --name task --cpus 4 --memory 8G --disk 20G
multipass shell task
```

If Multipass is unavailable on the host or its image fetch is blocked on the network, UTM (https://mac.getutm.app) is a secondary option: free, open source, GUI-driven, install Ubuntu 24.04 arm64 from the official ISO and select Apple Virtualization for native speed.

**Warning.** Docker Desktop is not a substitute. The mock environment runs Docker Engine *inside* the VM, not on the host.

## System resources

Allow at least 8 GB of RAM (16 GB recommended) and at least 5 GB of free disk after Docker images are loaded. The bulk of the disk usage is the openeclass container image (around 1.6 GB unpacked).

## Tools and libraries

Install these on the Linux environment that runs the case-study work:

- Docker Engine plus Compose v2. Install from the official Docker apt repository per the instructions at https://docs.docker.com/engine/install/ubuntu/.
- GitHub CLI (`gh`), used to download the mock-environment release.
- `git`, `curl`, `tar`, `openssl`, `bash` (3.2 or newer).
- Python 3.10 or newer; `uv` for managing the implementation codebase's dependencies.
- `gcc`, `make`, `valgrind`, `pkg-config`, and the `libcurl` and `libxml2` development headers.

On Debian or Ubuntu derivatives, the Docker convenience script installs Docker Engine and the Compose v2 plugin in one step, then `usermod` adds the user to the `docker` group so subsequent `docker` calls do not need `sudo` (the new group membership takes effect on the next login or after `newgrp docker`):

```
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
```

The line below then installs every remaining tool from the list above. `build-essential` provides `gcc`, `g++`, `make`, and the standard C library development headers; `pkg-config`, `valgrind`, `libcurl4-openssl-dev`, and `libxml2-dev` are named explicitly because they are not part of that meta-package. The trailing `curl` pipe installs `uv` from its official installer.

```
sudo apt-get update
sudo apt-get install -y \
    build-essential pkg-config valgrind \
    libcurl4-openssl-dev libxml2-dev \
    git curl tar openssl gh python3 python3-pip
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Required minimum versions: `gcc` 9.0 (for C11), `libcurl` 7.81.0, `libxml2` 2.9.13. Ubuntu 22.04 (gcc 11.2.0, libcurl 7.81.0, libxml2 2.9.13) and Ubuntu 24.04 (gcc 13.2.0, libcurl 8.5.0, libxml2 2.9.14) both satisfy them. Verify with:

```
gcc --version
pkg-config --modversion libcurl
pkg-config --modversion libxml-2.0
valgrind --version
```

## AI tool

Install the Claude Code CLI by following the official instructions at https://docs.claude.com/en/docs/claude-code. Sign in with the credentials the participant was provided.
