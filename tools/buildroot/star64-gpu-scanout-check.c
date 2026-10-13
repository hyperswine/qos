/* SPDX-License-Identifier: MIT
 * Physical dma-buf interop check. Allocates a separate display-controller
 * buffer; never modesets or replaces the visible framebuffer. Cross-build
 * with the image's compiler and -lEGL -lGLESv2, then use the private PVR stack.
 */
#define _GNU_SOURCE
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl31.h>
#include <GLES2/gl2ext.h>
#include <drm/drm.h>
#include <drm/drm_mode.h>
#include <drm/drm_fourcc.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#define REQUIRE(x) do { if (!(x)) { \
    fprintf(stderr, "FAIL line %d: EGL=0x%x GL=0x%x\n", \
            __LINE__, eglGetError(), glGetError()); exit(1); \
} } while (0)

static double now(void) {
    struct timespec t;
    REQUIRE(clock_gettime(CLOCK_MONOTONIC, &t) == 0);
    return t.tv_sec + t.tv_nsec * 1e-9;
}

int main(int argc, char **argv) {
    int fd = open(argc > 1 ? argv[1] : "/dev/dri/card0", O_RDWR | O_CLOEXEC);
    REQUIRE(fd >= 0);
    struct drm_mode_create_dumb cd = {.width=1920, .height=1080, .bpp=32};
    REQUIRE(ioctl(fd, DRM_IOCTL_MODE_CREATE_DUMB, &cd) == 0);
    struct drm_prime_handle prime = {.handle=cd.handle, .flags=DRM_CLOEXEC | DRM_RDWR};
    REQUIRE(ioctl(fd, DRM_IOCTL_PRIME_HANDLE_TO_FD, &prime) == 0);
    struct drm_mode_map_dumb md = {.handle=cd.handle};
    REQUIRE(ioctl(fd, DRM_IOCTL_MODE_MAP_DUMB, &md) == 0);
    volatile uint32_t *map = mmap(NULL, cd.size, PROT_READ | PROT_WRITE,
                                  MAP_SHARED, fd, md.offset);
    REQUIRE(map != MAP_FAILED);

    PFNEGLGETPLATFORMDISPLAYEXTPROC platform =
        (PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
    REQUIRE(platform);
    EGLDisplay d = platform(EGL_PLATFORM_SURFACELESS_MESA, EGL_DEFAULT_DISPLAY, NULL);
    EGLint major, minor, n;
    REQUIRE(eglInitialize(d, &major, &minor));
    REQUIRE(eglBindAPI(EGL_OPENGL_ES_API));
    const EGLint config_attrs[] = {EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
        EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT, EGL_NONE};
    EGLConfig config;
    REQUIRE(eglChooseConfig(d, config_attrs, &config, 1, &n) && n);
    const EGLint context_attrs[] = {EGL_CONTEXT_MAJOR_VERSION, 3,
        EGL_CONTEXT_MINOR_VERSION, 1, EGL_NONE};
    EGLContext context = eglCreateContext(d, config, EGL_NO_CONTEXT, context_attrs);
    REQUIRE(context != EGL_NO_CONTEXT);
    REQUIRE(eglMakeCurrent(d, EGL_NO_SURFACE, EGL_NO_SURFACE, context));
    const char *renderer = (const char *)glGetString(GL_RENDERER);
    printf("renderer=%s\n", renderer ? renderer : "absent");
    REQUIRE(renderer && strstr(renderer, "PowerVR"));

    PFNEGLCREATEIMAGEKHRPROC create =
        (PFNEGLCREATEIMAGEKHRPROC)eglGetProcAddress("eglCreateImageKHR");
    PFNEGLDESTROYIMAGEKHRPROC destroy =
        (PFNEGLDESTROYIMAGEKHRPROC)eglGetProcAddress("eglDestroyImageKHR");
    PFNGLEGLIMAGETARGETRENDERBUFFERSTORAGEOESPROC storage =
        (PFNGLEGLIMAGETARGETRENDERBUFFERSTORAGEOESPROC)
        eglGetProcAddress("glEGLImageTargetRenderbufferStorageOES");
    REQUIRE(create && destroy && storage);
    const EGLint image_attrs[] = {EGL_WIDTH, 1920, EGL_HEIGHT, 1080,
        EGL_LINUX_DRM_FOURCC_EXT, DRM_FORMAT_XRGB8888,
        EGL_DMA_BUF_PLANE0_FD_EXT, prime.fd, EGL_DMA_BUF_PLANE0_OFFSET_EXT, 0,
        EGL_DMA_BUF_PLANE0_PITCH_EXT, (EGLint)cd.pitch, EGL_NONE};
    EGLImageKHR image = create(d, EGL_NO_CONTEXT, EGL_LINUX_DMA_BUF_EXT, NULL, image_attrs);
    REQUIRE(image != EGL_NO_IMAGE_KHR);
    GLuint rb, dst, texture, src;
    glGenRenderbuffers(1, &rb);
    glBindRenderbuffer(GL_RENDERBUFFER, rb);
    storage(GL_RENDERBUFFER, (GLeglImageOES)image);
    REQUIRE(glGetError() == GL_NO_ERROR);
    glGenFramebuffers(1, &dst);
    glBindFramebuffer(GL_FRAMEBUFFER, dst);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, rb);
    REQUIRE(glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE);
    glClearColor(1, 0, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT);
    glFinish();
    REQUIRE(glGetError() == GL_NO_ERROR && (map[0] & 0xffffff) == 0xff0000);

    /* Four known source colors verify scaling, vertical flip and RGB order. */
    const unsigned char pixels[] = {255,0,0,255, 0,255,0,255,
                                     0,0,255,255, 255,255,255,255};
    glGenTextures(1, &texture);
    glBindTexture(GL_TEXTURE_2D, texture);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 2, 2, 0, GL_RGBA, GL_UNSIGNED_BYTE, pixels);
    glGenFramebuffers(1, &src);
    glBindFramebuffer(GL_READ_FRAMEBUFFER, src);
    glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, texture, 0);
    REQUIRE(glCheckFramebufferStatus(GL_READ_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, dst);
    double start = now();
    for (int i = 0; i < 100; i++) {
        glBlitFramebuffer(0, 2, 2, 0, 0, 0, 1920, 1080, GL_COLOR_BUFFER_BIT, GL_NEAREST);
        glFinish();
    }
    double ms = (now() - start) * 10;
    REQUIRE(glGetError() == GL_NO_ERROR);
    uint32_t a = map[0] & 0xffffff, b = map[1919] & 0xffffff;
    uint32_t c = map[1079 * (cd.pitch / 4)] & 0xffffff;
    uint32_t z = map[1079 * (cd.pitch / 4) + 1919] & 0xffffff;
    printf("corners=%06x,%06x,%06x,%06x blit-ms=%.3f\n", a, b, c, z, ms);
    REQUIRE(a == 0x0000ff && b == 0xffffff && c == 0xff0000 && z == 0x00ff00);
    glDeleteFramebuffers(1, &src);
    glDeleteFramebuffers(1, &dst);
    glDeleteTextures(1, &texture);
    glDeleteRenderbuffers(1, &rb);
    REQUIRE(destroy(d, image));
    eglMakeCurrent(d, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
    eglDestroyContext(d, context);
    eglTerminate(d);
    munmap((void *)map, cd.size);
    close(prime.fd);
    struct drm_mode_destroy_dumb dd = {.handle=cd.handle};
    REQUIRE(ioctl(fd, DRM_IOCTL_MODE_DESTROY_DUMB, &dd) == 0);
    close(fd);
    puts("DMA_BUF_GPU_BLIT_PASS scale orientation RGB CPU-coherence");
    return 0;
}
