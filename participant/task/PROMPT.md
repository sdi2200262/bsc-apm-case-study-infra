My task is to expand the functionality of `./eclass-mcp-server`
and add a native C replica of the service at
`./eclass-mcp-server/c-replica/`. The PRD at `./PRD.md` is the
single source of truth; my implementation must satisfy every
requirement and acceptance criterion it defines.

The workspace contains:

1. `./eclass-mcp-server`: the Python MCP server I am extending,
   pinned to a specific commit.
2. `./openeclass`: the legacy PHP platform the MCP server
   integrates against, pinned to a specific release.

A local mock of that same `openeclass` release is running on
this machine, paired with a mock single sign-on endpoint at
`https://localhost:18443/` whose flow matches what the existing
`eclass-mcp-server` is configured to integrate with. This is the
instance my MCP server connects to during development. The
credentials and TLS material the server needs at startup are
already in place inside `./eclass-mcp-server/`: a `.env` file at
the package root and a `certs/sso_cert.pem` cert it references.

I want all the requirements of the PRD validated against the data
this running mock exposes.
