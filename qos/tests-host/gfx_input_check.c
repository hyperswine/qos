#define _POSIX_C_SOURCE 200809L
#include <stdarg.h>
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include "../../hal/unix/gfx.c"
void qos_hostlog(const char *fmt, ...) { (void)fmt; }
void fpr_cpanic(const char *message) { fprintf(stderr, "%s\n", message); abort(); }
int main(void) {
  unsetenv("FPR_EVDEV"); unsetenv("FPR_GFX_SIZE");
  gfx_init(640, 480);
  int64_t k, a, b;
  for (int i = 0; i < 30; i++) gfx_input_poll(&k, &a, &b);
  glfwSetWindowSize(G.window, 1280, 720);
  int resized = 0;
  for (int i = 0; i < 200 && !resized; i++) {
    gfx_input_poll(&k, &a, &b);
    if (k == 5 && a == 1280 && b == 720) resized = 1;
    if (!resized) { struct timespec nap = {0, 10000000}; nanosleep(&nap, 0); }
  }
  assert(resized); int w, h; gfx_dims(&w, &h); assert(w == 1280 && h == 720);
  assert(glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE);
  gfx_event_read = gfx_event_write;
  gfx_key_cb(G.window, GLFW_KEY_ENTER, 0, GLFW_PRESS, 0);
  gfx_char_cb(G.window, 'a');
  gfx_input_poll(&k, &a, &b); assert(k == 4 && a == 28 && b == 1);
  gfx_input_poll(&k, &a, &b); assert(k == 0); /* no duplicate ASCII activation */
  gfx_key_cb(G.window, GLFW_KEY_LEFT_SHIFT, 0, GLFW_PRESS, GLFW_MOD_SHIFT);
  gfx_key_cb(G.window, GLFW_KEY_TAB, 0, GLFW_PRESS, GLFW_MOD_SHIFT);
  gfx_input_poll(&k, &a, &b); assert(k == 4 && a == 1015);
  gfx_size_cb(G.window, 1024, 600);
  gfx_mouse_cb(G.window, GLFW_MOUSE_BUTTON_LEFT, GLFW_PRESS, 0);
  gfx_focus_cb(G.window, 0);
  gfx_input_poll(&k, &a, &b); assert(k == 5 && a == 1024 && b == 600);
  gfx_input_poll(&k, &a, &b); assert(k == 8 && a == 0 && gfx_mouse_buttons == 0);
  gfx_focus_cb(G.window, 1);
  gfx_key_cb(G.window, GLFW_KEY_TAB, 0, GLFW_PRESS, 0);
  gfx_input_poll(&k, &a, &b); assert(k == 8 && a == 1);
  gfx_input_poll(&k, &a, &b); assert(k == 4 && a == 15); /* modifiers reset on loss */
  setenv("FPR_EVDEV", "/dev/null", 1);
  gfx_focus_cb(G.window, 0); gfx_cursor_cb(G.window, 1, 2); gfx_mouse_cb(G.window, 0, GLFW_PRESS, 0);
  assert(gfx_event_read == gfx_event_write);
  puts("gfx-input: real GL resize, focus cancellation, key ordering and replay isolation HOLDS");
  glfwDestroyWindow(G.window); glfwTerminate(); return 0;
}
