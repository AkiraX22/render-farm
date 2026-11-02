#include <atomic>
#include <chrono>
#include <complex>
#include <csignal>
#include <iostream>
#include <thread>
#include <unistd.h>

std::atomic<bool> running{true};

void handle_sigterm(int) { running = false; }

int compute_tile(int size, int max_iter) {
    int inside = 0;
    for (int y = 0; y < size; ++y) {
        for (int x = 0; x < size; ++x) {
            const std::complex<double> c(-2.0 + 3.0 * x / size, -1.5 + 3.0 * y / size);
            std::complex<double> z = 0;
            int i = 0;
            while (i < max_iter && std::norm(z) <= 4.0) {
                z = z * z + c;
                ++i;
            }
            if (i == max_iter) ++inside;
        }
    }
    return inside;
}

int main() {
    std::signal(SIGTERM, handle_sigterm);
    std::signal(SIGINT, handle_sigterm);

    char host[256] = "unknown";
    gethostname(host, sizeof(host));
    std::cout << "Worker started: " << host << std::endl;

    int tile = 0;
    while (running) {
        const int result = compute_tile(512, 1000);
        std::cout << host << " tile=" << ++tile << " inside=" << result << std::endl;
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }

    std::cout << host << " stopped cleanly" << std::endl;
}