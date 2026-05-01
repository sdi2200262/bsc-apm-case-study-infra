# AI tools

Each session uses one of two AI-assisted development frameworks (APM or Spec-kit), running on top of Claude Code. The participant package does not bundle either framework; install the assigned framework's CLI before that session begins. The system requirements (in `system-requirements.md`) cover the underlying tools both frameworks depend on. Claude Code itself is already installed (this skill loads from inside it).

## Agentic Project Management (APM)

APM (https://agentic-project-management.dev) ships as an npm package; the CLI is invoked as `apm`.

```
sudo npm install -g agentic-pm
apm --version
```

## GitHub Spec-kit

Spec-kit (https://github.github.io/spec-kit/) runs through `uvx` from a pinned tag of the upstream repository; the CLI is invoked as `specify`, prefixed by the same `uvx --from` expression on every invocation.

```
uvx --from git+https://github.com/github/spec-kit.git@v0.8.3 \
    specify --help
```
