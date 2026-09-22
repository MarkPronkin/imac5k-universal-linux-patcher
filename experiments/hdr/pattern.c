#define _GNU_SOURCE
// Native Wayland HDR test pattern. No kernel or display configuration changes.
#include <wayland-client.h>
#include "xdg-shell-client.h"
#include "color-management-client.h"
#include <errno.h>
#include <math.h>
#include <poll.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

static struct wl_display *display;
static struct wl_compositor *compositor;
static struct wl_shm *shm;
static struct wl_surface *surface;
static struct xdg_wm_base *shell;
static struct xdg_surface *xdg_surface;
static struct wp_color_manager_v1 *cm;
static struct wp_color_management_surface_v1 *cm_surface;
static struct wp_image_description_v1 *description;
static bool has_10bit, ready, running = true, sdr, failed, blur_probe;
static int width = 700, height = 280;
static double peak = 507.5;

static void die(const char *message) {
    fprintf(stderr, "%s: %s\n", message, strerror(errno));
    exit(1);
}

static double pq(double nits) {
    double p = pow(nits / 10000., 2610. / 16384.);
    return pow((3424. / 4096. + (2413. / 128.) * p) / (1. + (2392. / 128.) * p), 2523. / 32.);
}

struct buffer {
    void *pixels;
    size_t bytes;
};

static void release_buffer(void *data, struct wl_buffer *buffer) {
    struct buffer *b = data;
    wl_buffer_destroy(buffer);
    munmap(b->pixels, b->bytes);
    free(b);
}
static const struct wl_buffer_listener buffer_listener = {.release = release_buffer};

static void draw(void) {
    if (!ready)
        return;
    const unsigned max = has_10bit ? 1023 : 255;
    const unsigned shift = has_10bit ? 10 : 8;
    const double levels[] = {0, 50.75, 101.5, 203, 203 + (peak - 203) / 3, 203 + 2 * (peak - 203) / 3, peak};
    struct buffer *b = calloc(1, sizeof(*b));
    if (!b)
        die("allocate buffer");
    b->bytes = (size_t)width * height * 4;
    int fd = memfd_create("imac-hdr-pattern", MFD_CLOEXEC);
    if (fd < 0 || ftruncate(fd, b->bytes))
        die("allocate shared memory");
    b->pixels = mmap(NULL, b->bytes, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (b->pixels == MAP_FAILED)
        die("map shared memory");
    uint32_t *pixels = b->pixels;
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            double nits = y < height * 3 / 4 ? levels[x * 7 / width] : peak * x / (width - 1);
            // SDR comparison saturates at its reference white; PQ retains highlights.
            double signal = sdr ? pow(fmin(nits / 203., 1.), 1. / 2.2) : pq(nits);
            uint32_t value = (uint32_t)lround(signal * max);
            pixels[y * width + x] = blur_probe ? 0 : value | (value << shift) | (value << (shift * 2));
        }
    }
    struct wl_shm_pool *pool = wl_shm_create_pool(shm, fd, b->bytes);
    struct wl_buffer *buffer = wl_shm_pool_create_buffer(pool, 0, width, height, width * 4,
        blur_probe ? WL_SHM_FORMAT_ARGB8888 : has_10bit ? WL_SHM_FORMAT_XRGB2101010 : WL_SHM_FORMAT_XRGB8888);
    wl_shm_pool_destroy(pool);
    close(fd);
    wl_buffer_add_listener(buffer, &buffer_listener, b);
    wl_surface_attach(surface, buffer, 0, 0);
    wl_surface_damage_buffer(surface, 0, 0, width, height);
    wl_surface_commit(surface);
}

static void configure_surface(void *data, struct xdg_surface *object, uint32_t serial) {
    (void)data;
    xdg_surface_ack_configure(object, serial);
    draw();
}
static const struct xdg_surface_listener surface_listener = {.configure = configure_surface};

