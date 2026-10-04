#include "sod2se.h"
#include <windows.h>
#include <stdio.h>
#include <string.h>
_Static_assert(sizeof(sod2se_utf8)==16,"UTF8 ABI");
_Static_assert(sizeof(sod2se_host)==40,"Host ABI");
_Static_assert(sizeof(sod2se_plugin)==56,"Plugin ABI");
_Static_assert(offsetof(sod2se_host,owner)==16,"Owner ABI");
static int registered;
static int32_t request(void *context,uint64_t owner,sod2se_utf8 operation,sod2se_utf8 input,uint8_t *output,uint32_t capacity,uint32_t *used) {
    (void)context; (void)input;
    if(owner!=7 || capacity<2) return SOD2SE_INVALID;
    if(operation.len==17 && !memcmp(operation.data,"settings.register",17)) registered++;
    else if(operation.len!=20 || memcmp(operation.data,"translation.register",20)) return SOD2SE_INVALID;
    memcpy(output,"{}",2); *used=2; return 0;
}
int main(int argc,char **argv) {
    if(argc!=3) return 1;
    HMODULE module=LoadLibraryA(argv[1]); if(!module) return 2;
    FARPROC address=GetProcAddress(module,"sod2se_plugin_entry"); if(!address) return 3;
    sod2se_plugin_entry_fn entry; memcpy(&entry,&address,sizeof(entry));
    sod2se_plugin plugin={0};
    if(entry(0,&plugin)!=SOD2SE_UNSUPPORTED || entry(SOD2SE_NATIVE_ABI,&plugin)!=0) return 4;
    if(plugin.struct_size!=sizeof(plugin) || plugin.abi_version!=1 || !plugin.start || !plugin.stop) return 5;
    sod2se_host host={1,sizeof(sod2se_host),NULL,7,request,NULL};
    if(plugin.start(&host)!=0 || registered!=1 || plugin.stop()!=0) return 6;
    FreeLibrary(module);
    module=LoadLibraryA(argv[2]); if(!module) return 7;
    address=GetProcAddress(module,"sod2se_runtime_start"); if(!address) return 8;
    typedef uint32_t (WINAPI *runtime_start)(void *);
    runtime_start initialize; memcpy(&initialize,&address,sizeof(initialize));
    if((int32_t)initialize(NULL)!=SOD2SE_UNSUPPORTED) return 9;
    FreeLibrary(module);
    puts("PASS: independent C ABI and actual runtime bootstrap refusal in an inert foreign process"); return 0;
}
