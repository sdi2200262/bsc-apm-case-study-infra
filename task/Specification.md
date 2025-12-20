# Product Requirements Document: eClass MCP Server Enhancement & Native C Replica

This document specifies the goals, functional requirements, and acceptance criteria for expanding the capabilities of the `eclass-mcp-server` and creating a high-performance native C replica of the service.

## 1. Background & Objective

### Background

The `eclass-mcp-server` is a Python-based web crawling service that interfaces with the `openeclass` platform (a legacy PHP codebase) via the Model Context Protocol (MCP). While the current Python implementation handles basic authentication and course retrieval, we require extended functionality for course announcements.

### Objective

To support low-resource deployment environments, we require a dual-deliverable:
1.  **Feature Expansion:** Implement a new `get_course_announcements` tool in the existing Python codebase.
2.  **Native Replication:** Create a standalone **C Microservice** (`server_c`) that replicates the **entire functionality** of the enhanced Python server (Auth, Course Listing, and Announcements). This native server must serve as a functional drop-in replacement, adhering strictly to the same wire protocol.

## 2. Feature Specification (New Tool)

The following tool must be implemented in the Python server and subsequently included in the C Replica.

### Tool: `get_course_announcements`

* **Description:** Fetches announcements for a specific course.
* **Input Schema:**
  ```json
  {
    "type": "object",
    "properties": {
      "course_url": {
        "type": "string",
        "description": "The exact course URL from get_courses output [[https://eclass.example.com/courses/ABC101/](https://eclass.example.com/courses/ABC101/)]"
      },
      "days_back": {
        "type": "integer",
        "description": "Number of days to look back announcements. Must be a positive integer. Default is 30."
      }
    },
    "required": ["course_url"]
  }
  ```

* **Output:** A list of announcements in a standard JSON format. If `days_back` is provided, we return all the announcements until -`days_back` days ago. The tool must return a single `types.TextContent` object.
  * **On Success:** Returns a formatted text block.
    ```text
    Found [N] announcement(s):

    1. [Announcement Title]
        Date: [Date String]
        Content: [Full Announcement Content...]

    2. ...
    ```
  * **On Failure:** Returns a clear error message (e.g., `Error: Not logged in.`).
  * **No Announcements:** If none match the criteria, return: `No announcements found.`.

## 3. C Replica Specifications

The C implementation serves as a high-performance native alternative. It must replicate the **exact behavior** of the final Python server (including existing tools: `login`, `logout`, `get_courses`, `authstatus` AND the new `get_course_announcements`).

### Configuration & Target

The C microservice must be fully configurable via environment variables to support different deployment targets without recompilation. This behavior must strictly mirror the configuration logic of the Python reference implementation.

* **Requirement:** You must implement logic to read the following configuration values from the environment:
  * `ECLASS_URL`: The base URL of the target eClass instance.
  * `ECLASS_USERNAME`: The authentication username.
  * `ECLASS_PASSWORD`: The authentication password.

### Architectural Constraints

To ensure the binary remains lightweight but functional, you must adhere to the following **strict technical stack**:

* **Language:** C (Standard C99 or C11).
* **Networking:** **`libcurl`** is required.
  * You must use the `libcurl` cookie engine (`CURLOPT_COOKIEFILE`) to handle SSO redirects and session persistence.
  * The authentication flow (Login Form -> SSO -> CAS -> Redirect) must match the logic found in the Python `authentication.py`.
* **HTML Parsing:** **`libxml2`** is required.
  * You must use this parser to strip tags and normalize whitespace exactly as `BeautifulSoup` does in the Python reference.
  * To pass validation, your C output must textually match the Python output.
* **JSON & Protocol:**
  * **Strictly Forbidden:** `cJSON`, `Jansson`, or *any* external JSON library.
  * **Requirement:** You must implement the JSON-RPC 2.0 protocol (parsing and serialization) **manually** using standard C string manipulation (`<string.h>`, `<stdio.h>`, `snprintf`, etc.).

### Memory Safety & Stability

To demonstrate native performance without instability, the C Replica must be memory-safe.

* **Zero Leaks:** The application must run cleanly under `valgrind` (Memcheck).
  * **Requirement:** A full session (Login -> List Courses -> Get Announcements -> Exit) must result in **"definitely lost: 0 bytes, indirectly lost: 0 bytes"**.
