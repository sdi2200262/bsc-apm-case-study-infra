<?php
// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) BSc APM Case Study 2025-2026

declare(strict_types=1);

/**
 * Apply the testing-environment seed against an installed openeclass
 * instance. Reads ``seed.json`` next to this file and writes the rows,
 * filesystem entries, and search-index queue entries an openeclass
 * UI-driven create flow normally produces, so the mock state matches a
 * fresh install with the seeded entities created through the platform
 * rather than through bare table inserts.
 *
 * Runs inside the eclass container after the openeclass first-time
 * install has completed. A sentinel row in ``config`` keeps the seeder
 * idempotent across re-invocations.
 */

const WEBROOT = '/var/www/html';
const SEED_JSON = __DIR__ . '/seed.json';
const SENTINEL_KEY = 'bsc_apm_seed_applied';
const DEFAULT_DEPARTMENT_ID = 2;
const ADMIN_UID = 1;

// The openeclass bootstrap runs at file scope rather than from inside a
// function: include/init.php transitively loads config/config.php,
// which assigns $mysqlServer, $mysqlUser, $mysqlPassword, $mysqlMainDb
// at top level. Wrapping the require_once in a function would scope
// those names to the function and leave Database::get()'s `global`
// declarations resolving to NULL, which makes PDO fall back to a
// non-existent unix socket.
chdir(WEBROOT);

// openeclass's init.php inspects request superglobals during session
// and routing setup; populate the keys it expects so the CLI
// invocation does not fault.
$_SERVER['REQUEST_URI'] = '/seed';
$_SERVER['REQUEST_METHOD'] = 'CLI';
$_SERVER['HTTP_HOST'] = 'localhost';
$_SERVER['SERVER_NAME'] = 'localhost';

require_once WEBROOT . '/include/init.php';
require_once WEBROOT . '/modules/create_course/functions.php';
require_once WEBROOT . '/include/lib/course.class.php';
require_once WEBROOT . '/modules/search/classes/SearchEngineFactory.php';
require_once WEBROOT . '/modules/search/classes/ConstantsUtil.php';
require_once WEBROOT . '/modules/search/lucene/indexer.class.php';

main();

/**
 * Top-level orchestration. Walks the seed in dependency order: auth
 * row, users, courses, per-course enrollments, course announcements,
 * admin announcements, search index drain.
 *
 * @return void
 */
function main(): void {
    if (seed_already_applied()) {
        echo "seed already applied\n";
        return;
    }

    $seed = load_seed_json(SEED_JSON);

    // Attribute audit log entries to the platform admin created
    // during openeclass first-time install.
    $_SESSION['uid'] = ADMIN_UID;

    configure_cas_auth($seed['cas']);

    $user_ids = [];
    foreach ($seed['users'] as $user) {
        $user_ids[$user['username']] = create_seed_user($user);
    }

    $course_ids = [];
    foreach ($seed['courses'] as $course) {
        $course_ids[$course['code']] = create_seed_course($course);
    }

    foreach ($seed['courses'] as $course) {
        foreach ($course['enrolled_users'] ?? [] as $username) {
            enroll_user_in_course(
                $user_ids[$username],
                $course_ids[$course['code']]
            );
        }
    }

    foreach ($seed['courses'] as $course) {
        $cid = $course_ids[$course['code']];
        foreach ($course['announcements'] ?? [] as $ann) {
            create_course_announcement($cid, $ann);
        }
    }

    foreach ($seed['admin_announcements'] ?? [] as $ann) {
        create_admin_announcement($ann);
    }

    flush_search_index();
    mark_seed_applied();

    echo "seed applied\n";
}

/**
 * Read and decode the JSON seed alongside this script.
 *
 * @param string $path Absolute path to the JSON file.
 * @return array Decoded structure mirroring seed.yaml.
 * @throws RuntimeException When the file is missing or unreadable.
 */
function load_seed_json(string $path): array {
    if (!is_file($path)) {
        throw new RuntimeException("seed input not found: $path");
    }
    $raw = file_get_contents($path);
    if ($raw === false) {
        throw new RuntimeException("could not read seed input: $path");
    }
    $data = json_decode($raw, true);
    if (!is_array($data)) {
        throw new RuntimeException("seed input is not a JSON object: $path");
    }
    return $data;
}

