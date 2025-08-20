-- name: CreateProject :one
INSERT INTO "project" (owner_id,
                       name,
                       description,
                       configuration)
VALUES ($1, $2, $3, $4)
RETURNING *;

-- name: GetProjectByName :one
SELECT *
FROM "project"
WHERE owner_id = $1 AND name = $2
LIMIT 1;

-- name: GetProjectById :one
SELECT *
FROM "project"
WHERE id = $1
LIMIT 1;

-- name: GetProjectID :one
SELECT id
FROM "project"
WHERE owner_id = $1 AND name = $2
LIMIT 1;

-- name: UpdateProject :one
UPDATE "project"
SET description   = COALESCE(sqlc.narg(description), description),
    configuration = COALESCE(sqlc.narg(configuration), configuration),
    updated_at    = COALESCE(sqlc.narg(updated_at), updated_at)
WHERE owner_id = sqlc.arg(owner_id) AND name = sqlc.arg(name)
RETURNING *;

-- name: DeleteProject :exec
DELETE
FROM "project"
WHERE owner_id = $1 AND name = $2;

-- name: ListProjects :many
SELECT name
FROM "project"
WHERE owner_id = $1
LIMIT $2
OFFSET $3;