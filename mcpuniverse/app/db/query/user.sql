-- name: CreateUser :one
INSERT INTO "user" (username,
                    email,
                    hashed_password,
                    permission)
VALUES ($1, $2, $3, $4)
RETURNING *;

-- name: GetUserByName :one
SELECT *
FROM "user"
WHERE username = $1
LIMIT 1;

-- name: GetUserByEmail :one
SELECT *
FROM "user"
WHERE email = $1
LIMIT 1;

-- name: GetUserById :one
SELECT *
FROM "user"
WHERE id = $1
LIMIT 1;

-- name: UpdateUser :one
UPDATE "user"
SET hashed_password     = COALESCE(sqlc.narg(hashed_password), hashed_password),
    password_changed_at = COALESCE(sqlc.narg(password_changed_at), password_changed_at),
    email               = COALESCE(sqlc.narg(email), email),
    is_email_verified   = COALESCE(sqlc.narg(is_email_verified), is_email_verified)
WHERE email = sqlc.arg(email)
RETURNING *;