/**
 * Test whether the sentinel config row exists with a non-empty value.
 *
 * @return bool true when a previous run completed against this database.
 */
function seed_already_applied(): bool {
    $row = Database::get()->querySingle(
        "SELECT `value` FROM config WHERE `key` = ?s",
        SENTINEL_KEY
    );
    return $row !== false && $row !== null && !empty($row->value);
}

/**
 * Write the sentinel config row with the current timestamp.
 *
 * @return void
 */
function mark_seed_applied(): void {
    Database::get()->query(
        "INSERT INTO config (`key`, `value`) VALUES (?s, ?s) " .
        "ON DUPLICATE KEY UPDATE `value` = VALUES(`value`)",
        SENTINEL_KEY,
        date('c')
    );
}

/**
 * Activate the CAS auth row with the mock CAS connection details.
 *
 * @param array $cas Decoded ``cas`` section: host, port, context, title.
 * @return void
 */
function configure_cas_auth(array $cas): void {
    $settings = sprintf(
        'cas_host=%s|cas_port=%d|cas_context=%s|cas_cachain=',
        $cas['host'],
        (int)$cas['port'],
        $cas['context'] ?? ''
    );
    Database::get()->query(
        "UPDATE auth SET auth_settings = ?s, auth_title = ?s, " .
        "auth_default = 2 WHERE auth_id = 7",
        $settings,
        $cas['title']
    );
}

/**
 * Insert the seed test user, plus the personal_calendar_settings row
 * that openeclass's auth flow normally writes alongside it. Idempotent
 * at the row level via username lookup.
 *
 * @param array $user Decoded ``user`` section.
 * @return int The new or existing user.id.
 */
function create_seed_user(array $user): int {
    $existing = Database::get()->querySingle(
        "SELECT id FROM user WHERE username = ?s",
        $user['username']
    );
    if ($existing) {
        return (int)$existing->id;
    }

    $result = Database::get()->query(
        "INSERT INTO user SET surname = ?s, givenname = ?s, " .
        "password = 'cas', username = ?s, email = ?s, status = ?d, " .
        "lang = ?s, am = ?s, verified_mail = ?d, " .
        "registered_at = NOW(), " .
        "expires_at = DATE_ADD(NOW(), INTERVAL ?d SECOND), whitelist = ''",
        $user['surname'] ?? '',
        $user['givenname'] ?? '',
        $user['username'],
        $user['email'] ?? '',
        $user['status'] ?? USER_STUDENT,
        $user['lang'] ?? 'el',
        $user['studentid'] ?? '',
        EMAIL_VERIFIED,
        (int)get_config('account_duration')
    );
    $user_id = (int)$result->lastInsertID;

    Database::get()->query(
        "INSERT IGNORE INTO personal_calendar_settings(user_id) VALUES (?d)",
        $user_id
    );

    return $user_id;
}

/**
 * Create one course end to end with a fixed code from the seed:
 * filesystem directories, course row, course-department link, search
 * index queue entry (via Course::refresh), course_module rows,
 * default forum category, per-course URL shim, and audit log row.
 *
 * Bypasses ``create_course()`` because that helper auto-generates the
 * course code via ``new_code()``; the seed needs deterministic codes.
 *
 * @param array $course Decoded course entry.
 * @return int The new course.id.
 * @throws RuntimeException When directory creation fails.
 */
