# Local development image built from the unmodified official MinIO source release.
FROM golang:1.24.8-alpine3.22 AS builder
ENV CGO_ENABLED=0 GOTOOLCHAIN=local GOMAXPROCS=4
WORKDIR /src
COPY .cache/minio-source.tar.gz /tmp/minio-source.tar.gz
RUN echo "be6d0bd3696c3a13a35f02d3a0280b64319c67918b4501c5c3d87f96d000085c  /tmp/minio-source.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/minio-source.tar.gz --strip-components=1 -C /src
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    go build -p 4 -trimpath \
    -ldflags="-s -w -X github.com/minio/minio/cmd.Version=2025-10-15T17:29:55Z -X github.com/minio/minio/cmd.ReleaseTag=RELEASE.2025-10-15T17-29-55Z" \
    -o /out/minio .

FROM alpine:3.22
RUN apk add --no-cache ca-certificates curl
COPY --from=builder /out/minio /usr/local/bin/minio
COPY --from=builder /src/LICENSE /licenses/minio-LICENSE
LABEL org.opencontainers.image.source="https://github.com/minio/minio" \
      org.opencontainers.image.version="RELEASE.2025-10-15T17-29-55Z" \
      org.opencontainers.image.licenses="AGPL-3.0-only" \
      org.opencontainers.image.description="Local learning environment; official source compiled locally"
VOLUME ["/data"]
EXPOSE 9000 9001
ENTRYPOINT ["/usr/local/bin/minio"]
