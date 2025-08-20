-- name: CreateTask :one
INSERT INTO "task" (benchmark_id,
                    name,
                    category,
                    question,
                    data,
                    is_public)
VALUES ($1, $2, $3, $4, $5, $6)
RETURNING *;

-- name: GetTaskByName :one
SELECT *
FROM "task"
WHERE benchmark_id = $1 AND name = $2
LIMIT 1;

-- name: GetTaskID :one
SELECT id
FROM "task"
WHERE benchmark_id = $1 AND name = $2
LIMIT 1;

-- name: GetTaskById :one
SELECT *
FROM "task"
WHERE id = $1
LIMIT 1;

-- name: GetTaskNamesInBenchmark :many
SELECT name
FROM "task"
WHERE benchmark_id = $1;

-- name: UpdateTask :one
UPDATE "task"
SET category   = COALESCE(sqlc.narg(category), category),
    question   = COALESCE(sqlc.narg(question), question),
    data       = COALESCE(sqlc.narg(data), data),
    is_public  = COALESCE(sqlc.narg(is_public), is_public),
    updated_at = COALESCE(sqlc.narg(updated_at), updated_at)
WHERE benchmark_id = sqlc.arg(benchmark_id) AND name = sqlc.arg(name)
RETURNING *;

-- name: DeleteTask :exec
DELETE
FROM "task"
WHERE benchmark_id = $1 AND name = $2;