static void configure_toplevel(void *data, struct xdg_toplevel *object, int32_t w, int32_t h, struct wl_array *states) {
    (void)data; (void)object; (void)states;
    if (w > 0 && h > 0) {
        width = w;
        height = h;
    }
    if (width < 2 || height < 2 || width > 16384 || height > 16384) {
        fprintf(stderr, "Unexpected window dimensions\n");
        exit(1);
    }
}
static void close_toplevel(void *data, struct xdg_toplevel *object) {
    (void)data; (void)object; running = false;
}
static const struct xdg_toplevel_listener toplevel_listener = {.configure = configure_toplevel, .close = close_toplevel};
static void ping(void *data, struct xdg_wm_base *object, uint32_t serial) {
    (void)data; xdg_wm_base_pong(object, serial);
}
static const struct xdg_wm_base_listener shell_listener = {.ping = ping};
static void shm_format(void *data, struct wl_shm *object, uint32_t format) {
    (void)data; (void)object;
    if (format == WL_SHM_FORMAT_XRGB2101010)
        has_10bit = true;
}
static const struct wl_shm_listener shm_listener = {.format = shm_format};

static void cm_event(void *data, struct wp_color_manager_v1 *object, uint32_t value) {
    (void)data; (void)object; (void)value;
}
static void cm_done(void *data, struct wp_color_manager_v1 *object) {
    (void)data; (void)object;
}
static const struct wp_color_manager_v1_listener cm_listener = {
    .supported_intent = cm_event, .supported_feature = cm_event, .supported_tf_named = cm_event,
    .supported_primaries_named = cm_event, .done = cm_done,
};

static void global(void *data, struct wl_registry *registry, uint32_t name, const char *interface, uint32_t version) {
    (void)data;
    if (!strcmp(interface, "wl_compositor") && version >= 4)
        compositor = wl_registry_bind(registry, name, &wl_compositor_interface, 4);
    else if (!strcmp(interface, "wl_shm")) {
        shm = wl_registry_bind(registry, name, &wl_shm_interface, 1);
        wl_shm_add_listener(shm, &shm_listener, NULL);
    } else if (!strcmp(interface, "xdg_wm_base")) {
        shell = wl_registry_bind(registry, name, &xdg_wm_base_interface, 1);
        xdg_wm_base_add_listener(shell, &shell_listener, NULL);
    } else if (!strcmp(interface, "wp_color_manager_v1")) {
        cm = wl_registry_bind(registry, name, &wp_color_manager_v1_interface, 1);
        wp_color_manager_v1_add_listener(cm, &cm_listener, NULL);
    }
}
static void global_remove(void *data, struct wl_registry *registry, uint32_t name) {
    (void)data; (void)registry; (void)name;
}
static const struct wl_registry_listener registry_listener = {.global = global, .global_remove = global_remove};

static void description_failed(void *data, struct wp_image_description_v1 *object, uint32_t cause, const char *message) {
    (void)data; (void)object;
    fprintf(stderr, "Color description rejected (%u): %s\n", cause, message);
    failed = true;
    running = false;
}
static void description_ready(void *data, struct wp_image_description_v1 *object, uint32_t identity) {
    (void)data; (void)identity;
    wp_color_management_surface_v1_set_image_description(cm_surface, object, WP_COLOR_MANAGER_V1_RENDER_INTENT_PERCEPTUAL);
    ready = true;
    wl_surface_commit(surface); // Initial empty commit requests xdg configuration.
}
static const struct wp_image_description_v1_listener description_listener = {.failed = description_failed, .ready = description_ready};

