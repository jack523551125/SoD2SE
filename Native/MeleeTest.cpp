#include "MeleeNative.cpp"
#include <vector>
#include <memory>
#include <stdexcept>
#include <limits>

namespace {
void Check(bool condition, const char* message) { if (!condition) throw std::runtime_error(message); }
template<class T> void Write(uintptr_t p, uintptr_t offset, T value) { std::memcpy(reinterpret_cast<void*>(p + offset), &value, sizeof(value)); }
std::vector<std::unique_ptr<unsigned char[]>> objects;
uintptr_t Make() {
    auto p = std::make_unique<unsigned char[]>(0x2000); auto address = reinterpret_cast<uintptr_t>(p.get());
    objects.push_back(std::move(p)); return address;
}
uint32_t nextName = 4096;
uintptr_t pool;
uintptr_t Class(const char* name, uintptr_t parent = 0) {
    auto p = Make();
    Write(p, melee::field::UObjectFNameIndex, nextName);
    strcpy_s(reinterpret_cast<char*>(pool + nextName + melee::field::FNameEntryHeader), 120, name);
    nextName += 128; Write(p, melee::field::UClassSuperStruct, parent); return p;
}
uintptr_t Object(const char* name) { auto p = Make(); Write(p, melee::field::UObjectClass, Class(name)); return p; }
float receivedAction = 0, receivedAnimation = 0;
void* attitudeController = nullptr; void* attitudeTarget = nullptr;
unsigned char __fastcall FriendlyAttitude(void* controller, void* target) { attitudeController = controller; attitudeTarget = target; return 0; }
int receivedType = 0; void* receivedTick = nullptr; bool receivedRoot = false;
void __fastcall ActionSink(void*, float delta, int type, void* tick) { receivedAction = delta; receivedType = type; receivedTick = tick; }
void __fastcall AnimationSink(void*, float delta, bool root) { receivedAnimation = delta; receivedRoot = root; }
}
int main() {
    try {
        // Fake UObject graph exercises the real classifier without executing game code.
        base = reinterpret_cast<uintptr_t>(VirtualAlloc(nullptr, 0x4800000, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE));
        Check(base != 0, "fixture allocation");
        pool = Make(); // Names below 8192 fit this fixture.
        Write(base, melee::rva::FNamePool, pool);
        auto pawn = Object("DaytonHumanCharacter"), component = Object("ActionComponent");
        auto impl = Object("HumanMeleeActionImpl_C"), mesh = Object("SkeletalMeshComponent");
        auto player = Object("DaytonLocalPlayer"), controller = Make();
        auto weapon = Object("MeleeWeaponItemInstance"), stats = Object("MeleeWeaponResourceStats");
        Write(base, melee::rva::LocalPlayerGlobal, player);
        Write(player, melee::field::LocalPlayerController, controller);
        Write(controller, melee::field::ControllerPawn, pawn);
        Write(component, melee::field::ActionComponentPawn, pawn);
        Write(component, melee::field::ActionImplementation, impl);
        Write(pawn, melee::field::PawnActionComponent, component);
        Write(mesh, melee::field::AnimationComponentPawn, pawn);
        Write(pawn, melee::field::PawnAnimationComponent, mesh);
        Write(weapon, melee::field::WeaponStats, stats);
        int rates[] = {125, 150, 175, 200}, scopes[] = {1, 0, 0};
        auto settings = melee::Pack(true, rates, scopes); config.store(settings);
        Write(impl, melee::field::MeleeUnarmedMarker, Make());
        Check(SafeMultiplier(reinterpret_cast<void*>(component), false) == 1.25f, "close combat classification");
        Write(impl, melee::field::MeleeWeapon, weapon);
        for (int type = 0; type < 3; ++type) {
            Write(stats, melee::field::WeaponCategory, static_cast<unsigned char>(type));
            const float expected[] = {1.75f, 1.5f, 2.0f};
            Check(SafeMultiplier(reinterpret_cast<void*>(component), false) == expected[type], "weapon classification");
            Check(SafeMultiplier(reinterpret_cast<void*>(mesh), true) == expected[type], "animation/action multiplier parity");
        }
        originalAction = ActionSink; originalAnimation = AnimationSink;
        TickAction(reinterpret_cast<void*>(component), 0.02f, 7, reinterpret_cast<void*>(123));
        TickAnimation(reinterpret_cast<void*>(mesh), 0.02f, true);
        Check(receivedAction == 0.04f && receivedAnimation == 0.04f, "clock synchronization");
        Check(receivedType == 7 && receivedTick == reinterpret_cast<void*>(123) && receivedRoot, "ABI arguments preserved");
        Write(impl, melee::field::UObjectClass, Class("HumanHeavyWeaponChannelAttackActionImpl_C"));
        Write(impl, melee::field::HeavyWeapon, weapon);
        Check(SafeMultiplier(reinterpret_cast<void*>(component), false) == 2.0f, "heavy channel attack");
        Write(controller, melee::field::ControllerPawn, uintptr_t{0});
        Check(SafeMultiplier(reinterpret_cast<void*>(component), false) == 1.0f, "scope exclusion");
        scopes[2] = 1; config.store(melee::Pack(true, rates, scopes));
        Check(SafeMultiplier(reinterpret_cast<void*>(component), false) == 2.0f, "other humans opt in");
        auto localPawn = Object("DaytonHumanCharacter"), ai = Object("DaytonHumanAIController");
        Write(controller, melee::field::ControllerPawn, localPawn);
        Write(pawn, melee::field::PawnController, ai);
        // Provide a controlled ABI-compatible engine attitude function in the fixture.
        unsigned char stub[] = {0x48, 0xb8, 0,0,0,0,0,0,0,0, 0xff, 0xe0};
        auto target = reinterpret_cast<uintptr_t>(&FriendlyAttitude); std::memcpy(stub + 2, &target, sizeof(target));
        auto attitude = reinterpret_cast<void*>(base + melee::rva::Attitude);
        std::memcpy(attitude, stub, sizeof(stub));
        DWORD previous = 0; Check(VirtualProtect(attitude, sizeof(stub), PAGE_EXECUTE_READ, &previous) != 0, "attitude stub protection");
        FlushInstructionCache(GetCurrentProcess(), attitude, sizeof(stub));
        Check(SafeMultiplier(reinterpret_cast<void*>(component), false) == 1.0f, "friendly excluded despite other enabled");
        scopes[1] = 1; config.store(melee::Pack(true, rates, scopes));
        Check(SafeMultiplier(reinterpret_cast<void*>(component), false) == 2.0f, "friendly opted in");
        Check(attitudeController == reinterpret_cast<void*>(ai) && attitudeTarget == reinterpret_cast<void*>(localPawn), "attitude receiver/target ABI");
        auto pawnClass = Read<uintptr_t>(pawn, melee::field::UObjectClass);
        Write(pawn, melee::field::UObjectClass, Class("DaytonZombieCharacter"));
        Check(SafeMultiplier(reinterpret_cast<void*>(component), false) == 1.0f, "zombie exclusion");
        Write(pawn, melee::field::UObjectClass, pawnClass);
        Write(impl, melee::field::UObjectClass, Class("CommonSyncedAttackActionImpl_C"));
        Check(SafeMultiplier(reinterpret_cast<void*>(component), false) == 1.0f, "unhandled synced action left unchanged");
        Write(component, melee::field::ActionImplementation, uintptr_t{1});
        auto faultResult = SafeMultiplier(reinterpret_cast<void*>(component), false);
        if (faultResult != 1.0f || faults.load() != 1) std::fprintf(stderr, "fault result=%f faults=%llu latched=%d\n", faultResult, faults.load(), int(classificationFailed.load()));
        Check(faultResult == 1.0f && faults.load() == 1, "invalid pointer fails closed");
        config.store(0);
        Check(SafeMultiplier(reinterpret_cast<void*>(1), false) == 1.0f && faults.load() == 1, "disabled path avoids reads");
        for (int mask = 0; mask < 8; ++mask) {
            int flags[] = {mask & 1, mask & 2, mask & 4};
            for (int rate = melee::RateMinimum; rate <= melee::RateMaximum; ++rate) {
                int r[] = {rate, rate, rate, rate}; auto packed = melee::Pack(true, r, flags);
                for (int c = 0; c < melee::MaxCategories; ++c) for (int s = 0; s < melee::MaxScopes; ++s)
                    Check(melee::Multiplier(packed, static_cast<melee::Category>(c), static_cast<melee::Scope>(s)) ==
                        (flags[s] ? float(rate) / melee::RateNormal : 1.0f), "rate/scope matrix");
            }
        }
        rates[0] = 0; Check(melee::Pack(true, rates, scopes) == 0, "bad configuration rejected");
        Check(melee::ScaleDelta(0, 3) == 0 && melee::ScaleDelta(-1, 3) == -1, "nonpositive delta preserved");
        Check(std::isnan(melee::ScaleDelta(std::numeric_limits<float>::quiet_NaN(), 3)), "NaN preserved");
        VirtualFree(reinterpret_cast<void*>(base), 0, MEM_RELEASE);
        std::puts("PASS: 81888 rate/scope cases through 1000%; actual UObject classifier; action/animation parity; friendly attitude ABI; zombie exclusion; invalid reads; disable; unsupported actions.");
        return 0;
    } catch (const std::exception& e) { std::fprintf(stderr, "FAIL: %s\n", e.what()); return 1; }
}
