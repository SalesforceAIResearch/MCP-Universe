-- name: CreateReleasedBenchmark :one
INSERT INTO "released_benchmark" (owner_id,
                                  name,
                                  tag,
                                  description)
VALUES ($1, $2, $3, $4)
RETURNING *;

-- name: GetReleasedBenchmarkByName :many
SELECT *
FROM "released_benchmark"
WHERE owner_id = $1 AND name = $2;

-- name: GetReleasedBenchmarkByNameAndTag :one
SELECT *
FROM "released_benchmark"
WHERE owner_id = $1 AND name = $2 AND tag = $3
LIMIT 1;

-- name: GetReleasedBenchmarkID :one
SELECT id
FROM "released_benchmark"
WHERE owner_id = $1 AND name = $2 AND tag = $3
LIMIT 1;

-- name: GetReleasedBenchmarkById :one
SELECT *
FROM "released_benchmark"
WHERE id = $1
LIMIT 1;

-- name: DeleteReleasedBenchmark :exec
DELETE
FROM "released_benchmark"
WHERE owner_id = $1 AND name = $2 AND tag = $3;

-- name: ListReleasedBenchmarks :many
SELECT DISTINCT owner_id, name
FROM "released_benchmark"
LIMIT $1
OFFSET $2;