#include <atomic>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>
#include <thread>
#include <unistd.h>
#include <vector>

#include <nats/nats.h>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

std::atomic<bool> running{true};

void handle_sigterm(int) { running = false; }

std::string env_or(const char* name, const char* fallback) {
    const char* value = std::getenv(name);
    return value ? value : fallback;
}

struct Tile {
    std::string job;
    int x, y, w, h;
    int width, height, max_iter;
    double cx, cy, scale;
};

Tile parse_tile(const char* data, int len) {
    const json j = json::parse(data, data + len);
    auto i = [&](const char* k) { return j.at(k).get<int>(); };
    auto d = [&](const char* k) { return j.at(k).get<double>(); };
    return Tile{j.at("job").get<std::string>(), i("x"), i("y"), i("w"), i("h"),
                i("width"), i("height"), i("max_iter"), d("cx"), d("cy"), d("scale")};
}

// Renders the tile as packed RGB pixels using smooth iteration coloring.
std::vector<uint8_t> render_tile(const Tile& t) {
    std::vector<uint8_t> rgb(static_cast<size_t>(t.w) * t.h * 3);
    const double step = t.scale / t.width;
    size_t p = 0;
    for (int py = t.y; py < t.y + t.h; ++py) {
        for (int px = t.x; px < t.x + t.w; ++px) {
            const double cr = t.cx + (px - t.width / 2.0) * step;
            const double ci = t.cy + (py - t.height / 2.0) * step;
            double zr = 0, zi = 0;
            int i = 0;
            while (i < t.max_iter && zr * zr + zi * zi <= 256.0) {
                const double tmp = zr * zr - zi * zi + cr;
                zi = 2 * zr * zi + ci;
                zr = tmp;
                ++i;
            }
            if (i == t.max_iter) {
                rgb[p++] = 0; rgb[p++] = 0; rgb[p++] = 0;
                continue;
            }
            const double smooth = i + 1 - std::log2(std::log2(zr * zr + zi * zi) / 2);
            const double v = 0.1 * smooth;
            rgb[p++] = static_cast<uint8_t>(127.5 * (1 + std::cos(v)));
            rgb[p++] = static_cast<uint8_t>(127.5 * (1 + std::cos(v + 2.1)));
            rgb[p++] = static_cast<uint8_t>(127.5 * (1 + std::cos(v + 4.2)));
        }
    }
    return rgb;
}

bool check(natsStatus s, const char* what) {
    if (s == NATS_OK) return true;
    std::cerr << what << " failed: " << natsStatus_GetText(s) << std::endl;
    return false;
}

int main() {
    std::signal(SIGTERM, handle_sigterm);
    std::signal(SIGINT, handle_sigterm);

    char host[256] = "unknown";
    gethostname(host, sizeof(host));
    const std::string nats_url = env_or("NATS_URL", "nats://nats.nats.svc.cluster.local:4222");
    std::cout << "Worker started: " << host << " nats=" << nats_url << std::endl;

    natsOptions* opts = nullptr;
    natsConnection* conn = nullptr;
    jsCtx* js = nullptr;
    natsSubscription* sub = nullptr;

    natsOptions_Create(&opts);
    natsOptions_SetURL(opts, nats_url.c_str());
    natsOptions_SetMaxReconnect(opts, -1);
    while (running && !check(natsConnection_Connect(&conn, opts), "connect"))
        std::this_thread::sleep_for(std::chrono::seconds(2));

    if (conn) natsConnection_JetStream(&js, conn, nullptr);

    // The stream and the durable consumer are created by the controller: bind to them.
    jsSubOptions so;
    jsSubOptions_Init(&so);
    so.Stream = "TILES";
    so.Consumer = "workers";
    while (running && !sub) {
        jsErrCode jerr = static_cast<jsErrCode>(0);
        if (!check(js_PullSubscribe(&sub, js, "render.tiles.>", "workers", nullptr, &so, &jerr), "subscribe"))
            std::this_thread::sleep_for(std::chrono::seconds(2));
    }

    int tiles = 0;
    while (running) {
        natsMsgList list = {};
        const natsStatus s = natsSubscription_Fetch(&list, sub, 1, 2000, nullptr);
        if (s == NATS_TIMEOUT) continue;
        if (!check(s, "fetch")) {
            std::this_thread::sleep_for(std::chrono::seconds(1));
            continue;
        }
        for (int i = 0; i < list.Count; ++i) {
            natsMsg* msg = list.Msgs[i];
            try {
                const Tile t = parse_tile(natsMsg_GetData(msg), natsMsg_GetDataLength(msg));
                const auto start = std::chrono::steady_clock::now();
                const auto rgb = render_tile(t);
                const std::chrono::duration<double> took = std::chrono::steady_clock::now() - start;
                natsMsg_Ack(msg, nullptr);
                std::cout << host << " job=" << t.job << " tile=" << t.x << "," << t.y
                          << " seconds=" << took.count() << " total=" << ++tiles << std::endl;
            } catch (const std::exception& e) {
                std::cerr << host << " bad tile: " << e.what() << std::endl;
                natsMsg_Term(msg, nullptr);
            }
        }
        natsMsgList_Destroy(&list);
    }

    natsSubscription_Destroy(sub);
    jsCtx_Destroy(js);
    natsConnection_Destroy(conn);
    natsOptions_Destroy(opts);
    std::cout << host << " stopped cleanly after " << tiles << " tiles" << std::endl;
}
