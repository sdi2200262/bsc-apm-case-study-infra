My task is to expand the functionality of the `./eclass-mcp-server` and create a high-performance native C replica.

The single source of truth for all requirements is the `PRD.md` file. I must strictly ensure the final implementation adheres to all functional requirements and acceptance criteria defined within it.

You have the following codebases in your workspace:
1.  `./eclass-mcp-server` (The main Python codebase to be modified)
2.  `./openeclass` (The legacy codebase for research)

**Deliverables:**
The final implementation must include two distinct artifact sets, as specified in the PRD (Section 6):
1.  **Python Implementation:** The updated `eclass-mcp-server` containing the new announcement tools logic and necessary support modules.
2.  **C Replica:** A directory `c-replica/` containing the source code (`.c`, `.h`) and Makefile for the native C microservice inside the `eclass-mcp-server` codebase. This must compile via the specified command and strictly adhere to the technical stack defined in the Spec.

**Crucial Constraints:**
* **Protocol Compliance:** The C Replica must be a drop-in replacement. Its JSON-RPC output must byte-match the definitions in `docs/reference/wire_protocol.md`.
* **Technical Stack:** The C Replica has strict library requirements (`libcurl`, `libxml2`) and any JSON library is strictly forbidden.

**Developer Hint (Research):** After research of the `openeclass/` is completed, you may consolidate all technical findings into a `research-notes.md` file before beginning implementation to use as a primary reference.

Please proceed accordingly.
