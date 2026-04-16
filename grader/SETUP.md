# Environment Setup

This document describes how to set up the grading environment and workspace structure for evaluating participant submissions.

## System Requirements

**Operating System:** Ubuntu 22.04+ or similar Linux distribution

**Required Software:**
- Python 3.10+ with `uv` (recommended) or `pip`
- Docker with docker compose
- Git
- OpenSSL (for SSL certificate generation)

**Required for C Tests:**
- `gcc` (minimum version 9.0, for C11 support)
- `libcurl4-openssl-dev` (libcurl library minimum version 7.81.0 required)
- `libxml2-dev` (libxml2 library minimum version 2.9.13 required)
- `valgrind`
- `make`

Install on Ubuntu/Debian:
```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip docker.io docker-compose-plugin git openssl \
    libcurl4-openssl-dev libxml2-dev valgrind build-essential
```

**Critical:** The grader expects library versions that meet or exceed the minimum requirements for consistent evaluation. Verify installed versions with:
```bash
gcc --version                        # Must be >= 9.0
pkg-config --modversion libcurl    # Must be >= 7.81.0
pkg-config --modversion libxml-2.0  # Must be >= 2.9.13
```

**Note:** The grader uses black-box testing principles - it will attempt to build with any versions and only fail if the build actually fails. Version mismatches will generate warnings but won't cause automatic failure unless compilation fails.

**Version Compatibility:**
- **Ubuntu 22.04 LTS (Jammy):** Provides libcurl 7.81.0 and libxml2 2.9.13 (meets requirements)
- **Ubuntu 24.04 LTS (Noble):** Provides libcurl 8.5.0 and libxml2 2.9.14 (meets requirements)
- **Debian 12 (Bookworm):** Provides compatible versions

The grader will accept submissions compiled against any version meeting these minimums.

**Optional: Docker for Exact Version Matching**

For participants who want to ensure exact version compatibility with the grading environment, you can use Docker:

```bash
# Use Ubuntu 22.04 LTS container for development
docker run -it --rm -v $(pwd):/workspace ubuntu:22.04 bash
# Inside container:
apt-get update && apt-get install -y build-essential libcurl4-openssl-dev libxml2-dev valgrind
# Verify versions match Ubuntu 22.04 LTS
pkg-config --modversion libcurl    # Should be 7.81.0
pkg-config --modversion libxml-2.0  # Should be 2.9.13
```

Install `uv` (recommended Python package manager):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Baseline Reference

The grader tests against these baseline versions:

| Component | Commit/Version |
|-----------|----------------|
| eclass-mcp-server | `8b4e39c` (main branch) |
| openeclass | `e8b3329` / Docker image `openeclass:test` |

**Expected baseline score (no patch):** 12/100 points
- Python Baseline: 12/12
- Python Features: 0/36 (not implemented in baseline)
- C Replica: 0/52 (not implemented in baseline)

## Workspace Structure

The pipeline requires this workspace structure:

```
workspace/
├── bsc-apm-case-study-task/    # This repository
│   └── grader/
│       └── pipeline/
├── bsc-apm-case-study-data/    # Data repository
│   └── submissions_sanitized/
│       ├── copilot/
│       │   ├── pipeline_manifest.json
│       │   └── dataset.csv
│       └── cursor/
│           ├── pipeline_manifest.json
│           └── dataset.csv
├── eclass-mcp-server/          # eClass MCP Server repository
└── openeclass/                 # Local openeclass repository
```

The pipeline scripts automatically detect this workspace structure. You can run them from anywhere within the workspace, and they will find the correct paths.

## Setup Steps

### 1. Create Workspace Directory

```bash
mkdir -p workspace
cd workspace
```

### 2. Clone Repositories

```bash
# Clone this repository
git clone https://github.com/sdi2200262/bsc-apm-case-study-task

# Clone data repository
git clone https://github.com/sdi2200262/bsc-apm-case-study-data

# Clone baseline repositories
git clone https://github.com/sdi2200262/eclass-mcp-server.git
cd eclass-mcp-server
git checkout 8b4e39c
cd ..

git clone https://github.com/gunet/openeclass
cd openeclass
git checkout e8b3329
cd ..
```

**Note:** The data repository already contains the required directory structure (`submissions_sanitized/copilot/` and `submissions_sanitized/cursor/`). The pipeline scripts will automatically create `pipeline_manifest.json` and `dataset.csv` files when processing submissions.

### 3. Build OpenEclass Docker Image

```bash
cd openeclass
docker build -t openeclass:test .
```

### 4. Start Docker Services

```bash
cd bsc-apm-case-study-task/grader
docker compose -f docker-compose.eclass.yaml up -d
```

Wait for services:
```bash
docker exec grader_db_1 mysql -uroot -psecret -e "SELECT 1"
curl -s http://localhost/ > /dev/null
```

### 5. Configure CAS Authentication

```bash
docker exec grader_db_1 mysql -uroot -psecret eclass -e "
UPDATE auth SET
  auth_settings = 'cas_host=172.17.0.1|cas_port=8082|cas_context=/cas|cas_cachain=',
  auth_default = 2
WHERE auth_id = 7;
"
```

