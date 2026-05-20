#include "dmx_compression.h"
#include <string.h>

void dmx_compressor_init(DMX_Compressor *c, uint8_t flicker_threshold) {
    memset(c->last_state, 0, DMX_SLOT_COUNT);
    c->seq = 0;
    c->flicker_threshold = flicker_threshold;
}

void dmx_decompressor_init(DMX_Decompressor *d) {
    memset(d->state, 0, DMX_SLOT_COUNT);
    d->last_seq = -1;
    d->sync_lost = 1;
}

uint16_t dmx_compress(DMX_Compressor *c, const uint8_t *current_slots, uint8_t *out_buf, uint16_t out_max, uint8_t force_keyframe) {
    uint8_t seq = c->seq;
    c->seq = (c->seq + 1) % 16;

    // 1. Flicker filtering
    uint8_t filtered[DMX_SLOT_COUNT];
    uint16_t changed_count = 0;
    uint16_t changed_indices[DMX_SLOT_COUNT];
    
    for (uint16_t i = 0; i < DMX_SLOT_COUNT; i++) {
        uint8_t diff = (current_slots[i] > c->last_state[i]) ? 
                       (current_slots[i] - c->last_state[i]) : 
                       (c->last_state[i] - current_slots[i]);
                       
        if (diff <= c->flicker_threshold) {
            filtered[i] = c->last_state[i];
        } else {
            filtered[i] = current_slots[i];
        }
        
        if (filtered[i] != c->last_state[i]) {
            changed_indices[changed_count] = i;
            changed_count++;
        }
    }

    // 2. Keepalive mode: no changes and not a forced keyframe
    if (changed_count == 0 && !force_keyframe) {
        if (out_max >= 1) {
            out_buf[0] = (seq << 4) | 0x05;
            return 1;
        }
        return 0;
    }

    // 3. Forced I-Frame or too many changes
    if (force_keyframe || changed_count > 150) {
        if (out_max >= 513) {
            out_buf[0] = (seq << 4) | 0x01;
            memcpy(&out_buf[1], filtered, DMX_SLOT_COUNT);
            memcpy(c->last_state, filtered, DMX_SLOT_COUNT);
            return 513;
        }
        return 0;
    }

    // 4. Adaptive Mode Selection: Sparse vs. Bitmap vs. Range
    uint16_t sparse_size = 2 + changed_count * 3;
    uint16_t bitmap_size = 1 + 64 + changed_count;
    uint16_t range_size = 0xFFFF;
    
    uint16_t start = 0, span = 0;
    if (changed_count > 0) {
        start = changed_indices[0];
        span = changed_indices[changed_count - 1] - start + 1;
        range_size = 5 + span;
    }

    uint8_t best_mode = 0; // 0: Sparse, 1: Bitmap, 2: Range
    uint16_t min_size = sparse_size;

    if (bitmap_size < min_size) {
        best_mode = 1;
        min_size = bitmap_size;
    }
    if (range_size < min_size) {
        best_mode = 2;
        min_size = range_size;
    }

    if (min_size > out_max) {
        return 0;
    }

    // 5. Serialize according to best mode
    if (best_mode == 0) { // P-Sparse
        out_buf[0] = (seq << 4) | 0x02;
        out_buf[1] = (uint8_t)changed_count;
        uint16_t offset = 2;
        for (uint16_t i = 0; i < changed_count; i++) {
            uint16_t idx = changed_indices[i];
            out_buf[offset] = (idx >> 8) & 0xFF;
            out_buf[offset+1] = idx & 0xFF;
            out_buf[offset+2] = filtered[idx];
            offset += 3;
        }
        memcpy(c->last_state, filtered, DMX_SLOT_COUNT);
        return offset;
    } else if (best_mode == 1) { // P-Bitmap
        out_buf[0] = (seq << 4) | 0x03;
        memset(&out_buf[1], 0, 64);
        uint16_t offset = 65;
        for (uint16_t i = 0; i < changed_count; i++) {
            uint16_t idx = changed_indices[i];
            out_buf[1 + (idx / 8)] |= (1 << (idx % 8));
            out_buf[offset] = filtered[idx];
            offset++;
        }
        memcpy(c->last_state, filtered, DMX_SLOT_COUNT);
        return offset;
    } else { // P-Range
        out_buf[0] = (seq << 4) | 0x04;
        out_buf[1] = (start >> 8) & 0xFF;
        out_buf[2] = start & 0xFF;
        out_buf[3] = (span >> 8) & 0xFF;
        out_buf[4] = span & 0xFF;
        memcpy(&out_buf[5], &filtered[start], span);
        memcpy(c->last_state, filtered, DMX_SLOT_COUNT);
        return 5 + span;
    }
}

int dmx_decompress(DMX_Decompressor *d, const uint8_t *in_buf, uint16_t in_len, uint8_t *out_slots) {
    if (in_len == 0) return -1;

    uint8_t header = in_buf[0];
    uint8_t seq = (header >> 4) & 0x0F;
    uint8_t frame_type = header & 0x0F;

    if (d->last_seq != -1) {
        uint8_t expected_seq = (d->last_seq + 1) % 16;
        if (seq != expected_seq && frame_type != 0x01) {
            d->sync_lost = 1;
        }
    }
    d->last_seq = seq;

    if (frame_type == 0x01) {
        if (in_len < 513) return -2;
        memcpy(d->state, &in_buf[1], DMX_SLOT_COUNT);
        d->sync_lost = 0;
    } else if (d->sync_lost) {
        // Lost sync: reject incremental updates and maintain last state
        memcpy(out_slots, d->state, DMX_SLOT_COUNT);
        return -3; 
    } else if (frame_type == 0x02) { // P-Sparse
        uint8_t count = in_buf[1];
        if (in_len < 2 + count * 3) return -4;
        uint16_t offset = 2;
        for (uint8_t i = 0; i < count; i++) {
            uint16_t idx = (in_buf[offset] << 8) | in_buf[offset+1];
            uint8_t val = in_buf[offset+2];
            if (idx < DMX_SLOT_COUNT) {
                d->state[idx] = val;
            }
            offset += 3;
        }
    } else if (frame_type == 0x03) { // P-Bitmap
        if (in_len < 65) return -5;
        const uint8_t *bitmap = &in_buf[1];
        uint16_t offset = 65;
        for (uint16_t idx = 0; idx < DMX_SLOT_COUNT; idx++) {
            if (bitmap[idx / 8] & (1 << (idx % 8))) {
                if (offset >= in_len) return -6;
                d->state[idx] = in_buf[offset];
                offset++;
            }
        }
    } else if (frame_type == 0x04) { // P-Range
        if (in_len < 5) return -7;
        uint16_t start = (in_buf[1] << 8) | in_buf[2];
        uint16_t span = (in_buf[3] << 8) | in_buf[4];
        if (in_len < 5 + span || start + span > DMX_SLOT_COUNT) return -8;
        memcpy(&d->state[start], &in_buf[5], span);
    } else if (frame_type == 0x05) { // Keepalive
        // State remains unchanged
    } else {
        return -9; // Unknown frame type
    }

    memcpy(out_slots, d->state, DMX_SLOT_COUNT);
    return 0;
}
