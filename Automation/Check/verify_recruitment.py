"""Execute copied recruitment machine-code routines in a private test allocation.

Windows x64 only. Does not start, attach to, or modify the game. The population
getter is replaced by a controlled test stub; all tested gate instructions come
from the hash-verified game EXE and the shipped patch manifest.
"""
import ctypes
import hashlib
import json
import os
import struct
import sys
from pathlib import Path

sys.dont_write_bytecode = True
from verify_game import VerificationError, read_pe_sections, read_rva


class NativeRoutine:
    def __init__(self, code, result_type, argument_types):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong, ctypes.c_ulong]
        kernel.VirtualAlloc.restype = ctypes.c_void_p
        kernel.VirtualProtect.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
        kernel.VirtualProtect.restype = ctypes.c_int
        kernel.VirtualFree.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong]
        kernel.VirtualFree.restype = ctypes.c_int
        kernel.FlushInstructionCache.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
        kernel.FlushInstructionCache.restype = ctypes.c_int
        self.kernel = kernel
        self.address = kernel.VirtualAlloc(None, len(code), 0x3000, 0x04)  # RW
        if not self.address:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            ctypes.memmove(self.address, bytes(code), len(code))
            old = ctypes.c_ulong()
            if not kernel.VirtualProtect(self.address, len(code), 0x20, ctypes.byref(old)):  # RX
                raise ctypes.WinError(ctypes.get_last_error())
            if not kernel.FlushInstructionCache(ctypes.c_void_p(-1), self.address, len(code)):
                raise ctypes.WinError(ctypes.get_last_error())
            self.function = ctypes.WINFUNCTYPE(result_type, *argument_types)(self.address)
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.address:
            address, self.address = self.address, None
            if not self.kernel.VirtualFree(address, 0, 0x8000):
                raise ctypes.WinError(ctypes.get_last_error())


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def main():
    require(os.name == 'nt' and ctypes.sizeof(ctypes.c_void_p) == 8, 'Requires Windows x64 Python')
    require(len(sys.argv) == 2, 'Usage: python verify_recruitment.py <game.exe>')
    data = Path(sys.argv[1]).read_bytes()
    sections = read_pe_sections(data)
    manifest = json.loads((Path(__file__).parent / 'community-patch-manifest.json').read_text(encoding='utf-8'))
    require(hashlib.sha256(data).hexdigest().upper() == manifest['sha256'].upper(), 'Game EXE SHA256 mismatch')
    start, end = 0x1C0000, 0x292000
    pointer, integer = ctypes.c_void_p, ctypes.c_int
    cases = 0

    def make_image(patched, real_count=False):
        code = bytearray(read_rva(data, sections, start, end - start))
        for patch in manifest['patches']:
            pos = patch['rva'] - start
            original = bytes.fromhex(patch['original'])
            replacement = bytes.fromhex(patch['replacement'])
            require(0 <= pos and pos + len(original) <= len(code), 'Patch outside test image')
            require(code[pos:pos + len(original)] == original, 'Original bytes mismatch')
            require(len(original) == len(replacement), 'Patch length mismatch')
            if patched:
                code[pos:pos + len(original)] = replacement

        def put(rva, value):
            value = bytes.fromhex(value)
            code[rva-start:rva-start+len(value)] = value

        def redirect_call(rva, expected, stub):
            pos = rva - start
            require(code[pos] == 0xE8 and rva + 5 + struct.unpack_from('<i', code, pos+1)[0] == expected,
                    'Unexpected engine callback')
            target = start + len(code)
            struct.pack_into('<i', code, pos+1, target - (rva+5))
            code.extend(bytes.fromhex(stub))

        if not real_count:
            put(0x27D150, '8B01C3')  # Only test stub: fake enclave first dword.
        else:
            put(0x1D99E0, '31C0C3')  # Every non-null test character is alive.
        # Complete mutation routines retain their real pointer/record appends.
        # Use preallocated arrays and controlled callbacks; this does not test
        # Unreal object ownership, allocation, notification or save serialization.
        for rva, target, stub in [
            (0x2906A5, 0x143DAF0, 'C3'),
            (0x2906D2, 0x1DB7D0, 'C3'),
            (0x2906E1, 0x2D3460, 'C3'),
            (0x290784, 0x289F70, 'C3'),
            (0x2907A4, 0x1C40D0, '5756488BF9488BF2B950020000F3A45E5FC3'),
            (0x2907AF, 0x271960, 'C3'),
        ]:
            redirect_call(rva, target, stub)

        # Stop three larger operations after their capacity/non-capacity gates.
        # Original prologs and rejection paths execute; only successful engine
        # side effects are replaced by test returns using matching stack cleanup.
        put(0x290F84, 'B001488B7424404883C4205FC3')
        put(0x291A40, 'B0014883C440415E5F5BC3')
        put(0x2797F4, 'B0014883C4205D5E5FC3')
        put(0x279863, '32C04883C4205D5E5FC3')
        # Wrapper establishes the three live registers expected by the inlined
        # block; RCX=enclave, RDX=character record (flag at +31).
        wrapper_rva = start + len(code)
        code.extend(bytes.fromhex('5756554883EC20488BF9488BEA33F6E9'))
        code.extend(struct.pack('<i', 0x2797CD - (start + len(code) + 4)))
        image = NativeRoutine(code, ctypes.c_ubyte, [])

        def function(rva, args, result=ctypes.c_ubyte):
            return ctypes.WINFUNCTYPE(result, *args)(image.address + rva - start)
        return image, function, wrapper_rva

    for patched in [False, True]:
        image, function, wrapper = make_image(patched)
        try:
            single = function(0x276360, [pointer, integer])
            group = function(0x2763A0, [pointer, integer, integer])
            slots = function(0x27ADC0, [pointer, integer], integer)
            soft = function(0x281540, [pointer])
            restore = function(0x290F50, [pointer, integer])
            transfer = function(0x2919D0, [pointer, pointer, pointer, pointer, integer])
            inline = function(wrapper, [pointer, pointer])
            enclave = ctypes.create_string_buffer(0xB00)
            character = ctypes.create_string_buffer(0x500)
            for count in [0, 1, 8, 9, 10, 11, 12, 13, 20, 100, 1000, 0x7FFFFFFE]:
                struct.pack_into('<i', enclave, 0, count)
                for player in [0, 8]:
                    bypass = patched and bool(player)
                    for disabled in [0, 2]:
                        enclave[0xAF8] = bytes([player | disabled])
                        for hard in [0, 1, 2, 255]:
                            cap = 12 if hard else 9
                            allowed = not disabled and (bypass or count < cap)
                            label = 'patched=%s count=%s player=%s disabled=%s hard=%s' % (patched, count, player, disabled, hard)
                            require(bool(single(enclave, hard)) == allowed, 'Single mismatch: ' + label)
                            cases += 1
                            for size in [1, 2, 3, 12, 30]:
                                expected = not disabled and (bypass or size <= cap - count)
                                require(bool(group(enclave, size, hard)) == expected, 'Group mismatch: ' + label)
                                cases += 1
                            require(slots(enclave, hard) == cap - (0 if bypass else count), 'Slots mismatch: ' + label)
                            cases += 1
                            for rejected in [0, 1]:
                                character[0x408] = bytes([rejected])
                                require(bool(transfer(enclave, character, enclave, None, hard)) == (allowed and not rejected), 'Transfer mismatch: ' + label)
                                cases += 1
                        require(bool(soft(enclave)) == (not bypass and count > 9), 'Soft query mismatch')
                        require(bool(restore(enclave, 0)) == (not disabled and (bypass or count < 12)), 'Restore gate mismatch')
                        cases += 2
                        for departed in [0, 1]:
                            character[0x31] = bytes([departed])
                            require(bool(inline(enclave, character)) == (not disabled and not departed and (bypass or count < 12)), 'Inline gate/departed mismatch')
                            cases += 1
                        require(struct.unpack_from('<i', enclave)[0] == count, 'Gate changed true count input')
            print('PASS: %s native gates, player/NPC scope and other rejection conditions' % ('patched' if patched else 'original'))
        finally:
            image.close()

        image, function, _ = make_image(patched, real_count=True)
        try:
            live = function(0x290630, [pointer, pointer, integer, integer])
            record = function(0x290710, [pointer, pointer, integer])
            population = function(0x27D150, [pointer], integer)
            character = ctypes.create_string_buffer(0x500)
            for count in [0, 8, 9, 11, 12, 13, 20, 100]:
                for player in [0, 8]:
                    for hard in [0, 1]:
                        for disabled in [0, 2]:
                            enclave = ctypes.create_string_buffer(0xB00)
                            pointers = (pointer * (count + 1))()
                            for index in range(count):
                                pointers[index] = ctypes.addressof(character)
                            struct.pack_into('<Qii', enclave, 0x398, ctypes.addressof(pointers), count, count+1)
                            enclave[0xAF8] = bytes([player | disabled])
                            allowed = not disabled and ((patched and player) or count < (12 if hard else 9))
                            require(population(enclave) == count, 'Actual population getter initial mismatch')
                            require(bool(live(enclave, character, hard, 0)) == bool(allowed), 'TryAddCharacter result mismatch')
                            require(population(enclave) == count + int(bool(allowed)), 'Actual population after append mismatch')
                            require(pointers[count] == (ctypes.addressof(character) if allowed else None), 'Live append mismatch')
                            cases += 1
                            # Reset live roster for independent record tests.
                            struct.pack_into('<i', enclave, 0x3A0, count)
                            for departed in [0, 1]:
                                records = ctypes.create_string_buffer(0x250 * (count+1))
                                struct.pack_into('<Qii', enclave, 0x258, ctypes.addressof(records), count, count+1)
                                character[0] = b'Z'
                                character[0xA1] = bytes([departed])
                                can_add = bool(allowed and not departed)
                                require(bool(record(enclave, character, hard)) == can_add, 'TryAddCharacterRecord result mismatch')
                                require(struct.unpack_from('<i', enclave, 0x260)[0] == count+int(can_add), 'Record count mismatch')
                                require(records.raw[count*0x250:] == (character.raw[:0x250] if can_add else bytes(0x250)), 'Record append mismatch')
                                require(population(enclave) == count, 'Record gate changed live population')
                                cases += 1
            print('PASS: %s complete native append routines and unchanged real population getter' % ('patched' if patched else 'original'))
        finally:
            image.close()
    print('PASS: %d native cases; real gameplay, allocator, saves and engine callbacks remain untested' % cases)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, VerificationError) as error:
        raise SystemExit('FAIL: ' + str(error))
