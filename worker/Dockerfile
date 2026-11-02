FROM gcc:14 AS build
WORKDIR /src
COPY main.cpp .
RUN g++ -O2 -std=c++20 -static -o worker main.cpp

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /src/worker /worker
ENTRYPOINT ["/worker"]