-- name: CreateBenchmarkJob :one
INSERT INTO "benchmark_job" (job_id,
                             owner_id,
                             benchmark_id,
                             project_id)
VALUES ($1, $2, $3, $4)
RETURNING *;

-- name: GetBenchmarkJobs :many
SELECT *
FROM "benchmark_job"
WHERE owner_id = $1;

-- name: GetBenchmarkJobById :one
SELECT *
FROM "benchmark_job"
WHERE job_id = $1
LIMIT 1;

-- name: GetNumJobs :one
SELECT COUNT(*)
FROM "benchmark_job"
WHERE owner_id = $1 AND status = $2 AND updated_at > $3;

-- name: GetTotalNumJobs :one
SELECT COUNT(*)
FROM "benchmark_job"
WHERE status = $1 AND updated_at > $2;

-- name: UpdateBenchmarkJob :one
UPDATE "benchmark_job"
SET status     = COALESCE(sqlc.narg(status), status),
    progress   = COALESCE(sqlc.narg(progress), progress),
    results    = COALESCE(sqlc.narg(results), results),
    score      = COALESCE(sqlc.narg(score), score),
    celery_id  = COALESCE(sqlc.narg(celery_id), celery_id),
    updated_at = COALESCE(sqlc.narg(updated_at), updated_at)
WHERE job_id = sqlc.arg(job_id)
RETURNING *;