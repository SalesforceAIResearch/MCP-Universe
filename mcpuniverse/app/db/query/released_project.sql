-- name: CreateReleasedProject :one
INSERT INTO "released_project" (owner_id,
                                name,
                                tag,
                                description,
                                configuration)
VALUES ($1, $2, $3, $4, $5)
RETURNING *;

-- name: GetReleasedProjectByName :many
SELECT *
FROM "released_project"
WHERE owner_id = $1 AND name = $2;

-- name: GetReleasedProjectByNameAndTag :one
SELECT *
FROM "released_project"
WHERE owner_id = $1 AND name = $2 AND tag = $3
LIMIT 1;

-- name: GetReleasedProjectById :one
SELECT *
FROM "released_project"
WHERE id = $1
LIMIT 1;

-- name: DeleteReleasedProject :exec
DELETE
FROM "released_project"
WHERE owner_id = $1 AND name = $2 AND tag = $3;

-- name: ListReleasedProjects :many
SELECT DISTINCT name
FROM "released_project"
WHERE owner_id = $1
LIMIT $2
OFFSET $3;

-- name: GetReleasedTags :many
SELECT tag
FROM "released_project"
WHERE owner_id = $1 AND name = $2;