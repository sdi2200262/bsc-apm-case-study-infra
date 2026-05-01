# Workspace

The participant package's `task/` directory holds `PRD.md` (the requirements the participant implements against), `PROMPT.md` (the message the participant gives the AI to open the session), and a throwaway `README.txt` with the clone commands for the two repositories at their pinned commits. The *workspace* is the directory in which the participant opens Claude Code on the Linux environment (native or inside the VM); it is the AI's working directory for the session, and it must end up with this exact layout:

```
<workspace>/
|-- PRD.md
|-- PROMPT.md
|-- eclass-mcp-server/      # implementation codebase
`-- openeclass/             # legacy PHP codebase (read-only reference)
```

Create the workspace as a fresh directory of the participant's choice on the Linux filesystem. `~/workspace/` is the default the helper proposes; before creating it, announce the default in plain terms and offer the participant the chance to specify a different path. Copy `PRD.md` and `PROMPT.md` into the chosen directory from the participant package's `task/` directory, and clone the two repositories alongside them following the next section. `README.txt` carries the same clone commands for convenience and has no further role.

## Cloning the codebases

Clone `eclass-mcp-server` and check out the pinned commit `dbd2d16`. This commit is the patch baseline: every diff submitted is computed against it.

```
cd <workspace>
git clone https://github.com/sdi2200262/eclass-mcp-server.git
cd eclass-mcp-server
git checkout dbd2d16
uv sync --dev --all-extras
cd ..
```

Clone `openeclass` at its pinned commit `e8b3329`. The AI treats this codebase as a read-only reference, and the participant keeps it that way.

```
cd <workspace>
git clone https://github.com/gunet/openeclass.git
cd openeclass
git checkout e8b3329
cd ..
```
