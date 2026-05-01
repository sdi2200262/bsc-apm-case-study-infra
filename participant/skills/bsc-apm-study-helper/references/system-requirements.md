# System requirements

## Operating system

A Linux environment is required. Two paths are supported:

- **Native Linux** (Ubuntu 22.04 or 24.04, or an equivalent distribution).
- **Linux virtual machine** on a non-Linux host. The VM must satisfy every other requirement in this section, and the work happens entirely inside it: the participant package, the codebase clones, the workspace, and the mock environment all live on the VM filesystem.

**macOS.** Two Homebrew-installable VM tools are recommended, split by host architecture. Both are free, open source, CLI-driven, and bring up an Ubuntu LTS VM in one command. Homebrew (https://brew.sh) must be present first.

Apple Silicon Macs use Multipass:

```
brew install --cask multipass
multipass launch lts --name task --cpus 4 --memory 8G --disk 20G
multipass shell task
```

Intel Macs use Lima:

```
brew install lima
limactl start --name=task --cpus=4 --memory=8 --disk=20 \
    --tty=false template:ubuntu-24.04
limactl shell task
```

On macOS, if neither Multipass nor Lima works on the host, UTM (https://mac.getutm.app) is a secondary option: free, open source, GUI-driven. Install Ubuntu 24.04 from the official ISO; setup takes longer than the CLI tools because the Ubuntu installer runs interactively.

**Windows.** Install WSL2 with an Ubuntu 24.04 distribution following the official Microsoft instructions at https://learn.microsoft.com/en-us/windows/wsl/install, then follow the native-Linux path inside the WSL2 shell.

**Warning.** Docker Desktop is not a substitute. The mock environment runs Docker Engine *inside* the VM, not on the host.

## System resources

The Linux environment needs at least 4 vCPUs, 8 GB of RAM, and a 20 GB virtual disk; the launch commands above provision these for VM users. After Docker images are loaded (about 1.6 GB for the openeclass container), at least 5 GB of free disk should remain for the workspace, Docker state, and transient files.

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

If `uv --version` reports `command not found` immediately after the install, run `source ~/.local/bin/env` once or open a new login shell so the installer's PATH update takes effect.

Required minimum versions: `gcc` 9.0 (for C11), `libcurl` 7.81.0, `libxml2` 2.9.13. Ubuntu 22.04 (gcc 11.2.0, libcurl 7.81.0, libxml2 2.9.13) and Ubuntu 24.04 (gcc 13.2.0, libcurl 8.5.0, libxml2 2.9.14) both satisfy them. Verify with:

```
gcc --version
pkg-config --modversion libcurl
pkg-config --modversion libxml-2.0
valgrind --version
```

## AI tool

Install the Claude Code CLI by following the official instructions at https://docs.claude.com/en/docs/claude-code. Sign in with the credentials the participant was provided.
