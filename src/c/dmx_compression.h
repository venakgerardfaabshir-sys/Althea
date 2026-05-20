#ifndef DMX_COMPRESSION_H
#define DMX_COMPRESSION_H

#include <stdint.h>

#define DMX_SLOT_COUNT 512

typedef struct {
    uint8_t last_state[DMX_SLOT_COUNT];
    uint8_t seq;
    uint8_t flicker_threshold;
} DMX_Compressor;

typedef struct {
    uint8_t state[DMX_SLOT_COUNT];
    int8_t last_seq;
    uint8_t sync_lost;
} DMX_Decompressor;

void dmx_compressor_init(DMX_Compressor *c, uint8_t flicker_threshold);
void dmx_decompressor_init(DMX_Decompressor *d);

// Compress: returns length of compressed bytes, or 0 if output buffer is too small
uint16_t dmx_compress(DMX_Compressor *c, const uint8_t *current_slots, uint8_t *out_buf, uint16_t out_max, uint8_t force_keyframe);

// Decompress: returns 0 on success, or a negative error code on failure
int dmx_decompress(DMX_Decompressor *d, const uint8_t *in_buf, uint16_t in_len, uint8_t *out_slots);

#endif // DMX_COMPRESSION_H
