DB_URL=postgresql://root:secret@localhost:5432/mcpuniverse?sslmode=disable

test:
	PYTHONPATH=. pytest tests/

sqlc:
	sqlc generate

redis:
	docker run --name redis -p 6379:6379 -d redis:7.2-alpine

dropredis:
	docker stop redis
	docker container rm redis

postgres:
	docker run --name postgres -p 5432:5432 -e POSTGRES_USER=root -e POSTGRES_PASSWORD=secret -d postgres:15.13-alpine

droppostgres:
	docker stop postgres
	docker container rm postgres

createdb:
	docker exec -it postgres createdb --username=root --owner=root mcpuniverse

dropdb:
	docker exec -it postgres dropdb mcpuniverse

new_migration:
	migrate create -ext sql -dir mcpuniverse/app/db/migration -seq $(name)

migrateup:
	migrate -path mcpuniverse/app/db/migration -database "$(DB_URL)" -verbose up

migratedown:
	migrate -path mcpuniverse/app/db/migration -database "$(DB_URL)" -verbose down

dashboard:
	PYTHONPATH=. uvicorn mcpuniverse.dashboard.app:app

kafka:
	docker run --name kafka -p 9092:9092 -d apache/kafka:4.1.0

dropkafka:
	docker stop kafka
	docker container rm kafka

rabbitmq:
	docker run --name rabbitmq -p 5672:5672 -p 15672:15672 -d rabbitmq:4.1.4-management

droprabbitmq:
	docker stop rabbitmq
	docker container rm rabbitmq

.PHONY: test sqlc redis dropredis postgres droppostgres createdb dropdb new_migration migrateup migratedown dashboard kafka dropkafka rabbitmq droprabbitmq