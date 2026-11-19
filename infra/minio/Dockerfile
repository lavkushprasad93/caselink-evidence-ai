ARG MINIO_VERSION=RELEASE.2025-10-15T17-29-55Z

FROM golang:1.24.8-alpine3.22 AS builder
ARG MINIO_VERSION
RUN apk add --no-cache ca-certificates git
WORKDIR /src
RUN git clone --depth 1 --branch "${MINIO_VERSION}" https://github.com/minio/minio.git .
RUN mkdir -p /out && CGO_ENABLED=0 go build -tags kqueue -trimpath --ldflags "$(go run buildscripts/gen-ldflags.go)" -o /out/minio

FROM alpine:3.22.1
RUN apk add --no-cache ca-certificates
COPY --from=builder /out/minio /usr/bin/minio
ENTRYPOINT ["/usr/bin/minio"]
