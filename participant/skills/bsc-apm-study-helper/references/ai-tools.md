# AI tools

Each session uses one of two AI-assisted development frameworks (APM or Spec-kit), running on top of Claude Code. The participant package does not bundle either framework; install the assigned framework's CLI before that session begins. The system requirements (in `system-requirements.md`) cover the underlying tools both frameworks depend on. Claude Code itself is already installed; the participant opened it with the participant-package directory as its working directory, which is how this skill became visible.

## Agentic Project Management (APM)

APM (https://agentic-project-management.dev) ships as an npm package; the CLI is invoked as `apm`.

```
sudo npm install -g agentic-pm
apm --version
```

## GitHub Spec-kit

Spec-kit (https://github.github.io/spec-kit/) runs through `uvx` from a release tag of the upstream repository; the CLI is invoked as `specify`, prefixed by the same `uvx --from` expression on every invocation. `v0.8.3` is the floor verified for this study; any newer release tag listed at https://github.com/github/spec-kit/releases is also acceptable.

```
uvx --from git+https://github.com/github/spec-kit.git@v0.8.3 \
    specify --help
```
