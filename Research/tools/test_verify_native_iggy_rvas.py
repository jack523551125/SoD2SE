import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('verify_native', ROOT / 'verify_native.py')
verify_native = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verify_native
SPEC.loader.exec_module(verify_native)

DLL_HASH = '09049ffc7b48639c72336bb809035fa1c1b827e898693fbc2968165bd23940a6'
EVIDENCE = {
    'iggy_callback_abi': {
        'dll_sha256': DLL_HASH,
        'disassembly_rvas': {
            'result_path_export': '0x66890',
            'set_s32_export': '0x67880',
            'set_string_utf8_export': '0x67a30',
        },
        'callback': {
            'registration_slots': {
                'narrow_function_pointer_rva': '0x101D50',
                'wide_function_pointer_rva': '0x101D60',
            }
        },
    }
}
SOURCE = '''
inline bool PinnedFile(HMODULE module) { return true; }
enum class InitStatus { WaitingForModule, UnsupportedHash, UnsupportedExports, Ready };
inline InitStatus initStatus;
inline bool verified;
inline Callback* callbackSlot;
inline Callback resultPath, setInt, setText;
static const BYTE expected[32] = {
    0x09,0x04,0x9f,0xfc,0x7b,0x48,0x63,0x9c,0x72,0x33,0x6b,0xb8,0x09,0x03,0x5f,0xa1,
    0xc1,0xb8,0x27,0xe8,0x98,0x69,0x3f,0xbc,0x29,0x68,0x16,0x5b,0xd2,0x39,0x40,0xa6};
inline InitStatus Initialize(mcm::State* state, HANDLE gate) {
    const auto module = GetModuleHandleW(L"iggy_w64.dll");
    if (!module) return initStatus = InitStatus::WaitingForModule;
    if (!PinnedFile(module)) return initStatus = InitStatus::UnsupportedHash;
    auto base = reinterpret_cast<unsigned char*>(module);
    resultPath = reinterpret_cast<Callback>(GetProcAddress(module, "IggyPlayerCallbackResultPath"));
    setInt = reinterpret_cast<Callback>(GetProcAddress(module, "IggyValueSetS32RS"));
    setText = reinterpret_cast<Callback>(GetProcAddress(module, "IggyValueSetStringUTF8RS"));
    if (reinterpret_cast<void*>(resultPath) != base + 0x66890 ||
        reinterpret_cast<void*>(setInt) != base + 0x67880 ||
        reinterpret_cast<void*>(setText) != base + 0x67a30)
        return initStatus = InitStatus::UnsupportedExports;
    callbackSlot = reinterpret_cast<Callback*>(base + 0x101d50);
    verified = true;
    return initStatus = InitStatus::Ready;
}
inline bool CanRetryInitialization() { return initStatus == InitStatus::WaitingForModule; }
inline bool InitializationRetryDue(unsigned& frames) { return (++frames % 120) == 1; }
void Pump() { if (!verified && CanRetryInitialization() && InitializationRetryDue(initializeRetry)) Initialize(channel, channelGate); }
'''


class GuardedIggyRvaTests(unittest.TestCase):
    def test_pinned_and_export_checked_iggy_rvas_are_allowed(self):
        allowed = verify_native.check_guarded_iggy_rvas_text(SOURCE, EVIDENCE)
        self.assertEqual(allowed, {0x66890, 0x67880, 0x67a30, 0x101d50})
        with tempfile.TemporaryDirectory() as directory:
            header = Path(directory) / 'NativeSettingsIggy.h'
            header.write_text(SOURCE, encoding='utf-8')
            verify_native.check_no_raw_offsets(Path(directory), 'MeleeOffsets.h', allowed)

    def test_unguarded_rva_and_hash_or_export_drift_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            header = Path(directory) / 'NativeSettingsIggy.h'
            header.write_text(SOURCE + '\nvoid Other() { auto p = base + 0x123456; }\n', encoding='utf-8')
            allowed = verify_native.check_guarded_iggy_rvas_text(header.read_text(), EVIDENCE)
            with self.assertRaises(verify_native.VerificationError):
                verify_native.check_no_raw_offsets(Path(directory), 'MeleeOffsets.h', allowed)
        wrong_hash = dict(EVIDENCE)
        wrong_hash['iggy_callback_abi'] = dict(EVIDENCE['iggy_callback_abi'], dll_sha256='0' * 64)
        with self.assertRaises(verify_native.VerificationError):
            verify_native.check_guarded_iggy_rvas_text(SOURCE, wrong_hash)
        wrong_export = SOURCE.replace('base + 0x67880', 'base + 0x67881')
        with self.assertRaises(verify_native.VerificationError):
            verify_native.check_guarded_iggy_rvas_text(wrong_export, EVIDENCE)


if __name__ == '__main__':
    unittest.main()
