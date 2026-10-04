#ifndef SOD2SE_ABI_H
#define SOD2SE_ABI_H
#include <stdint.h>
#include <stddef.h>
#define SOD2SE_NATIVE_ABI 1u
#define SOD2SE_OK 0
#define SOD2SE_INVALID -1
#define SOD2SE_UNSUPPORTED -2
#define SOD2SE_BUSY -3
#define SOD2SE_INTERNAL -4
#define SOD2SE_BUFFER_TOO_SMALL -5
typedef struct { const uint8_t *data; uint32_t len; } sod2se_utf8;
typedef int32_t (*sod2se_request)(void *, uint64_t, sod2se_utf8, sod2se_utf8, uint8_t *, uint32_t, uint32_t *);
typedef int32_t (*sod2se_log)(void *, uint64_t, uint32_t, sod2se_utf8, sod2se_utf8);
typedef struct {
    uint32_t abi_version, struct_size;
    void *context;
    uint64_t owner;
    sod2se_request request;
    sod2se_log log;
} sod2se_host;
typedef int32_t (*sod2se_start)(const sod2se_host *);
typedef int32_t (*sod2se_stop)(void);
typedef struct {
    uint32_t abi_version, struct_size;
    sod2se_utf8 id, version;
    sod2se_start start;
    sod2se_stop stop;
} sod2se_plugin;
typedef int32_t (*sod2se_plugin_entry_fn)(uint32_t, sod2se_plugin *);
#endif
