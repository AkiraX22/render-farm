FROM debian:trixie AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
        g++ cmake make curl ca-certificates nlohmann-json3-dev \
    && rm -rf /var/lib/apt/lists/*

# NATS C client, built as a static library without TLS (cluster-internal traffic).
ARG NATS_C_VERSION=3.12.0
RUN curl -fsSL https://github.com/nats-io/nats.c/archive/refs/tags/v${NATS_C_VERSION}.tar.gz | tar xz -C /tmp \
    && cmake -S /tmp/nats.c-${NATS_C_VERSION} -B /tmp/nats-build -DCMAKE_BUILD_TYPE=Release \
        -DNATS_BUILD_WITH_TLS=OFF -DNATS_BUILD_STREAMING=OFF -DNATS_BUILD_EXAMPLES=OFF \
        -DNATS_BUILD_LIB_SHARED=OFF -DBUILD_TESTING=OFF \
    && cmake --build /tmp/nats-build -j \
    && cmake --install /tmp/nats-build

WORKDIR /src
COPY main.cpp .
RUN g++ -O2 -std=c++20 -static -o worker main.cpp -lnats_static -lpthread

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /src/worker /worker
ENTRYPOINT ["/worker"]