int main(int argc, char **argv) {
    bool fullscreen = false;
    int seconds = 30;
    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--sdr")) sdr = true;
        else if (!strcmp(argv[i], "--fullscreen")) fullscreen = true;
        else if (!strcmp(argv[i], "--blur-probe")) blur_probe = sdr = true;
        else if (!strcmp(argv[i], "--peak") && i + 1 < argc) {
            char *end;
            peak = strtod(argv[++i], &end);
            if (*end || !isfinite(peak) || peak < 203 || peak > 10000) {
                fprintf(stderr, "Peak must be 203..10000 source nits\n");
                return 2;
            }
        }
        else if (!strcmp(argv[i], "--seconds") && i + 1 < argc) {
            char *end;
            long value = strtol(argv[++i], &end, 10);
            if (*end || value < 1 || value > 3600) {
                fprintf(stderr, "Seconds must be 1..3600\n");
                return 2;
            }
            seconds = value;
        } else {
            fprintf(stderr, "Usage: pattern [--sdr] [--fullscreen] [--blur-probe] [--peak 203..10000] [--seconds 1..3600]\n");
            return 2;
        }
    }
    display = wl_display_connect(NULL);
    if (!display) die("connect Wayland");
    struct wl_registry *registry = wl_display_get_registry(display);
    wl_registry_add_listener(registry, &registry_listener, NULL);
    if (wl_display_roundtrip(display) < 0 || wl_display_roundtrip(display) < 0)
        die("read Wayland globals");
    if (!compositor || !shm || !shell || !cm) {
        fprintf(stderr, "Compositor needs xdg-shell and color-management-v1\n");
        return 1;
    }
    surface = wl_compositor_create_surface(compositor);
    cm_surface = wp_color_manager_v1_get_surface(cm, surface);
    xdg_surface = xdg_wm_base_get_xdg_surface(shell, surface);
    xdg_surface_add_listener(xdg_surface, &surface_listener, NULL);
    struct xdg_toplevel *toplevel = xdg_surface_get_toplevel(xdg_surface);
    xdg_toplevel_add_listener(toplevel, &toplevel_listener, NULL);
    xdg_toplevel_set_title(toplevel, sdr ? "iMac EDR: SDR comparison" : "iMac EDR: PQ highlights");
    xdg_toplevel_set_app_id(toplevel, blur_probe ? "imac-edr-blur-probe" : "imac-edr-pattern");
    if (fullscreen) xdg_toplevel_set_fullscreen(toplevel, NULL);
    struct wp_image_description_creator_params_v1 *creator = wp_color_manager_v1_create_parametric_creator(cm);
    wp_image_description_creator_params_v1_set_primaries_named(creator, WP_COLOR_MANAGER_V1_PRIMARIES_BT2020);
    wp_image_description_creator_params_v1_set_tf_named(creator,
        sdr ? WP_COLOR_MANAGER_V1_TRANSFER_FUNCTION_GAMMA22 : WP_COLOR_MANAGER_V1_TRANSFER_FUNCTION_ST2084_PQ);
    wp_image_description_creator_params_v1_set_luminances(creator, 0, sdr ? 203 : 10000, 203);
    if (!sdr) {
        wp_image_description_creator_params_v1_set_max_cll(creator, (uint32_t)ceil(peak));
        wp_image_description_creator_params_v1_set_max_fall(creator, (uint32_t)ceil(peak));
    }
    description = wp_image_description_creator_params_v1_create(creator);
    wp_image_description_v1_add_listener(description, &description_listener, NULL);
    printf("%s, %u-bit buffer. Reference white: 203, source peak: %g nits.\n",
           blur_probe ? "Transparent blur probe" : sdr ? "SDR (clipped at 203)" : "PQ", has_10bit && !blur_probe ? 10 : 8, peak);
    fflush(stdout);
    const time_t end = time(NULL) + seconds;
    while (running && time(NULL) < end) {
        while (wl_display_prepare_read(display) != 0)
            if (wl_display_dispatch_pending(display) < 0) goto disconnected;
        if (wl_display_flush(display) < 0 && errno != EAGAIN) {
            wl_display_cancel_read(display);
            goto disconnected;
        }
        struct pollfd p = {.fd = wl_display_get_fd(display), .events = POLLIN};
        int result = poll(&p, 1, 100);
        if (result > 0 && (p.revents & POLLIN)) {
            if (wl_display_read_events(display) < 0 || wl_display_dispatch_pending(display) < 0) goto disconnected;
        } else {
            wl_display_cancel_read(display);
            if (result < 0 && errno != EINTR) goto disconnected;
            if (result > 0 && (p.revents & (POLLERR | POLLHUP))) goto disconnected;
        }
    }
    wl_display_disconnect(display);
    return failed ? 1 : 0;
disconnected:
    fprintf(stderr, "Wayland connection failed\n");
    wl_display_disconnect(display);
    return 1;
}
