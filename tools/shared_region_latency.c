/* Shared-region callback timing, adapted from Steve's 7ba8b8d diagnostics.
 * No GPU objects or rendering are submitted. The syscall can invoke the
 * installed kext's normal private-cache patch handlers in this process.
 * This measures the whole syscall, including the native implementation;
 * dyld has already started this process, so the first sample is not cold boot.
 */
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

enum { MaxSamples = 256 };
static double seconds(void) {
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now)) { perror("clock_gettime"); exit(1); }
    return (double)now.tv_sec + (double)now.tv_nsec / 1000000000.0;
}
static int compare(const void *left, const void *right) {
    const double a = *(const double *)left, b = *(const double *)right;
    return (a > b) - (a < b);
}
/* Nearest rank, with one-based ranks and a zero-based array. */
static double percentile(const double *values, unsigned count, unsigned percent) {
    unsigned rank = (count * percent + 99) / 100;
    return values[rank ? rank - 1 : 0];
}
int main(int argc, char **argv) {
    unsigned count = 16;
    if (argc > 2) { fprintf(stderr, "Usage: %s [samples:1..256]\n", argv[0]); return 64; }
    if (argc == 2) {
        char *end = NULL;
        errno = 0;
        const unsigned long parsed = strtoul(argv[1], &end, 10);
        if (errno || end == argv[1] || *end || parsed < 1 || parsed > MaxSamples) {
            fprintf(stderr, "Sample count must be 1..256\n"); return 64;
        }
        count = (unsigned)parsed;
    }
    double samples[MaxSamples];
    for (unsigned i = 0; i < count; ++i) {
        uint64_t base = 0;
        const double start = seconds();
        const int result = (int)syscall(SYS_shared_region_check_np, &base);
        samples[i] = (seconds() - start) * 1000.0;
        if (result || !base) {
            fprintf(stderr, "shared_region_check_np failed: result=%d errno=%d\n", result, errno);
            return 1;
        }
    }
    const double first = samples[0];
    qsort(samples, count, sizeof(samples[0]), compare);
    printf("{\"samples\":%u,\"first_ms\":%.6f,\"min_ms\":%.6f,\"p50_ms\":%.6f,"
           "\"p95_ms\":%.6f,\"p99_ms\":%.6f,\"max_ms\":%.6f,"
           "\"GPU_work_submitted\":false,\"scope\":\"Native shared-region syscall plus installed hooks in an already started process; not cold boot or GPU throughput\"}\n",
           count, first, samples[0], percentile(samples,count,50), percentile(samples,count,95),
           percentile(samples,count,99), samples[count-1]);
    return 0;
}