function create_seed_course(array $course): int {
    $code = $course['code'];

    if (!create_course_dirs($code)) {
        throw new RuntimeException("could not create course directories for $code");
    }

    $result = Database::get()->query(
        "INSERT INTO course SET code = ?s, lang = ?s, title = ?s, " .
        "visible = ?d, public_code = ?s, " .
        "doc_quota = ?d, video_quota = ?d, group_quota = ?d, dropbox_quota = ?d, " .
        "view_type = 'units', glossary_expand = 0, glossary_index = 1, " .
        "is_collaborative = 0, view_units = 1, " .
        "keywords = '', description = '', prof_names = '', course_image = '', " .
        "course_license = 0, password = '', flipped_flag = 0, " .
        "start_date = NOW(), created = NOW()",
        $code,
        $course['lang'] ?? 'el',
        $course['title'],
        $course['visible'] ?? COURSE_OPEN,
        $course['public_code'] ?? $code,
        (int)get_config('doc_quota') * 1024 * 1024,
        (int)get_config('video_quota') * 1024 * 1024,
        (int)get_config('group_quota') * 1024 * 1024,
        (int)get_config('dropbox_quota') * 1024 * 1024
    );
    $course_id = (int)$result->lastInsertID;

    $courseObj = new Course();
    $courseObj->refresh($course_id, [DEFAULT_DEPARTMENT_ID]);

    create_modules($course_id);

    Database::get()->query(
        "INSERT INTO forum_category SET cat_title = ?s, course_id = ?d",
        'General',
        $course_id
    );

    course_index($code);

    Log::record(0, 0, LOG_CREATE_COURSE, [
        'id' => $course_id,
        'code' => $code,
        'title' => $course['title'],
        'language' => $course['lang'] ?? 'el',
        'visible' => $course['visible'] ?? COURSE_OPEN,
    ]);

    return $course_id;
}

/**
 * Enroll the seed user in a course as a student and write the audit
 * log row openeclass's enrollment flow produces.
 *
 * @param int $user_id   user.id of the seed user.
 * @param int $course_id course.id of the target course.
 * @return void
 */
function enroll_user_in_course(int $user_id, int $course_id): void {
    Database::get()->query(
        "INSERT IGNORE INTO course_user " .
        "(course_id, user_id, status, reg_date, document_timestamp) " .
        "VALUES (?d, ?d, ?d, NOW(), NOW())",
        $course_id,
        $user_id,
        USER_STUDENT
    );
    Log::record(
        $course_id,
        MODULE_ID_USERS,
        LOG_INSERT,
        ['uid' => $user_id, 'right' => USER_STUDENT]
    );
}

/**
 * Insert one course-scoped announcement, queue it for the search
 * index, and write the audit log row. Date is anchored relative to
 * apply time so seed-time freshness windows hold across resets.
 *
 * @param int   $course_id Target course.
 * @param array $ann       Announcement entry: days_ago, title, body.
 * @return void
 */
function create_course_announcement(int $course_id, array $ann): void {
    $result = Database::get()->query(
        "INSERT INTO announcement SET course_id = ?d, title = ?s, " .
        "content = ?s, `date` = DATE_SUB(NOW(), INTERVAL ?d DAY), " .
        "`order` = 0, visible = 1",
        $course_id,
        $ann['title'],
        $ann['body'],
        (int)$ann['days_ago']
    );
    $id = (int)$result->lastInsertID;

    SearchEngineFactory::create()->indexResource(
        ConstantsUtil::REQUEST_STORE,
        ConstantsUtil::RESOURCE_ANNOUNCEMENT,
        $id
    );

    Log::record($course_id, MODULE_ID_ANNOUNCE, LOG_INSERT, [
        'id' => $id,
        'email' => false,
        'title' => $ann['title'],
        'content' => mb_substr(strip_tags($ann['body']), 0, 50),
    ]);
}

/**
 * Insert one system-wide announcement at the next ordering position.
 * No search index entry: openeclass's admin announcement flow does
 * not index admin announcements at this version.
 *
 * @param array $ann Admin announcement entry: days_ago, title, body, lang.
 * @return void
 */
function create_admin_announcement(array $ann): void {
    $next_order = 1 + (int)Database::get()->querySingle(
        "SELECT COALESCE(MAX(`order`), 0) AS m FROM admin_announcement"
    )->m;

    Database::get()->query(
        "INSERT INTO admin_announcement SET title = ?s, body = ?s, " .
        "lang = ?s, `date` = DATE_SUB(NOW(), INTERVAL ?d DAY), " .
        "`order` = ?d, visible = 1",
        $ann['title'],
        $ann['body'],
        $ann['lang'] ?? 'el',
        (int)$ann['days_ago'],
        $next_order
    );
}

/**
 * Drain the async indexing queue so the on-disk Lucene segments
 * reflect the rows the announcement and course steps just queued.
 * Without this drain the queue rows exist but the index files are
 * not built until a page load triggers idxasync.php, leaving search
 * paths returning empty on first probe against the seeded mock.
 *
 * @return void
 */
function flush_search_index(): void {
    $indexer = new Indexer();
    $indexer->queueAsyncProcess();
}
