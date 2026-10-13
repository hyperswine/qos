/* SPDX-License-Identifier: MIT
 * Offscreen rendering check. Success says nothing about HDMI or GPU speed.
 */
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <stdio.h>
#include <stdlib.h>

static void fail(const char *what) {
    fprintf(stderr, "%s: EGL error 0x%x\n", what, eglGetError());
    exit(1);
}

int main(void) {
    PFNEGLGETPLATFORMDISPLAYEXTPROC get_display =
        (PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
    if (!get_display) fail("surfaceless platform entry point absent");
    EGLDisplay d = get_display(EGL_PLATFORM_SURFACELESS_MESA, EGL_DEFAULT_DISPLAY, NULL);
    EGLint major, minor;
    if (d == EGL_NO_DISPLAY || !eglInitialize(d, &major, &minor)) fail("eglInitialize");
    printf("EGL %d.%d vendor=%s\n", major, minor, eglQueryString(d, EGL_VENDOR));
    if (!eglBindAPI(EGL_OPENGL_ES_API)) fail("eglBindAPI");
    const EGLint attrs[] = {EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
        EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT, EGL_RED_SIZE, 8,
        EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_NONE};
    EGLConfig config;
    EGLint n;
    if (!eglChooseConfig(d, attrs, &config, 1, &n) || n < 1) fail("ES3 config absent");
    const EGLint context_attrs[] = {EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE};
    EGLContext context = eglCreateContext(d, config, EGL_NO_CONTEXT, context_attrs);
    if (context == EGL_NO_CONTEXT) fail("eglCreateContext");
    if (!eglMakeCurrent(d, EGL_NO_SURFACE, EGL_NO_SURFACE, context)) fail("eglMakeCurrent");
    printf("GL vendor=%s renderer=%s version=%s\n", glGetString(GL_VENDOR),
        glGetString(GL_RENDERER), glGetString(GL_VERSION));
    GLuint fbo, color;
    glGenFramebuffers(1, &fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glGenRenderbuffers(1, &color);
    glBindRenderbuffer(GL_RENDERBUFFER, color);
    glRenderbufferStorage(GL_RENDERBUFFER, GL_RGBA8, 16, 16);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, color);
    if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
        fprintf(stderr, "offscreen framebuffer incomplete\n");
        return 1;
    }
    glViewport(0, 0, 16, 16);
    glClearColor(0.25f, 0.5f, 0.75f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    unsigned char pixel[4] = {0};
    glReadPixels(8, 8, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel);
    GLenum error = glGetError();
    int ok = error == GL_NO_ERROR && abs((int)pixel[0] - 64) <= 2 &&
        abs((int)pixel[1] - 128) <= 2 && abs((int)pixel[2] - 191) <= 2;
    printf("pixel=%u,%u,%u,%u GL-error=0x%x result=%s\n",
        pixel[0], pixel[1], pixel[2], pixel[3], error, ok ? "PASS" : "FAIL");
    glDeleteRenderbuffers(1, &color);
    glDeleteFramebuffers(1, &fbo);
    eglMakeCurrent(d, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
    eglDestroyContext(d, context);
    eglTerminate(d);
    return ok ? 0 : 1;
}
