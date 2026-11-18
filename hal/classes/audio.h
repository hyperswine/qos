/* audio.h -- the AUDIO device class: sound out.
 *
 *   audTone d freq ms   -> Int   play a tone of freq Hz for ms; 0 sent,
 *                                -1 no listener (the tone is dropped)
 */
#ifndef QOS_CLASS_AUDIO_H
#define QOS_CLASS_AUDIO_H
#include <stdint.h>
#define QOS_AUDIO_OPS_VERSION 1u
typedef struct qos_audio_ops {
  uint32_t version;
  int (*tone)(void *st, uint32_t freq_hz, uint32_t ms);
} qos_audio_ops;
#endif
