# Workspace

The participant package's `task/` directory holds `PRD.md` (the requirements the participant implements against), `PROMPT.md` (the message the participant gives the AI to open the session), and a throwaway `README.txt` with the clone commands for the two repositories at their pinned commits. The *workspace* is the directory in which the participant opens Claude Code; it is the AI's working directory for the session, and it must end up with this exact layout:

```
<workspace>/
|-- PRD.md
|-- PROMPT.md
|-- eclass-mcp-server/      # implementation codebase
`-- openeclass/             # legacy PHP codebase (read-only reference)
```

The participant can either use the package's `task/` directory as the workspace, or copy `PRD.md` and `PROMPT.md` into a fresh directory of their choice and clone the two repositories alongside them there. Either way, follow the clone commands in `README.txt` (or the equivalent commands below), then delete `README.txt`; it has no role beyond initial setup.

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
