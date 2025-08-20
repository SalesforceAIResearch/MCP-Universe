CREATE TYPE "user_perm" AS ENUM (
  'default',
  'internal',
  'admin'
);

CREATE TABLE "user" (
  "id" bigserial PRIMARY KEY,
  "username" varchar(256) UNIQUE NOT NULL,
  "email" varchar(256) UNIQUE NOT NULL,
  "hashed_password" varchar NOT NULL,
  "permission" user_perm NOT NULL DEFAULT 'default',
  "is_email_verified" bool NOT NULL DEFAULT false,
  "password_changed_at" timestamp NOT NULL DEFAULT (now()),
  "created_at" timestamp NOT NULL DEFAULT (now()),
  "updated_at" timestamp NOT NULL DEFAULT (now())
);

CREATE TABLE "project" (
  "id" bigserial PRIMARY KEY,
  "owner_id" bigserial NOT NULL,
  "name" varchar NOT NULL,
  "description" text,
  "configuration" text,
  "created_at" timestamp NOT NULL DEFAULT (now()),
  "updated_at" timestamp NOT NULL DEFAULT (now())
);

CREATE TABLE "benchmark" (
  "id" bigserial PRIMARY KEY,
  "owner_id" bigserial NOT NULL,
  "name" varchar NOT NULL,
  "description" text,
  "created_at" timestamp NOT NULL DEFAULT (now()),
  "updated_at" timestamp NOT NULL DEFAULT (now())
);

CREATE TABLE "task" (
  "id" bigserial PRIMARY KEY,
  "benchmark_id" bigserial NOT NULL,
  "name" varchar NOT NULL,
  "category" text,
  "question" text,
  "data" text,
  "is_public" bool DEFAULT true,
  "created_at" timestamp NOT NULL DEFAULT (now()),
  "updated_at" timestamp NOT NULL DEFAULT (now())
);

CREATE TABLE "released_project" (
  "id" bigserial PRIMARY KEY,
  "owner_id" bigserial NOT NULL,
  "name" varchar NOT NULL,
  "tag" text NOT NULL,
  "description" text,
  "configuration" text,
  "created_at" timestamp NOT NULL DEFAULT (now())
);

CREATE TABLE "released_benchmark" (
  "id" bigserial PRIMARY KEY,
  "owner_id" bigserial NOT NULL,
  "name" varchar NOT NULL,
  "tag" text NOT NULL,
  "description" text,
  "created_at" timestamp NOT NULL DEFAULT (now())
);

CREATE TABLE "released_task" (
  "id" bigserial PRIMARY KEY,
  "benchmark_id" bigserial NOT NULL,
  "name" varchar NOT NULL,
  "tag" text NOT NULL,
  "category" text,
  "question" text,
  "data" text,
  "is_public" bool DEFAULT true,
  "created_at" timestamp NOT NULL DEFAULT (now())
);

CREATE TABLE "benchmark_job" (
  "id" bigserial PRIMARY KEY,
  "job_id" varchar(36) UNIQUE NOT NULL,
  "owner_id" bigserial NOT NULL,
  "benchmark_id" bigserial NOT NULL,
  "project_id" bigserial NOT NULL,
  "status" text DEFAULT 'pending',
  "progress" int DEFAULT 0,
  "results" text DEFAULT '',
  "score" float DEFAULT 0,
  "celery_id" varchar(36) DEFAULT '',
  "created_at" timestamp NOT NULL DEFAULT (now()),
  "updated_at" timestamp NOT NULL DEFAULT (now())
);

CREATE UNIQUE INDEX ON "project" ("owner_id", "name");

CREATE UNIQUE INDEX ON "benchmark" ("owner_id", "name");

CREATE UNIQUE INDEX ON "task" ("benchmark_id", "name");

CREATE UNIQUE INDEX ON "released_project" ("owner_id", "name", "tag");

CREATE UNIQUE INDEX ON "released_benchmark" ("owner_id", "name", "tag");

CREATE UNIQUE INDEX ON "released_task" ("benchmark_id", "name", "tag");

ALTER TABLE "project" ADD FOREIGN KEY ("owner_id") REFERENCES "user" ("id");

ALTER TABLE "benchmark" ADD FOREIGN KEY ("owner_id") REFERENCES "user" ("id");

ALTER TABLE "task" ADD FOREIGN KEY ("benchmark_id") REFERENCES "benchmark" ("id");

ALTER TABLE "released_project" ADD FOREIGN KEY ("owner_id") REFERENCES "user" ("id");

ALTER TABLE "released_benchmark" ADD FOREIGN KEY ("owner_id") REFERENCES "user" ("id");

ALTER TABLE "released_task" ADD FOREIGN KEY ("benchmark_id") REFERENCES "released_benchmark" ("id");

ALTER TABLE "benchmark_job" ADD FOREIGN KEY ("owner_id") REFERENCES "user" ("id");

ALTER TABLE "benchmark_job" ADD FOREIGN KEY ("benchmark_id") REFERENCES "released_benchmark" ("id");

ALTER TABLE "benchmark_job" ADD FOREIGN KEY ("project_id") REFERENCES "released_project" ("id");
