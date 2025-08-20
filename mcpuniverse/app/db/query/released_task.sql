-- name: CreateReleasedTask :one
INSERT INTO "released_task" (benchmark_id,
                             name,
                             tag,
                             category,
                             question,
                             data,
                             is_public)
VALUES ($1, $2, $3, $4, $5, $6, $7)
RETURNING *;

-- name: GetReleasedTaskByName :many
SELECT *
FROM "released_task"
WHERE benchmark_id = $1 AND name = $2;

-- name: GetReleasedTaskByNameAndTag :one
SELECT *
FROM "released_task"
WHERE benchmark_id = $1 AND name = $2 AND tag = $3
LIMIT 1;

-- name: GetReleasedTaskById :one
SELECT *
FROM "released_task"
WHERE id = $1
LIMIT 1;

-- name: GetReleasedTaskNames :many
SELECT name
FROM "released_task"
WHERE benchmark_id = $1;

-- name: GetReleasedTaskConfigs :many
SELECT data
FROM "released_task"
WHERE benchmark_id = $1;

-- name: DeleteReleasedTask :exec
DELETE
FROM "released_task"
WHERE id = $1;