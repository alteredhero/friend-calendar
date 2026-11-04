-- Golden fixture: a Friend Calendar v1.1 database (schema version 1) with representative data.
-- Regenerate NEVER: it exists to prove newer versions can still open real v1.1 data.
BEGIN TRANSACTION;
CREATE TABLE events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                owner      TEXT    NOT NULL,
                day        TEXT    NOT NULL,            -- YYYY-MM-DD
                title      TEXT    NOT NULL DEFAULT '',
                tag        TEXT    NOT NULL,
                start_min  INTEGER NOT NULL DEFAULT 540, -- minutes since midnight
                end_min    INTEGER NOT NULL DEFAULT 600,
                note       TEXT    NOT NULL DEFAULT '',
                created_at TEXT    NOT NULL
            , detail TEXT NOT NULL DEFAULT '', series_id TEXT);
INSERT INTO "events" VALUES(1,'Alex','2026-11-05','Movie night','movie',1200,1320,'bring snacks','2026-10-30T18:00:00','Dune',NULL);
INSERT INTO "events" VALUES(2,'Blake','2026-11-05','','game',1260,1380,'','2026-10-30T18:05:00','Catan',NULL);
INSERT INTO "events" VALUES(3,'Casey','2026-11-12','Away','out of town',0,1440,'visiting family','2026-10-31T09:00:00','',NULL);
INSERT INTO "events" VALUES(4,'Alex','2026-11-02','Work','schedule',540,1020,'','2026-10-01T08:00:00','','series-work');
INSERT INTO "events" VALUES(5,'Alex','2026-11-09','Work','schedule',540,1020,'','2026-10-01T08:00:00','','series-work');
INSERT INTO "events" VALUES(6,'Alex','2026-11-16','Work','schedule',600,1080,'late start','2026-10-01T08:00:00','','series-work');
INSERT INTO "events" VALUES(7,'Blake','2026-11-03','','busy',780,840,'','2026-10-02T08:00:00','','series-gym');
INSERT INTO "events" VALUES(8,'Blake','2026-11-10','','busy',780,840,'','2026-10-02T08:00:00','','series-gym');
INSERT INTO "events" VALUES(9,'Dana','2026-11-20','Dentist','busy',900,960,'owner has no users row','2026-11-01T12:00:00','',NULL);
CREATE TABLE users (
                name     TEXT PRIMARY KEY,
                color    TEXT NOT NULL DEFAULT '#6c8cff',
                timezone TEXT NOT NULL DEFAULT 'America/Los_Angeles'
            );
INSERT INTO "users" VALUES('Alex','#6c8cff','America/Los_Angeles');
INSERT INTO "users" VALUES('Blake','#4bd07b','America/New_York');
INSERT INTO "users" VALUES('Casey','#ff9f43','America/Phoenix');
CREATE INDEX idx_events_day ON events(day);
CREATE INDEX idx_events_series ON events(series_id);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('events',9);
COMMIT;
PRAGMA user_version = 1;