### 6. Create Test User

The `password` field must be `'cas'` for CAS authentication.

```bash
docker exec grader_db_1 mysql -uroot -psecret eclass -e "
INSERT INTO user (username, password, email, status, registered_at, expires_at, lang)
VALUES ('testuser', 'cas', 'testuser@test.com', 5, NOW(), '2099-12-31', 'el')
ON DUPLICATE KEY UPDATE password='cas';
"
```

### 7. Create Test Courses

```bash
docker exec grader_db_1 mysql -uroot -psecret eclass -e "
INSERT INTO course (code, title, visible, created, public_code, lang) VALUES
('TEST101', 'Test Course', 2, NOW(), 'TEST101', 'el'),
('MATH301', 'Mathematics', 2, NOW(), 'MATH301', 'el')
ON DUPLICATE KEY UPDATE title=VALUES(title);

INSERT INTO course_user (course_id, user_id, status, reg_date)
SELECT id, (SELECT id FROM user WHERE username='testuser'), 5, NOW() 
FROM course WHERE code IN ('TEST101', 'MATH301')
ON DUPLICATE KEY UPDATE status=5;
"
```

### 8. Seed Test Announcements

```bash
docker exec grader_db_1 mysql -uroot -psecret eclass -e "
INSERT INTO announcement (course_id, title, content, date, visible) VALUES
((SELECT id FROM course WHERE code='TEST101'), 'Welcome', 'Welcome to the course!', NOW() - INTERVAL 3 DAY, 1),
((SELECT id FROM course WHERE code='TEST101'), 'Assignment 1', 'First assignment.', NOW() - INTERVAL 10 DAY, 1),
((SELECT id FROM course WHERE code='TEST101'), 'Old News', 'Old announcement.', NOW() - INTERVAL 45 DAY, 1);

INSERT INTO admin_announcement (title, body, date, visible, lang) VALUES
('System Maintenance', 'System will be down on Sunday.', NOW() - INTERVAL 1 DAY, 1, 'el'),
('Policy Update', 'New usage policy available.', NOW() - INTERVAL 20 DAY, 1, 'el'),
('Ancient History', 'This is from last year.', NOW() - INTERVAL 60 DAY, 1, 'el');
"
```

Note: MATH301 has no announcements for testing "No announcements found" case.

### 9. Generate SSL Certificates

The mock SSO server requires self-signed SSL certificates with proper Subject Alternative Name (SAN) extension for IP address validation.

**Location:** Certificates must be generated in the `grader/` directory (same level as this SETUP.md file).

```bash
cd bsc-apm-case-study-task/grader
openssl req -x509 -newkey rsa:2048 -keyout sso_key.pem -out sso_cert.pem \
    -days 365 -nodes -subj '/CN=172.17.0.1' \
    -addext 'subjectAltName=IP:172.17.0.1'
```

This will create:
- `grader/sso_cert.pem` - SSL certificate
- `grader/sso_key.pem` - Private key

**Important:** The `-addext` option adds a SAN extension, which is required for modern SSL/TLS validation of IP addresses (RFC 6125). Without it, Python's `requests` library will reject the certificate with "IP address mismatch".

**Note:** These files are in `.gitignore`. Each grading environment must generate its own certificates. 

### 10. Verify Setup

Run the baseline test to verify everything works:

```bash
cd bsc-apm-case-study-task/grader
./grade --no-patch
```

Expected output: 12/100 points (Python Baseline: 12/12).

## Troubleshooting

### OpenEclass not accessible
```bash
docker start grader_db_1 grader_eclass_1
```

### CAS not detected
```bash
docker exec grader_db_1 mysql -uroot -psecret eclass \
  -e "SELECT * FROM auth WHERE auth_id = 7\G"
```

### Session errors
Ensure test user has `password='cas'`:
```bash
docker exec grader_db_1 mysql -uroot -psecret eclass \
  -e "UPDATE user SET password='cas' WHERE username='testuser'"
```

### No announcements in test
Verify data:
```bash
docker exec grader_db_1 mysql -uroot -psecret eclass \
  -e "SELECT course_id, title, date FROM announcement"
```

### C build fails with "missing libxml2-dev" or "missing libcurl-dev"

Install the development packages:
```bash
sudo apt-get install libcurl4-openssl-dev libxml2-dev
```

**Important:** Verify the library versions meet the minimum requirements:
```bash
pkg-config --modversion libcurl    # Must be >= 7.81.0
pkg-config --modversion libxml-2.0  # Must be >= 2.9.13
```

These are required for compiling the C replica, as specified in the task specification. The grader accepts any version meeting these minimums. Common distributions:
- Ubuntu 22.04 LTS: libcurl 7.81.0, libxml2 2.9.13
- Ubuntu 24.04 LTS: libcurl 8.5.0, libxml2 2.9.14

### Pipeline workspace detection fails

Ensure all required directories exist at the same level:
- `bsc-apm-case-study-task/`
- `bsc-apm-case-study-data/`
- `eclass-mcp-server/`
- `openeclass/`

Run pipeline scripts from within the workspace directory structure.