* **Resource Management:** All `libcurl` handles and `libxml2` contexts objects must be explicitly freed.
* **Verification:** The provided `Makefile` should ideally include a `test-memory` target that runs the server binary with: 
  `valgrind --leak-check=full --show-leak-kinds=all --track-origins=yes --error-exitcode=1 ./server`

### Runtime Behavior

The C microservice acts as a standard CLI application implementing the **Model Context Protocol stdio transport**.

* **Execution:** The binary will be executed directly (e.g., `./server`) without command-line arguments. Configuration is handled solely via Environment Variables.
* **I/O Channels:**
  * **Stdin:** The server must listen for incoming newline-delimited JSON-RPC messages.
  * **Stdout:** The server must emit valid, newline-delimited JSON-RPC responses.
    * **Constraint (Parity):** The JSON-RPC success and error responses (including error codes and message strings) must be **identical** to the Python implementation's output for the same inputs.
  * **Stderr:** All application logs and internal debug information must be printed to `stderr`.
    * **Constraint (Cleanliness):** `stdout` must remain pure JSON-RPC. Any "print debugging" leaked to `stdout` will corrupt the protocol and fail.
* **Lifecycle:** The server must run continuously in a loop, processing requests one by one until the input stream is closed (EOF).

### Protocol Compliance

The C server must operate as a strict drop-in replacement. Your JSON-RPC output (keys, structure, capabilities) must match exactly the specifications defined in **`docs/reference/wire_protocol.md`**. This document is the single source of truth for this microservice.

## 4. Functional & Technical Requirements

### Authentication

All tools must function only for an authenticated session.

  * **Python:** Must leverage the existing `session_state` and fail gracefully if `session_state.logged_in` is `False`.
  * **C Replica:** Must implement a persistent session state equivalent to the Python version, maintaining valid `PHPSESSID` cookies across tool calls.

### Data Source

The logic for retrieving data (announcements, documents) does not currently exist in the `eclass-mcp-server`. The implementation **must be based on research of the `openeclass` legacy codebase** (`./openeclass`) to determine the correct data-fetching procedures.

### Date Filtering Logic

The `days_back` parameter is a strict functional requirement.

  * **Research Requirement:** You must analyze the `openeclass` legacy codebase to determine if the backend supports date filtering. If not, you must implement robust **Client-Side Filtering** to parse the locale-specific date formats and filter entries accurately.

## 5. Acceptance Criteria

All responses from the `get_course_announcements` tool must match the exact formats specified below. Deviations in string content, punctuation, or output structure will result in non-conforming behavior.

### Tool: `get_course_announcements` (Both Implementations)

| WHEN... | THEN... |
| :--- | :--- |
| **User is not logged in** | Must return exact error string: `"Error: Not logged in."` |
| **Invalid `course_url`** | Must return exact error string: `"Error: Could not extract course code."` |
| **No announcements found** | Must return exact success string: `"No announcements found."` |
| **Valid URL + `days_back=X`** | Returns list containing *only* announcements from the last `X` days. Output must follow the format defined in Section 2 (Feature Specification). |
| **Valid URL + No `days_back`** | Returns list containing announcements from the last 30 days (default). Output must follow the format defined in Section 2 (Feature Specification). |

### C Replica System Behavior

| Feature | Criteria |
| :--- | :--- |
| **Compilation** | Execution of `make c-server` inside the `c-replica/` directory completes without errors and produces a binary named `server`. |
| **Protocol** | `initialize`, `tools/list`, and `tools/call` responses match the JSON structure in `wire_protocol.md`. |
| **Authentication** | Successfully performs the full SSO login flow against the configured target environment. |
| **Cookie State** | `authstatus` correctly reflects the login state after a `login` call. |

## 6. Deliverables

### 1. Python Implementation
* **Location:** `eclass-mcp-server/`
* **Artifacts:** The complete updated Python project directory, including any modified or new modules required for the `get_course_announcements` tool.

### 2. C Replica Implementation
* **Location:** A new directory named `c-replica/` inside the `eclass-mcp-server/` codebase.
* **Artifacts:**
  * **Implementation:** Source code files (`.c`) and headers (`.h`).
  * **Makefile:** A valid Makefile with a default target or a specific `c-server` target.
    * **Constraint:** Running `make c-server` must compile the source and produce a binary named `server` in the same directory. It must strictly link against the system libraries (`libcurl`, `libxml2`).