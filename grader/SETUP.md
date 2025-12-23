# Environment Setup

This document describes how to set up the grading environment for evaluating
participant submissions to the eclass-mcp-server task.

## System Requirements

**Operating System:** Ubuntu 22.04+ or similar Linux distribution

**Required Software:**
- Python 3.10+ with `uv` (recommended) or `pip`
- Docker with docker compose
- Git
- OpenSSL (for SSL certificate generation)

**Required for C Tests:**
- `libcurl4-openssl-dev` (or equivalent libcurl development package)
- `libxml2-dev`
- `valgrind`
- `make` and `gcc`

Install on Ubuntu/Debian:
```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip docker.io docker-compose-plugin git openssl \
    libcurl4-openssl-dev libxml2-dev valgrind build-essential
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

**Expected baseline score (no patch):** 12/48 points
- Python Baseline: 12/12
- Python Feature: 0/12 (not implemented in baseline)
- C Replica: 0/24 (not implemented in baseline)

## Directory Layout

The grader expects this workspace structure:

```
workspace/
  eclass-mcp-server/          # Project being evaluated (git repo)
  openeclass/                 # OpenEclass source (for Docker image)
  bsc-apm-case-study-task/    # This repository
    └── grader/               # This directory
  bsc-apm-case-study-data/     # Data repository (for pipeline)
    └── submissions_sanitized/
        ├── copilot/
        │   └── pipeline_manifest.json
        └── cursor/
            └── pipeline_manifest.json
```

**Note:** The pipeline scripts automatically detect this workspace structure. You can run them from anywhere within the workspace, and they will find the correct paths. See [PIPELINE.md](PIPELINE.md) for details on workspace auto-detection.

## Setup Steps

### 1. Clone Repositories

```bash
git clone https://github.com/sdi2200262/eclass-mcp-server.git
git clone <openeclass-repo> openeclass
```

### 2. Build OpenEclass Docker Image

```bash
cd openeclass
docker build -t openeclass:test .
```

### 3. Start Docker Services

```bash
cd grader
docker compose -f docker-compose.eclass.yaml up -d
```

Wait for services:
```bash
docker exec grader_db_1 mysql -uroot -psecret -e "SELECT 1" && echo "DB ready"
curl -s http://localhost/ > /dev/null && echo "OpenEclass ready"
```

### 4. Configure CAS Authentication

```bash
docker exec grader_db_1 mysql -uroot -psecret eclass -e "
UPDATE auth SET
  auth_settings = 'cas_host=172.17.0.1|cas_port=8082|cas_context=/cas|cas_cachain=',
  auth_default = 2
WHERE auth_id = 7;
"
```

### 5. Create Test User

The `password` field must be `'cas'` for CAS authentication.

```bash
docker exec grader_db_1 mysql -uroot -psecret eclass -e "
INSERT INTO user (username, password, email, status, registered_at, expires_at, lang)
VALUES ('testuser', 'cas', 'testuser@test.com', 5, NOW(), '2099-12-31', 'el')
ON DUPLICATE KEY UPDATE password='cas';
"
```

### 6. Create Test Courses

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

### 7. Seed Test Announcements

```bash
docker exec grader_db_1 mysql -uroot -psecret eclass -e "
INSERT INTO announcement (course_id, title, content, date, visible) VALUES
((SELECT id FROM course WHERE code='TEST101'), 'Welcome', 'Welcome to the course!', NOW() - INTERVAL 3 DAY, 1),
((SELECT id FROM course WHERE code='TEST101'), 'Assignment 1', 'First assignment.', NOW() - INTERVAL 10 DAY, 1),
((SELECT id FROM course WHERE code='TEST101'), 'Old News', 'Old announcement.', NOW() - INTERVAL 45 DAY, 1);
"
```

Note: MATH301 has no announcements for testing "No announcements found" case.

### 8. Generate SSL Certificates

The mock SSO server requires self-signed SSL certificates with proper Subject
Alternative Name (SAN) extension for IP address validation.

**Location:** Certificates must be generated in the `grader/` directory (same level as this SETUP.md file).

```bash
cd grader
openssl req -x509 -newkey rsa:2048 -keyout sso_key.pem -out sso_cert.pem \
    -days 365 -nodes -subj '/CN=172.17.0.1' \
    -addext 'subjectAltName=IP:172.17.0.1'
```

This will create:
- `grader/sso_cert.pem` - SSL certificate
- `grader/sso_key.pem` - Private key

**Important:** The `-addext` option adds a SAN extension, which is required for
modern SSL/TLS validation of IP addresses (RFC 6125). Without it, Python's
`requests` library will reject the certificate with "IP address mismatch".

**Note:** These files are in `.gitignore`. Each grading environment must
generate its own certificates. The mock server (`src/mock_server.py`) expects
these files to be in the `grader/` directory.

### 9. Verify Setup

Run the baseline test to verify everything works:

```bash
./grade --no-patch
```

Expected output: 12/48 points (Python Baseline: 12/12).

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

These are required for compiling the C replica, as specified in the task specification.
