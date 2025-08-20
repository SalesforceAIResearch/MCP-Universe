-- name: CreateBenchmark :one
INSERT INTO "benchmark" (owner_id,
                         name,
                         description)
VALUES ($1, $2, $3)
RETURNING *;

-- name: GetBenchmarkByName :one
SELECT *
FROM "benchmark"
WHERE owner_id = $1 AND name = $2
LIMIT 1;

-- name: GetBenchmarkID :one
SELECT id
FROM "benchmark"
WHERE owner_id = $1 AND name = $2
LIMIT 1;

-- name: GetBenchmarkById :one
SELECT *
FROM "benchmark"
WHERE id = $1
LIMIT 1;

-- name: UpdateBenchmark :one
UPDATE "benchmark"
SET description   = COALESCE(sqlc.narg(description), description),
    updated_at    = COALESCE(sqlc.narg(updated_at), updated_at)
WHERE owner_id = sqlc.arg(owner_id) AND name = sqlc.arg(name)
RETURNING *;

-- name: DeleteBenchmark :exec
DELETE
FROM "benchmark"
WHERE owner_id = $1 AND name = $2;