#include <stdio.h>
#include <assert.h>
#include <string.h>
#include "dmx_compression.h"

void test_c_dmx_compression() {
    DMX_Compressor compressor;
    DMX_Decompressor decompressor;
    dmx_compressor_init(&compressor, 1);
    dmx_decompressor_init(&decompressor);

    uint8_t raw_frame[512];
    memset(raw_frame, 0, 512);

    uint8_t compressed[600];
    uint16_t comp_len = 0;

    // 1. 测试首帧（强制 I-Frame 发送）
    comp_len = dmx_compress(&compressor, raw_frame, compressed, sizeof(compressed), 1);
    assert(comp_len == 513);
    assert((compressed[0] & 0x0F) == 0x01);

    uint8_t decompressed[512];
    memset(decompressed, 0, 512);
    int dec_res = dmx_decompress(&decompressor, compressed, comp_len, decompressed);
    assert(dec_res == 0);
    assert(memcmp(raw_frame, decompressed, 512) == 0);
    assert(decompressor.sync_lost == 0);

    // 2. 测试 Keepalive 模式
    comp_len = dmx_compress(&compressor, raw_frame, compressed, sizeof(compressed), 0);
    assert(comp_len == 1);
    assert((compressed[0] & 0x0F) == 0x05);
    assert((compressed[0] >> 4) == 1); // 序列号自增
    
    dec_res = dmx_decompress(&decompressor, compressed, comp_len, decompressed);
    assert(dec_res == 0);

    // 3. 测试增量变化（稀疏模式 - 改变 2 个通道）
    raw_frame[10] = 0xAA;
    raw_frame[200] = 0xBB;
    comp_len = dmx_compress(&compressor, raw_frame, compressed, sizeof(compressed), 0);
    // Header(1) + Count(1) + 2 * [Idx(2) + Val(1)] = 8 字节
    assert(comp_len == 8); 
    assert((compressed[0] & 0x0F) == 0x02);

    memset(decompressed, 0, 512);
    dec_res = dmx_decompress(&decompressor, compressed, comp_len, decompressed);
    assert(dec_res == 0);
    assert(decompressed[10] == 0xAA);
    assert(decompressed[200] == 0xBB);
    assert(memcmp(raw_frame, decompressed, 512) == 0);

    // 4. 测试增量变化（Range模式 - 连续 30 个通道）
    memset(raw_frame, 0, 512);
    // 先发送 I-Frame 建立新基线
    dmx_compress(&compressor, raw_frame, compressed, sizeof(compressed), 1);
    dmx_decompress(&decompressor, compressed, 513, decompressed);

    // 修改 10 到 39 通道
    for (int i = 10; i < 40; i++) {
        raw_frame[i] = 100;
    }
    comp_len = dmx_compress(&compressor, raw_frame, compressed, sizeof(compressed), 0);
    // Header(1) + Start(2) + Span(2) + 30 = 35 字节
    assert((compressed[0] & 0x0F) == 0x04); // Range Mode
    assert(comp_len == 35);

    memset(decompressed, 0, 512);
    dec_res = dmx_decompress(&decompressor, compressed, comp_len, decompressed);
    assert(dec_res == 0);
    assert(decompressed[10] == 100);
    assert(decompressed[39] == 100);
    assert(memcmp(raw_frame, decompressed, 512) == 0);

    // 5. 测试丢包与同步恢复
    // 跳过一帧的发送以制造序列号跳跃
    // 当前 compressor.seq 应为 4
    uint8_t seq_before = compressor.seq;
    
    // 压缩一帧，但丢弃 (不发给 decompressor)
    raw_frame[50] = 50;
    uint16_t dropped_len = dmx_compress(&compressor, raw_frame, compressed, sizeof(compressed), 0);
    
    // 压缩下一帧，修改通道 60
    raw_frame[60] = 60;
    comp_len = dmx_compress(&compressor, raw_frame, compressed, sizeof(compressed), 0);
    
    // 此时 decompressor 收到不连续的 seq，应判定丢包并失去同步
    memset(decompressed, 0, 512);
    dec_res = dmx_decompress(&decompressor, compressed, comp_len, decompressed);
    assert(dec_res == -3); // 返回失去同步错误代码
    assert(decompressor.sync_lost == 1);
    assert(decompressor.state[60] != 60); // 拒绝更新

    // 重新发送 I-Frame 应该恢复同步
    comp_len = dmx_compress(&compressor, raw_frame, compressed, sizeof(compressed), 1);
    dec_res = dmx_decompress(&decompressor, compressed, comp_len, decompressed);
    assert(dec_res == 0);
    assert(decompressor.sync_lost == 0);
    assert(decompressor.state[50] == 50);
    assert(decompressor.state[60] == 60);
    assert(memcmp(raw_frame, decompressed, 512) == 0);

    printf("C DMX Compression Tests Passed Successfully!\n");
}

int main() {
    test_c_dmx_compression();
    return 0;
}
