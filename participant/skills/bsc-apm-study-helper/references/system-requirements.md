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

The case-study work needs a container runtime (Docker Engine with Compose v2), a C build chain (`gcc`, `make`, `valgrind`, `pkg-config`, plus the `libcurl` and `libxml2` development headers), two scripting runtimes (Python 3.10 or newer with `uv`, and Node.js with `npm`), and a handful of command-line utilities (`git`, `curl`, `tar`, `openssl`, `bash` 3.2 or newer, and `gh`). Install Docker first via the official convenience script:

```
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
```

The new `docker` group membership takes effect on the next login or after `newgrp docker`. Within Claude Code, prefer wrapping docker calls in `sg docker -c '<cmd>'` instead: `sg` runs the command in a subshell with the docker group active for that single invocation and returns control to the parent shell, so the conversation's working shell is preserved. Use `newgrp docker` (or log out and back in) for the participant's own terminal sessions. Install everything else with `apt` and the official `uv` installer:

```
sudo apt-get update
sudo apt-get install -y \
    build-essential pkg-config valgrind \
    libcurl4-openssl-dev libxml2-dev \
    git curl tar openssl gh python3 python3-pip npm
curl -LsSf https://astral.sh/uv/install.sh | sh
```

If `uv --version` reports `command not found` immediately after the install, run `source ~/.local/bin/env` once or open a new login shell so the installer's PATH update takes effect. The C minimums are `gcc` 9.0 (for C11), `libcurl` 7.81.0, and `libxml2` 2.9.13; Ubuntu 22.04 and 24.04 both satisfy them. Verify the toolchain:

```
gcc --version
pkg-config --modversion libcurl
pkg-config --modversion libxml-2.0
valgrind --version
python3 --version
node --version
npm --version
uv --version
```

