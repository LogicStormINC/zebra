# CI-only MinIO server and client built from the same releases as the old fixture images.
FROM golang:1.24.2-alpine@sha256:7772cb5322baa875edd74705556d08f0eeca7b9c4b5367754ce3f2f00041ccee AS build
RUN CGO_ENABLED=0 go install github.com/minio/minio@0d7408fc9969caf07de6a8c3a84f9fbb10a6739e \
    && CGO_ENABLED=0 go install github.com/minio/mc@b00526b153a31b36767991a4f5ce2cced435ee8e

FROM alpine:3.22@sha256:2e0b81d60597f449baa56dc25d355367869d2dca4cd57e866f1e2b52af3eb55f
RUN apk add --no-cache ca-certificates curl
COPY --from=build /go/bin/minio /go/bin/mc /usr/local/bin/
ENTRYPOINT ["/usr/local/bin/minio"]
