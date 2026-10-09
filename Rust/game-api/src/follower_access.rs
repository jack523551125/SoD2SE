//! Fixed-build follower access. Called only inside the owned engine-thread observer.
//! All UObject references are ephemeral; only validated values leave this adapter.
use crate::follower_state::{Identity, MAX_FOLLOWERS};
use serde::Deserialize;
use sod2se_abi::{BUSY, INTERNAL, INVALID, UNSUPPORTED};
use std::{cell::Cell, collections::BTreeMap, ffi::c_void, sync::OnceLock};
use windows_sys::Win32::System::{
    Diagnostics::Debug::ReadProcessMemory,
    Memory::{
        MEMORY_BASIC_INFORMATION, PAGE_EXECUTE, PAGE_EXECUTE_READ, PAGE_EXECUTE_READWRITE,
        PAGE_EXECUTE_WRITECOPY, VirtualQuery,
    },
    Threading::{GetCurrentProcess, GetCurrentThreadId},
};

// Original category registration covers world NPCs, not just saved followers.
// This is a reader budget, never a replacement for the native population cap.
const MAX_SPAWN_ENTRIES: usize = 4096;

#[derive(Deserialize)]
pub(crate) struct Function {
    pub rva: usize,
    pub guard: String,
}

#[cfg(test)]
#[path = "follower_access_tests.rs"]
mod activation_tests;

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn original_positioning_abi_keeps_collision_failures_pending_and_checks_actual_distance() {
        use std::sync::atomic::{AtomicUsize, Ordering};
        use windows_sys::Win32::System::Memory::{
            MEM_COMMIT, MEM_RELEASE, MEM_RESERVE, VirtualAlloc, VirtualFree,
        };
        static MODE: AtomicUsize = AtomicUsize::new(0);
        static CALLS: AtomicUsize = AtomicUsize::new(0);
        unsafe extern "system" fn location(
            actor: *mut c_void,
            out: *mut PlacementVector,
        ) -> *mut PlacementVector {
            unsafe { *out = *(actor as *const PlacementVector) };
            out
        }
        unsafe extern "system" fn rotation(
            _: *mut c_void,
            out: *mut PlacementVector,
        ) -> *mut PlacementVector {
            unsafe { *out = PlacementVector::default() };
            out
        }
        unsafe extern "system" fn teleport(
            actor: *mut c_void,
            destination: *const PlacementVector,
            _: *const PlacementVector,
        ) -> bool {
            CALLS.fetch_add(1, Ordering::SeqCst);
            match MODE.load(Ordering::SeqCst) {
                0 => false,
                1 => true, // Authored false confirmation: position did not change.
                _ => {
                    unsafe { *(actor as *mut PlacementVector) = *destination };
                    true
                }
            }
        }
        let page = unsafe {
            VirtualAlloc(
                std::ptr::null(),
                4096,
                MEM_COMMIT | MEM_RESERVE,
                PAGE_EXECUTE_READWRITE,
            )
        };
        assert!(!page.is_null());
        let base = page as usize;
        let mut input: Facts =
            serde_json::from_str(include_str!("../follower-bindings.json")).unwrap();
        for (name, offset, callback) in [
            ("actor_location", 128usize, location as *const () as usize),
            ("actor_rotation", 256, rotation as *const () as usize),
            ("teleport_character", 384, teleport as *const () as usize),
        ] {
            let mut code = vec![0x48, 0xb8];
            code.extend_from_slice(&(callback as u64).to_le_bytes());
            code.extend_from_slice(&[0xff, 0xe0, 0x90, 0x90, 0x90, 0x90]);
            unsafe {
                std::ptr::copy_nonoverlapping(code.as_ptr(), (base + offset) as *mut u8, code.len())
            };
            input.functions.insert(
                name.into(),
                Function {
                    rva: offset,
                    guard: code.iter().map(|b| format!("{b:02x}")).collect(),
                },
            );
        }
        let reader = Reader {
            base,
            facts: Box::leak(Box::new(input)),
            stage: Cell::new("test"),
            saved_mutation: Cell::new(false),
            category_activation: Cell::new(false),
        };
        let mut player = PlacementVector {
            x: 1000.0,
            ..PlacementVector::default()
        };
        let mut follower = PlacementVector {
            x: 10_000.0,
            ..PlacementVector::default()
        };
        let player_at = &mut player as *mut PlacementVector as usize;
        let follower_at = &mut follower as *mut PlacementVector as usize;
        for mode in [0, 1] {
            MODE.store(mode, Ordering::SeqCst);
            CALLS.store(0, Ordering::SeqCst);
            assert_eq!(reader.place_actor(follower_at, player_at), Ok(false));
            assert_eq!(
                CALLS.load(Ordering::SeqCst),
                4,
                "bounded collision attempts cannot become a forced placement"
            );
        }
        MODE.store(2, Ordering::SeqCst);
        CALLS.store(0, Ordering::SeqCst);
        assert_eq!(reader.place_actor(follower_at, player_at), Ok(true));
        assert_eq!(CALLS.load(Ordering::SeqCst), 1);
        assert!(player.near(&follower));
        assert_eq!(reader.place_actor(follower_at, player_at), Ok(true));
        assert_eq!(
            CALLS.load(Ordering::SeqCst),
            1,
            "already-near actors are not teleported again"
        );
        let mut invalid_player = PlacementVector {
            x: f32::NAN,
            ..PlacementVector::default()
        };
        assert_eq!(
            reader.place_actor(
                follower_at,
                &mut invalid_player as *mut PlacementVector as usize
            ),
            Err(BUSY)
        );
        assert_eq!(CALLS.load(Ordering::SeqCst), 1);
        assert_eq!(unsafe { VirtualFree(page, 0, MEM_RELEASE) }, 1);
    }
    #[test]
    fn unstreamed_character_is_not_an_invalid_actor_pointer() {
        let character = vec![0u8; 0x1000];
        let reader = Reader {
            base: 0,
            facts: facts().unwrap(),
            stage: Cell::new("test"),
            saved_mutation: Cell::new(false),
            category_activation: Cell::new(false),
        };
        assert_eq!(reader.actor(character.as_ptr() as usize), Ok(None));
    }
    #[test]
    fn record_restore_uses_original_add_then_role_abi_and_validates_both_sites_first() {
        use std::sync::atomic::{AtomicUsize, Ordering};
        use windows_sys::Win32::System::Memory::{
            MEM_COMMIT, MEM_RELEASE, MEM_RESERVE, VirtualAlloc, VirtualFree,
        };
        static CALL_ORDER: AtomicUsize = AtomicUsize::new(0);
        unsafe extern "system" fn add(manager: *mut c_void, character: *mut c_void, notify: u8) {
            assert_eq!(notify, 1);
            assert_eq!(CALL_ORDER.fetch_add(1, Ordering::SeqCst), 0);
            unsafe { *(manager as *mut usize) = character as usize };
        }
        unsafe extern "system" fn role(character: *mut c_void, value: u8) {
            assert_eq!(value, 3);
            assert_eq!(CALL_ORDER.fetch_add(1, Ordering::SeqCst), 1);
            unsafe { *(character as *mut u8) = value };
        }
        // Authored executable trampolines call authored spies, never game code.
        let page = unsafe {
            VirtualAlloc(
                std::ptr::null(),
                4096,
                MEM_COMMIT | MEM_RESERVE,
                PAGE_EXECUTE_READWRITE,
            )
        };
        assert!(!page.is_null());
        let base = page as usize;
        let mut input: Facts =
            serde_json::from_str(include_str!("../follower-bindings.json")).unwrap();
        for (name, offset, callback) in [
            ("manager_add", 128usize, add as *const () as usize),
            ("set_busy_state", 256usize, role as *const () as usize),
        ] {
            let mut code = vec![0x48, 0xb8];
            code.extend_from_slice(&(callback as u64).to_le_bytes());
            code.extend_from_slice(&[0xff, 0xe0, 0x90, 0x90, 0x90, 0x90]);
            unsafe {
                std::ptr::copy_nonoverlapping(code.as_ptr(), (base + offset) as *mut u8, code.len())
            };
            input.functions.insert(
                name.into(),
                Function {
                    rva: offset,
                    guard: code.iter().map(|b| format!("{b:02x}")).collect(),
                },
            );
        }
        let input = Box::leak(Box::new(input));
        let reader = Reader {
            base,
            facts: input,
            stage: Cell::new("test"),
            saved_mutation: Cell::new(false),
            category_activation: Cell::new(false),
        };
        let mut manager = 0usize;
        let mut character = 0u8;
        CALL_ORDER.store(0, Ordering::SeqCst);
        reader
            .enlist_record(
                &mut manager as *mut usize as usize,
                &mut character as *mut u8 as usize,
            )
            .unwrap();
        assert_eq!(CALL_ORDER.load(Ordering::SeqCst), 2);
        assert_eq!(manager, &mut character as *mut u8 as usize);
        assert_eq!(character, 3);
        unsafe { *((base + 256) as *mut u8) ^= 1 };
        CALL_ORDER.store(0, Ordering::SeqCst);
        assert_eq!(
            reader.enlist_record(
                &mut manager as *mut usize as usize,
                &mut character as *mut u8 as usize
            ),
            Err(UNSUPPORTED)
        );
        assert_eq!(
            CALL_ORDER.load(Ordering::SeqCst),
            0,
            "failed role guard must block the add call too"
        );
        assert_eq!(unsafe { VirtualFree(page, 0, MEM_RELEASE) }, 1);
    }

    #[test]
    fn bounded_identity_reader_accepts_original_zero_narrative_fields_but_not_default_record() {
        let mut globals = vec![0u8; 0x100];
        let mut character = vec![0u8; 0x500];
        let class = [0u8; 0x100];
        let mut objects = [0u8; 24];
        let mut input: Facts =
            serde_json::from_str(include_str!("../follower-bindings.json")).unwrap();
        input.object_data = 0x10;
        input.object_count = 0x18;
        input.classes.insert("character".into(), 0x40);
        globals[0x10..0x18].copy_from_slice(&(objects.as_ptr() as u64).to_le_bytes());
        globals[0x18..0x1c].copy_from_slice(&1i32.to_le_bytes());
        globals[0x40..0x48].copy_from_slice(&(class.as_ptr() as u64).to_le_bytes());
        character[0x10..0x18].copy_from_slice(&(class.as_ptr() as u64).to_le_bytes());
        objects[..8].copy_from_slice(&(character.as_ptr() as u64).to_le_bytes());
        let record = input.fields["record"];
        character[record..record + 4].copy_from_slice(&7i32.to_le_bytes());
        let reader = Reader {
            base: globals.as_ptr() as usize,
            facts: Box::leak(Box::new(input)),
            stage: Cell::new("test"),
            saved_mutation: Cell::new(false),
            category_activation: Cell::new(false),
        };
        assert_eq!(
            reader.identity(character.as_ptr() as usize),
            Ok(Identity {
                id: 7,
                narrative: 0,
                entity: 0
            })
        );
        character[record..record + 4].copy_from_slice(&(-1i32).to_le_bytes());
        assert_eq!(reader.identity(character.as_ptr() as usize), Err(INVALID));
    }

    // Authored process-local objects exercise the real bounded reader. They are
    // protocol fixtures, not substituted original-game inputs or live evidence.
    #[test]
    fn solo_host_driver_is_allowed_but_remote_sessions_and_replay_are_refused() {
        fn put(bytes: &mut [u8], offset: usize, value: u64) {
            bytes[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
        }
        let mut globals = vec![0u8; 0x100];
        let mut world = vec![0u8; 0x200];
        let mut driver = vec![0u8; 0x200];
        let class = vec![0u8; 0x100];
        let mut objects = vec![0u8; 24];
        let peers = [driver.as_ptr() as usize];
        let mut input: Facts =
            serde_json::from_str(include_str!("../follower-bindings.json")).unwrap();
        input.object_data = 0x10;
        input.object_count = 0x18;
        input.classes.insert("net_driver".into(), 0x40);
        put(&mut globals, 0x10, objects.as_ptr() as u64);
        globals[0x18..0x1c].copy_from_slice(&1i32.to_le_bytes());
        put(&mut globals, 0x40, class.as_ptr() as u64);
        put(&mut driver, 0x10, class.as_ptr() as u64);
        put(&mut objects, 0, driver.as_ptr() as u64);
        let input = Box::leak(Box::new(input));
        let reader = Reader {
            base: globals.as_ptr() as usize,
            facts: input,
            stage: Cell::new("test"),
            saved_mutation: Cell::new(false),
            category_activation: Cell::new(false),
        };
        let address = world.as_ptr() as usize;
        assert_eq!(reader.require_solo(address), Ok(()));
        put(
            &mut world,
            input.fields["net_driver"],
            driver.as_ptr() as u64,
        );
        assert_eq!(
            reader.require_solo(address),
            Ok(()),
            "a driver alone cannot reject solo play"
        );
        put(
            &mut driver,
            input.fields["server_connection"],
            peers.as_ptr() as u64,
        );
        assert_eq!(reader.require_solo(address), Err(UNSUPPORTED));
        assert_eq!(reader.stage(), "context.server-connection");
        put(&mut driver, input.fields["server_connection"], 0);
        let clients = input.fields["client_connections"];
        put(&mut driver, clients, peers.as_ptr() as u64);
        driver[clients + 8..clients + 12].copy_from_slice(&1i32.to_le_bytes());
        driver[clients + 12..clients + 16].copy_from_slice(&4i32.to_le_bytes());
        assert_eq!(reader.require_solo(address), Err(UNSUPPORTED));
        assert_eq!(reader.stage(), "context.remote-peers");
        driver[clients + 8..clients + 12].copy_from_slice(&0i32.to_le_bytes());
        assert_eq!(
            reader.require_solo(address),
            Ok(()),
            "retained empty capacity after peers leave is valid"
        );
        driver[clients + 12..clients + 16].copy_from_slice(&257i32.to_le_bytes());
        assert_eq!(reader.require_solo(address), Err(INVALID));
        driver[clients + 12..clients + 16].copy_from_slice(&4i32.to_le_bytes());
        put(
            &mut world,
            input.fields["demo_driver"],
            driver.as_ptr() as u64,
        );
        assert_eq!(reader.require_solo(address), Err(UNSUPPORTED));
        assert_eq!(reader.stage(), "context.replay");
        put(&mut world, input.fields["demo_driver"], 0);
        put(&mut driver, 0x10, 0);
        assert_eq!(reader.require_solo(address), Err(UNSUPPORTED));
        put(&mut driver, 0x10, class.as_ptr() as u64);
        put(&mut objects, 0, 0);
        assert_eq!(reader.require_solo(address), Err(BUSY));
    }
}
#[derive(Deserialize)]
pub(crate) struct Facts {
    pub schema: u32,
    pub target_sha256: String,
    pub functions: BTreeMap<String, Function>,
    pub classes: BTreeMap<String, usize>,
    pub thread_id: usize,
    pub thread_initialized: usize,
    pub player_global: usize,
    pub object_data: usize,
    pub object_count: usize,
    pub fields: BTreeMap<String, usize>,
}
pub(crate) fn facts() -> Result<&'static Facts, i32> {
    static FACTS: OnceLock<Result<Facts, i32>> = OnceLock::new();
    FACTS
        .get_or_init(|| {
            let facts: Facts = serde_json::from_str(include_str!("../follower-bindings.json"))
                .map_err(|_| INVALID)?;
            if facts.schema != 1 || facts.target_sha256 != crate::target().sha256 {
                return Err(UNSUPPORTED);
            }
            for name in [
                "tick",
                "save",
                "dismiss",
                "rpc",
                "validate_rpc",
                "allowed",
                "restriction",
                "manager_add",
                "set_busy_state",
                "record_set_transform",
                "component_transform",
                "set_saved_position_kind",
                "get_record_transform",
                "refresh_spawn_category",
                "world_self",
                "actor_world",
                "actor_location",
                "actor_rotation",
                "follow",
                "resolve_weak",
                "teleport_character",
            ] {
                let function = facts.functions.get(name).ok_or(INVALID)?;
                if function.rva == 0 || crate::decode(&function.guard)?.len() != 16 {
                    return Err(INVALID);
                }
            }
            Ok(facts)
        })
        .as_ref()
        .map_err(|code| *code)
}
pub(crate) fn read(address: usize, size: usize) -> Result<Vec<u8>, i32> {
    if address < 0x10000
        || size == 0
        || size > 4096
        || address
            .checked_add(size)
            .is_none_or(|end| end >= 0x800000000000)
    {
        return Err(INVALID);
    }
    let mut bytes = vec![0; size];
    let mut count = 0;
    if unsafe {
        ReadProcessMemory(
            GetCurrentProcess(),
            address as *const c_void,
            bytes.as_mut_ptr().cast(),
            size,
            &mut count,
        )
    } == 0
        || count != size
    {
        return Err(INTERNAL);
    }
    Ok(bytes)
}
pub(crate) struct Reader {
    pub base: usize,
    facts: &'static Facts,
    stage: Cell<&'static str>,
    saved_mutation: Cell<bool>,
    category_activation: Cell<bool>,
}
pub(crate) struct Context {
    pub world: usize,
    pub controller: usize,
    pub pawn: usize,
    pub dialogue: usize,
    pub community: usize,
    pub game: usize,
    pub manager: usize,
    pub key: String,
    pub controlled: Identity,
    pub vanilla_follower: i32,
}
#[repr(C, align(16))]
#[derive(Clone, Copy, Default)]
struct PlacementVector {
    x: f32,
    y: f32,
    z: f32,
    padding: f32,
}
#[repr(C, align(16))]
#[derive(Clone, Copy, Debug, Default, PartialEq)]
struct SavedTransform {
    rotation: [f32; 4],
    translation: [f32; 4],
    scale: [f32; 4],
}
impl SavedTransform {
    fn valid(&self) -> bool {
        self.rotation.iter().all(|v| v.is_finite())
            && (self.rotation.iter().map(|v| v * v).sum::<f32>() - 1.0).abs() < 0.1
            && self.translation[..3]
                .iter()
                .all(|v| v.is_finite() && v.abs() < 100_000_000.0)
            && self.scale[..3]
                .iter()
                .all(|v| v.is_finite() && v.abs() > 0.001 && v.abs() < 1000.0)
    }
    fn position(&self) -> PlacementVector {
        PlacementVector {
            x: self.translation[0],
            y: self.translation[1],
            z: self.translation[2],
            padding: 0.0,
        }
    }
}
impl PlacementVector {
    fn valid(&self) -> bool {
        [self.x, self.y, self.z]
            .iter()
            .all(|v| v.is_finite() && v.abs() < 100_000_000.0)
    }
    fn near(&self, other: &Self) -> bool {
        let x = self.x - other.x;
        let y = self.y - other.y;
        x * x + y * y <= 450.0 * 450.0 && (self.z - other.z).abs() <= 150.0
    }
}
impl Reader {
    pub fn new(base: usize) -> Result<Self, i32> {
        Ok(Self {
            base,
            facts: facts()?,
            stage: Cell::new("bindings"),
            saved_mutation: Cell::new(false),
            category_activation: Cell::new(false),
        })
    }
    pub fn stage(&self) -> &'static str {
        self.stage.get()
    }
    pub fn saved_mutated(&self) -> bool {
        self.saved_mutation.get()
    }
    pub fn activation_called(&self) -> bool {
        self.category_activation.get()
    }
    pub fn checkpoint(&self, stage: &'static str) {
        self.stage.set(stage);
    }
    pub fn field(&self, name: &str) -> Result<usize, i32> {
        self.facts.fields.get(name).copied().ok_or(INVALID)
    }
    pub fn pointer(&self, at: usize) -> Result<usize, i32> {
        Ok(usize::from_le_bytes(
            read(at, 8)?.try_into().map_err(|_| INVALID)?,
        ))
    }
    pub fn integer(&self, at: usize) -> Result<i32, i32> {
        Ok(i32::from_le_bytes(
            read(at, 4)?.try_into().map_err(|_| INVALID)?,
        ))
    }
    pub fn byte(&self, at: usize) -> Result<u8, i32> {
        Ok(read(at, 1)?[0])
    }
    pub fn engine_thread(&self) -> Result<(), i32> {
        if self.integer(self.base + self.facts.thread_initialized)? == 0
            || self.integer(self.base + self.facts.thread_id)? as u32
                != unsafe { GetCurrentThreadId() }
        {
            return Err(UNSUPPORTED);
        }
        Ok(())
    }
    pub fn healthy(&self, object: usize) -> Result<(), i32> {
        self.healthy_object(object, false)
    }
    fn healthy_object(&self, object: usize, default_object: bool) -> Result<(), i32> {
        let is_default = self.integer(object.checked_add(8).ok_or(INVALID)?)? as u32 & 0x10 != 0;
        if is_default != default_object {
            return Err(BUSY);
        }
        let index = self.integer(object.checked_add(12).ok_or(INVALID)?)?;
        let count = self.integer(self.base + self.facts.object_count)?;
        if !(0..=2_000_000).contains(&count) || index < 0 || index >= count {
            return Err(BUSY);
        }
        let data = self.pointer(self.base + self.facts.object_data)?;
        let item = data.checked_add(index as usize * 24).ok_or(INVALID)?;
        if self.pointer(item)? != object || (self.integer(item + 8)? as u32 & 0x30000000) != 0 {
            return Err(BUSY);
        }
        Ok(())
    }
    pub fn require_class(&self, object: usize, name: &str) -> Result<(), i32> {
        self.healthy(object)?;
        let expected =
            self.pointer(self.base + self.facts.classes.get(name).copied().ok_or(INVALID)?)?;
        if expected == 0 {
            return Err(BUSY);
        }
        let mut class = self.pointer(object + self.field("object_class")?)?;
        for _ in 0..32 {
            if class == expected {
                return Ok(());
            }
            if class == 0 {
                break;
            }
            class = self.pointer(class + self.field("class_parent")?)?;
        }
        Err(UNSUPPORTED)
    }
    pub fn identity(&self, character: usize) -> Result<Identity, i32> {
        self.require_class(character, "character")?;
        let record = character + self.field("record")?;
        let values = read(record, 24)?;
        let identity = Identity {
            id: i32::from_le_bytes(values[0..4].try_into().map_err(|_| INVALID)?),
            narrative: u64::from_le_bytes(values[8..16].try_into().map_err(|_| INVALID)?),
            entity: u64::from_le_bytes(values[16..24].try_into().map_err(|_| INVALID)?),
        };
        identity.validate()?;
        Ok(identity)
    }
    fn selected_game(&self, manager: usize) -> Result<usize, i32> {
        self.stage.set("save-manager.class");
        self.require_class(manager, "save_manager")?;
        self.stage.set("save-manager.mode-map");
        let slots = self.integer(manager + 0x158)?;
        let free = self.integer(manager + 0x184)?;
        if !(0..=64).contains(&slots) || free < 0 || free >= slots {
            return Err(BUSY);
        }
        let inline = manager + 0x188;
        let bucket = self.pointer(inline + 8)?;
        let mut index = self.integer(if bucket == 0 { inline } else { bucket })?;
        let entries = self.pointer(manager + 0x150)?;
        let mut visited = 0u64;
        while index != -1 {
            if index < 0 || index >= slots || visited & (1u64 << index) != 0 {
                return Err(INVALID);
            }
            visited |= 1u64 << index;
            let entry = entries + index as usize * 48;
            if self.byte(entry)? == 0 {
                let slot = self.integer(manager + 0x1b8)?;
                self.stage.set("save-manager.selected-slot");
                let (games, count) = self.array(entry + 8, 64)?;
                if slot < 0 || slot as usize >= count {
                    return Err(BUSY);
                }
                let game = self.pointer(games + slot as usize * 8)?;
                self.stage.set("save-game.class");
                self.require_class(game, "game")?;
                return Ok(game);
            }
            index = self.integer(entry + 0x28)?;
        }
        Err(BUSY)
    }
    pub fn array(&self, at: usize, max: usize) -> Result<(usize, usize), i32> {
        let values = read(at, 16)?;
        Self::array_header(&values, max)
    }
    fn array_header(values: &[u8], max: usize) -> Result<(usize, usize), i32> {
        if values.len() != 16 {
            return Err(INVALID);
        }
        let ptr = usize::from_le_bytes(values[0..8].try_into().map_err(|_| INVALID)?);
        let count = i32::from_le_bytes(values[8..12].try_into().map_err(|_| INVALID)?);
        let capacity = i32::from_le_bytes(values[12..16].try_into().map_err(|_| INVALID)?);
        if count < 0 || capacity < count || capacity as usize > max || (count > 0 && ptr < 0x10000)
        {
            return Err(INVALID);
        }
        Ok((ptr, count as usize))
    }
    fn require_solo(&self, world: usize) -> Result<(), i32> {
        self.stage.set("context.replay");
        if self.pointer(world + self.field("demo_driver")?)? != 0 {
            return Err(UNSUPPORTED);
        }
        self.stage.set("context.network-driver");
        let driver = self.pointer(world + self.field("net_driver")?)?;
        if driver == 0 {
            return Ok(());
        }
        self.require_class(driver, "net_driver")?;
        self.stage.set("context.server-connection");
        if self.pointer(driver + self.field("server_connection")?)? != 0 {
            return Err(UNSUPPORTED);
        }
        self.stage.set("context.remote-peers");
        let (_, count) = self.array(driver + self.field("client_connections")?, 256)?;
        if count != 0 {
            return Err(UNSUPPORTED);
        }
        Ok(())
    }
    pub fn context(&self, world: usize) -> Result<Context, i32> {
        self.stage.set("context.engine-thread");
        self.engine_thread()?;
        self.stage.set("context.world");
        self.require_class(world, "world")?;
        // A listening driver with no server connection or remote peers still
        // belongs to the local player. Reject actual clients/peers and replay,
        // rather than suspending every world which allocated a driver.
        self.require_solo(world)?;
        let player = self.pointer(self.base + self.facts.player_global)?;
        self.stage.set("context.local-player");
        self.require_class(player, "player")?;
        self.stage.set("context.controller");
        let controller = self.pointer(player + self.field("controller")?)?;
        self.require_class(controller, "controller")?;
        self.stage.set("context.level");
        let level = self.pointer(controller + self.field("outer")?)?;
        self.require_class(level, "level")?;
        if self.pointer(level + self.field("level_world")?)? != world {
            return Err(BUSY);
        }
        self.stage.set("context.game-instance");
        let instance = self.pointer(world + self.field("world_instance")?)?;
        self.require_class(instance, "instance")?;
        self.stage.set("context.loading-screen");
        if self.pointer(instance + self.field("loading_screen")?)? != 0 {
            return Err(BUSY);
        }
        self.stage.set("context.pawn");
        let pawn = self.pointer(controller + self.field("pawn")?)?;
        self.require_class(pawn, "pawn")?;
        self.stage.set("context.character-component");
        let component = self.pointer(pawn + self.field("component")?)?;
        self.require_class(component, "component")?;
        self.stage.set("context.controlled-identity");
        let character = self.pointer(component + self.field("character")?)?;
        let controlled = self.identity(character)?;
        if self.byte(character + self.field("record")? + self.field("dead")?)? != 0 {
            return Err(BUSY);
        }
        let game = self.selected_game(self.pointer(instance + self.field("save_manager")?)?)?;
        self.stage.set("context.community-records");
        // A loaded pointer alone does not bind a world to the selected community.
        // Require the controlled survivor's full identity in this game's record.
        let (members, count) = self.array(game + 0x1c8, MAX_FOLLOWERS)?;
        let mut matched = false;
        for index in 0..count {
            let record = read(members + index * 0x1c0, 24)?;
            if i32::from_le_bytes(record[0..4].try_into().map_err(|_| INVALID)?) == controlled.id
                && u64::from_le_bytes(record[8..16].try_into().map_err(|_| INVALID)?)
                    == controlled.narrative
                && u64::from_le_bytes(record[16..24].try_into().map_err(|_| INVALID)?)
                    == controlled.entity
            {
                matched = true;
                break;
            }
        }
        if !matched {
            return Err(BUSY);
        }
        self.stage.set("context.community-id");
        let guid = read(game + self.field("game_id")?, 16)?;
        if guid.iter().all(|b| *b == 0) {
            return Err(BUSY);
        }
        let key = guid.iter().map(|b| format!("{b:02x}")).collect();
        self.stage.set("context.follower-manager");
        let manager = self.pointer(controller + self.field("followers")?)?;
        self.require_class(manager, "followers")?;
        self.stage.set("context.dialogue");
        let dialogue = self.pointer(controller + self.field("dialogue")?)?;
        self.require_class(dialogue, "dialogue")?;
        self.stage.set("context.community-component");
        let community = self.pointer(controller + self.field("community_component")?)?;
        self.require_class(community, "community")?;
        Ok(Context {
            world,
            controller,
            pawn,
            dialogue,
            community,
            game,
            manager,
            key,
            controlled,
            vanilla_follower: self.integer(community + self.field("last_follower_id")?)?,
        })
    }
    pub fn current_world(&self) -> Result<usize, i32> {
        self.stage.set("current-world.engine-thread");
        self.engine_thread()?;
        self.stage.set("current-world.local-player");
        let player = self.pointer(self.base + self.facts.player_global)?;
        self.require_class(player, "player")?;
        self.stage.set("current-world.controller");
        let controller = self.pointer(player + self.field("controller")?)?;
        self.require_class(controller, "controller")?;
        self.stage.set("current-world.level");
        let level = self.pointer(controller + self.field("outer")?)?;
        self.require_class(level, "level")?;
        self.pointer(level + self.field("level_world")?)
    }
    pub fn roster(&self, context: &Context) -> Result<Vec<Identity>, i32> {
        self.stage.set("roster.array");
        let (data, count) = self.array(context.manager + self.field("array")?, MAX_FOLLOWERS)?;
        let mut result = Vec::new();
        for index in 0..count {
            self.stage.set("roster.character");
            let character = self.pointer(data + index * 8)?;
            self.require_class(character, "character")?;
            if self.byte(character + self.field("busy_state")?)? == 3 {
                self.stage.set("roster.identity");
                let identity = self.identity(character)?;
                if self.byte(character + self.field("record")? + self.field("dead")?)? == 0 {
                    result.push(identity);
                }
            }
        }
        Ok(result)
    }
    fn matching(&self, character: usize, target: &Identity) -> bool {
        self.identity(character)
            .is_ok_and(|identity| identity == *target)
    }
    fn actor(&self, character: usize) -> Result<Option<usize>, i32> {
        let component = self.pointer(character + self.field("character_component")?)?;
        if component == 0 {
            return Ok(None);
        }
        self.require_class(component, "component")?;
        let pawn = self.pointer(component + self.field("component_owner")?)?;
        if pawn == 0 {
            return Ok(None);
        }
        self.require_class(pawn, "pawn")?;
        if self.pointer(pawn + self.field("component")?)? != component
            || self.pointer(component + self.field("character")?)? != character
        {
            return Err(BUSY);
        }
        Ok(Some(pawn))
    }
    fn in_world(&self, pawn: usize, world: usize) -> Result<bool, i32> {
        let level = self.pointer(pawn + self.field("outer")?)?;
        self.require_class(level, "level")?;
        Ok(self.pointer(level + self.field("level_world")?)? == world)
    }
    pub fn present_roster(
        &self,
        context: &Context,
        enlisted: &[Identity],
    ) -> Result<Vec<Identity>, i32> {
        let (data, count) = self.array(context.manager + self.field("array")?, MAX_FOLLOWERS)?;
        let mut present = Vec::new();
        for index in 0..count {
            let character = self.pointer(data + index * 8)?;
            if let Ok(identity) = self.identity(character)
                && enlisted.contains(&identity)
                && let Ok(Some(pawn)) = self.actor(character)
                && self.in_world(pawn, context.world).unwrap_or(false)
            {
                present.push(identity);
            }
        }
        Ok(present)
    }
    pub fn bring_near(
        &self,
        context: &Context,
        target: &Identity,
        character: usize,
    ) -> Result<bool, i32> {
        self.checkpoint("placement.actor");
        self.engine_thread()?;
        if !self.matching(character, target)
            || self.byte(character + self.field("busy_state")?)? != 3
        {
            return Err(BUSY);
        }
        if self.byte(character + self.field("record")? + self.field("dead")?)? != 0 {
            return Err(sod2se_abi::NOT_FOUND);
        }
        let Some(pawn) = self.actor(character)? else {
            return Ok(false);
        };
        if pawn == context.pawn || !self.in_world(pawn, context.world)? {
            return Err(BUSY);
        }
        self.checkpoint("placement.follow-controller");
        let ai = self.pointer(pawn + self.field("actor_controller")?)?;
        if ai == 0 {
            return Ok(false);
        }
        self.require_class(ai, "ai_controller")?;
        if self.pointer(ai + self.field("pawn")?)? != pawn {
            return Err(BUSY);
        }
        for actor in [pawn, context.pawn] {
            let root = self.pointer(actor + self.field("actor_root")?)?;
            if root == 0 {
                return Ok(false);
            }
            self.healthy(root)?;
        }
        self.checkpoint("placement.context");
        self.require_solo(context.world)?;
        if self.current_world()? != context.world
            || self.pointer(context.controller + self.field("pawn")?)? != context.pawn
        {
            return Err(BUSY);
        }
        self.require_class(context.game, "game")?;
        let key: String = read(context.game + self.field("game_id")?, 16)?
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect();
        if key != context.key {
            return Err(sod2se_abi::STALE);
        }
        if !self.roster(context)?.contains(target) {
            return Err(BUSY);
        }
        type Follow = unsafe extern "system" fn(*mut c_void, *mut c_void, f32, u8);
        type Resolve = unsafe extern "system" fn(*const c_void) -> *mut c_void;
        let follow: Follow = unsafe { std::mem::transmute(self.function("follow")?) };
        let resolve: Resolve = unsafe { std::mem::transmute(self.function("resolve_weak")?) };
        // Check all positioning sites before changing the follow target.
        for name in ["actor_location", "actor_rotation", "teleport_character"] {
            self.function(name)?;
        }
        self.checkpoint("placement.follow-target");
        unsafe { follow(ai as *mut c_void, context.pawn as *mut c_void, 0.0, 1) };
        self.healthy(pawn)?;
        self.healthy(ai)?;
        self.healthy(context.pawn)?;
        if self.current_world()? != context.world
            || self.pointer(context.controller + self.field("pawn")?)? != context.pawn
            || !self.matching(character, target)
        {
            return Err(BUSY);
        }
        self.checkpoint("placement.near-player");
        let near = self.place_actor(pawn, context.pawn)?;
        let attached = unsafe { resolve((ai + self.field("ai_follow_target")?) as *const c_void) }
            as usize
            == context.pawn;
        Ok(near && attached)
    }
    fn place_actor(&self, pawn: usize, player: usize) -> Result<bool, i32> {
        type Get =
            unsafe extern "system" fn(*mut c_void, *mut PlacementVector) -> *mut PlacementVector;
        type Teleport = unsafe extern "system" fn(
            *mut c_void,
            *const PlacementVector,
            *const PlacementVector,
        ) -> bool;
        let get: Get = unsafe { std::mem::transmute(self.function("actor_location")?) };
        let rotation: Get = unsafe { std::mem::transmute(self.function("actor_rotation")?) };
        let teleport: Teleport =
            unsafe { std::mem::transmute(self.function("teleport_character")?) };
        let mut position = PlacementVector::default();
        let mut current = PlacementVector::default();
        let mut heading = PlacementVector::default();
        unsafe {
            get(player as *mut c_void, &mut position);
            get(pawn as *mut c_void, &mut current);
        };
        if !position.valid() || !current.valid() {
            return Err(BUSY);
        }
        if position.near(&current) {
            return Ok(true);
        }
        unsafe { rotation(player as *mut c_void, &mut heading) };
        if !heading.valid() {
            return Err(BUSY);
        }
        // Original collision checks remain enabled. Failure never forces a
        // location or clears the restoration queue. At most four attempts.
        for (x, y) in [(200.0, 0.0), (-200.0, 0.0), (0.0, 200.0), (0.0, -200.0)] {
            let destination = PlacementVector {
                x: position.x + x,
                y: position.y + y,
                ..position
            };
            if unsafe { teleport(pawn as *mut c_void, &destination, &heading) } {
                unsafe { get(pawn as *mut c_void, &mut current) };
                if current.valid() && position.near(&current) {
                    return Ok(true);
                }
            }
        }
        Ok(false)
    }
    fn community_member(&self, context: &Context, character: usize) -> Result<bool, i32> {
        let enclave = self.pointer(context.community + self.field("enclave")?)?;
        self.require_class(enclave, "characters")?;
        let (data, count) = self.array(enclave + self.field("characters_array")?, MAX_FOLLOWERS)?;
        for index in 0..count {
            if self.pointer(data + index * 8)? == character {
                return Ok(true);
            }
        }
        Ok(false)
    }
    fn enlist_record(&self, manager: usize, character: usize) -> Result<(), i32> {
        type Add = unsafe extern "system" fn(*mut c_void, *mut c_void, u8);
        type Role = unsafe extern "system" fn(*mut c_void, u8);
        // Validate both sites before the first original gameplay call.
        let add: Add = unsafe { std::mem::transmute(self.function("manager_add")?) };
        let role: Role = unsafe { std::mem::transmute(self.function("set_busy_state")?) };
        unsafe { add(manager as *mut c_void, character as *mut c_void, 1) };
        unsafe { role(character as *mut c_void, 3) };
        Ok(())
    }
    fn saved_registration(
        &self,
        context: &Context,
        target: &Identity,
        character: usize,
    ) -> Result<bool, i32> {
        self.require_class(context.manager, "followers")?;
        let (data, count) = self.array(context.manager + self.field("array")?, MAX_FOLLOWERS)?;
        let mut matches = 0;
        for index in 0..count {
            let member = self.pointer(data + index * 8)?;
            let identity = self.identity(member)?;
            if identity == *target {
                if member != character {
                    return Err(sod2se_abi::STALE);
                }
                matches += 1;
            }
        }
        if matches > 1 {
            return Err(INVALID);
        }
        Ok(matches == 1)
    }
    fn player_saved_transform(&self, context: &Context) -> Result<SavedTransform, i32> {
        type Get =
            unsafe extern "system" fn(*mut c_void, *mut SavedTransform) -> *mut SavedTransform;
        let get: Get = unsafe { std::mem::transmute(self.function("component_transform")?) };
        self.checkpoint("restore.saved-player-transform");
        self.require_class(context.pawn, "pawn")?;
        let root = self.pointer(context.pawn + self.field("actor_root")?)?;
        self.require_class(root, "scene_component")?;
        if self.pointer(root + self.field("component_owner")?)? != context.pawn {
            return Err(BUSY);
        }
        let mut result = SavedTransform::default();
        if !std::ptr::eq(unsafe { get(root as *mut c_void, &mut result) }, &result)
            || !result.valid()
        {
            return Err(BUSY);
        }
        // A bounded nearby request leaves collision/ground selection to the
        // original spawner. Preserve the current root's rotation and scale.
        result.translation[0] += 200.0;
        if !result.valid() {
            return Err(BUSY);
        }
        Ok(result)
    }
    fn enlist_saved_record(
        &self,
        manager: usize,
        character: usize,
        transform: &SavedTransform,
        post_add_validate: impl FnOnce() -> Result<(), i32>,
    ) -> Result<(), i32> {
        type Set = unsafe extern "system" fn(*mut c_void, *const SavedTransform);
        type Byte = unsafe extern "system" fn(*mut c_void, u8);
        type Add = unsafe extern "system" fn(*mut c_void, *mut c_void, u8);
        type Get =
            unsafe extern "system" fn(*mut c_void, *mut SavedTransform) -> *mut SavedTransform;
        // Original LastFollowerID restoration: request position, request its
        // saved-location kind, enroll, then set RecruitedFollower BusyState.
        // Validate every site before the first record mutation.
        let set: Set = unsafe { std::mem::transmute(self.function("record_set_transform")?) };
        let kind: Byte = unsafe { std::mem::transmute(self.function("set_saved_position_kind")?) };
        let add: Add = unsafe { std::mem::transmute(self.function("manager_add")?) };
        let busy: Byte = unsafe { std::mem::transmute(self.function("set_busy_state")?) };
        let get: Get = unsafe { std::mem::transmute(self.function("get_record_transform")?) };
        if !transform.valid() {
            return Err(BUSY);
        }
        self.saved_mutation.set(true);
        unsafe {
            set(character as *mut c_void, transform);
            kind(character as *mut c_void, 2);
            add(manager as *mut c_void, character as *mut c_void, 1);
        }
        post_add_validate()?;
        unsafe { busy(character as *mut c_void, 3) };
        let mut observed = SavedTransform::default();
        if !std::ptr::eq(
            unsafe { get(character as *mut c_void, &mut observed) },
            &observed,
        ) || !observed.valid()
            || self.byte(character + self.field("busy_state")?)? != 3
        {
            return Err(BUSY);
        }
        // BusyState's original E22 transition may replace the request with
        // the enclave pose. Reapply only the original spatial pair once, after
        // that protected transition; do not enroll or change BusyState again.
        if !observed.position().near(&transform.position()) {
            unsafe {
                set(character as *mut c_void, transform);
                kind(character as *mut c_void, 2);
            }
            if !std::ptr::eq(
                unsafe { get(character as *mut c_void, &mut observed) },
                &observed,
            ) || !observed.valid()
                || !observed.position().near(&transform.position())
            {
                return Err(BUSY);
            }
        }
        Ok(())
    }
    fn restore_saved_community(
        &self,
        context: &Context,
        target: &Identity,
        character: usize,
        allow_activation: bool,
    ) -> Result<bool, i32> {
        self.checkpoint("restore.saved-community");
        if target == &context.controlled
            || !self.matching(character, target)
            || !self.community_member(context, character)?
        {
            return Err(BUSY);
        }
        if self.byte(character + self.field("record")? + self.field("dead")?)? != 0 {
            return Err(sod2se_abi::NOT_FOUND);
        }
        let busy = self.byte(character + self.field("busy_state")?)?;
        if ![0, 3].contains(&busy) {
            self.checkpoint("restore.saved-busy");
            return Ok(false);
        }
        self.revalidate(context)?;
        let actor = self.actor(character)?;
        if let Some(pawn) = actor {
            if !self.in_world(pawn, context.world)? {
                self.checkpoint("resume.old-world-actor");
                return Ok(false);
            }
        } else if self.pointer(character + self.field("character_component")?)? != 0 {
            self.checkpoint("resume.component-waiting");
            return Ok(false);
        }
        let registered = self.saved_registration(context, target, character)?;
        if !allow_activation {
            self.checkpoint("restore.saved-observing");
            return Ok(false);
        }
        // Keep task/busy/death constraints. The two code-3 results are the
        // new-recruit distance gates, not eligibility for an existing saved
        // follower. Code 1 is only a proven existing pointer registration.
        type Check = unsafe extern "system" fn(*mut c_void, *mut c_void) -> u8;
        let allowed: Check = unsafe { std::mem::transmute(self.function("allowed")?) };
        let restriction: Check = unsafe { std::mem::transmute(self.function("restriction")?) };
        let allowed_code =
            unsafe { allowed(context.pawn as *mut c_void, character as *mut c_void) };
        if ![0, 3].contains(&allowed_code) {
            self.checkpoint(match allowed_code {
                1 => "restore.saved-allowed-1",
                2 => "restore.saved-allowed-2",
                4 => "restore.saved-allowed-4",
                5 => "restore.saved-allowed-5",
                6 => "restore.saved-allowed-6",
                7 => "restore.saved-allowed-7",
                8 => "restore.saved-allowed-8",
                9 => "restore.saved-allowed-9",
                _ => "restore.saved-allowed-unknown",
            });
            return Ok(false);
        }
        let restriction_code =
            unsafe { restriction(context.pawn as *mut c_void, character as *mut c_void) };
        if ![0, 1, 3].contains(&restriction_code) || (restriction_code == 1) != registered {
            self.checkpoint(match restriction_code {
                1 => "restore.saved-registration-mismatch",
                2 => "restore.saved-restriction-2",
                4 => "restore.saved-restriction-4",
                _ => "restore.saved-restriction-mismatch",
            });
            return Ok(false);
        }
        let desired = self.player_saved_transform(context)?;
        self.revalidate(context)?;
        if !self.matching(character, target)
            || !self.community_member(context, character)?
            || self.byte(character + self.field("busy_state")?)? != busy
            || self.byte(character + self.field("record")? + self.field("dead")?)? != 0
            || self.saved_registration(context, target, character)? != registered
            || self.actor(character)? != actor
        {
            return Err(BUSY);
        }
        self.checkpoint("restore.saved-original-record");
        self.enlist_saved_record(context.manager, character, &desired, || {
            self.revalidate(context)?;
            if !self.matching(character, target)
                || !self.community_member(context, character)?
                || self.byte(character + self.field("record")? + self.field("dead")?)? != 0
                || ![0, 3].contains(&self.byte(character + self.field("busy_state")?)?)
                || !self.saved_registration(context, target, character)?
            {
                return Err(BUSY);
            }
            let status = unsafe { allowed(context.pawn as *mut c_void, character as *mut c_void) };
            if ![0, 3].contains(&status) {
                return Err(BUSY);
            }
            Ok(())
        })?;
        self.revalidate(context)?;
        if !self.saved_registration(context, target, character)? {
            return Err(BUSY);
        }
        self.checkpoint("saved-original-record-submitted");
        if actor.is_none()
            && let Some(list) = self.owned_spawn_list(context)?
        {
            self.activate_record(list, context.world, target, character, || {
                self.revalidate(context)?;
                if self.owned_spawn_list(context)? != Some(list)
                    || !self.community_member(context, character)?
                    || self.byte(character + self.field("busy_state")?)? != 3
                    || self.byte(character + self.field("record")? + self.field("dead")?)? != 0
                    || self.pointer(character + self.field("character_component")?)? != 0
                {
                    return Err(BUSY);
                }
                Ok(())
            })?;
        }
        Ok(true)
    }
    fn revalidate(&self, previous: &Context) -> Result<(), i32> {
        let current = self.context(previous.world)?;
        if current.key != previous.key {
            return Err(sod2se_abi::STALE);
        }
        if current.controller != previous.controller
            || current.pawn != previous.pawn
            || current.manager != previous.manager
            || current.community != previous.community
            || current.game != previous.game
            || current.controlled != previous.controlled
        {
            return Err(BUSY);
        }
        Ok(())
    }
    fn owned_spawn_list(&self, context: &Context) -> Result<Option<usize>, i32> {
        self.checkpoint("resume.spawn-world");
        self.require_class(context.world, "world")?;
        self.require_class(
            self.pointer(context.world + self.field("world_mode")?)?,
            "game_mode",
        )?;
        type World = unsafe extern "system" fn(*mut c_void) -> *mut c_void;
        let method = self.function("world_self")?;
        let vtable = self.pointer(context.world)?;
        if self.pointer(vtable + self.field("get_world_slot")?)? != method {
            return Err(UNSUPPORTED);
        }
        let get_world: World = unsafe { std::mem::transmute(method) };
        if unsafe { get_world(context.world as *mut c_void) } as usize != context.world {
            return Err(BUSY);
        }
        self.checkpoint("resume.spawn-list");
        let enclave = self.pointer(context.community + self.field("enclave")?)?;
        self.require_class(enclave, "characters")?;
        let list = self.pointer(enclave + self.field("enclave_spawn_list")?)?;
        if list == 0 {
            return Ok(None);
        }
        self.require_class(list, "spawn_list")?;
        // The list's +0x38 is category configuration, not its world owner.
        // Its actual UObject Outer is the original proximity-manager Actor.
        let manager = self.pointer(list + self.field("outer")?)?;
        self.require_class(manager, "spawn_manager")?;
        if !self.in_world(manager, context.world)? {
            return Err(sod2se_abi::STALE);
        }
        let actor_method = self.function("actor_world")?;
        let actor_vtable = self.pointer(manager)?;
        if self.pointer(actor_vtable + self.field("get_world_slot")?)? != actor_method {
            return Err(UNSUPPORTED);
        }
        let get_actor_world: World = unsafe { std::mem::transmute(actor_method) };
        if unsafe { get_actor_world(manager as *mut c_void) } as usize != context.world {
            return Err(sod2se_abi::STALE);
        }
        Ok(Some(list))
    }
    fn category_class(&self, category: usize) -> Result<(), i32> {
        self.require_class(category, "uclass")?;
        let expected = self.pointer(self.base + self.facts.classes["spawn_category"])?;
        if expected == 0 {
            return Err(BUSY);
        }
        let mut parent = category;
        for _ in 0..32 {
            if parent == expected {
                return Ok(());
            }
            if parent == 0 {
                break;
            }
            self.require_class(parent, "uclass")?;
            parent = self.pointer(parent + self.field("class_parent")?)?;
        }
        Err(UNSUPPORTED)
    }
    fn registered_category(&self, manager: usize, list: usize) -> Result<Option<usize>, i32> {
        self.checkpoint("resume.category-registration");
        self.require_class(manager, "spawn_manager")?;
        let header = manager + self.field("spawn_categories")?;
        let before = read(header, 16)?;
        let (data, count) = Self::array_header(&before, MAX_SPAWN_ENTRIES)?;
        let stride = self.field("spawn_category_stride")?;
        let key_offset = self.field("spawn_category_class")?;
        let list_offset = self.field("spawn_category_list")?;
        let mut found = None;
        for index in 0..count {
            let category = self.pointer(data + index * stride + key_offset)?;
            // The original lookup casts every key that it visits. Validate
            // those keys too; unlike unrelated spawn-entry characters, the
            // native wrapper will dereference their class ancestry.
            if category != 0 {
                self.category_class(category)?;
            }
            if self.pointer(data + index * stride + list_offset)? == list {
                if found.is_some() {
                    return Err(INVALID);
                }
                if category == 0 {
                    return Err(INVALID);
                }
                let payload =
                    self.pointer(data + index * stride + self.field("spawn_category_payload")?)?;
                self.require_class(payload, "spawn_payload")?;
                if self.pointer(payload + self.field("outer")?)? != manager {
                    return Err(sod2se_abi::STALE);
                }
                let default = self.pointer(category + self.field("spawn_category_default")?)?;
                self.healthy_object(default, true)?;
                if self.pointer(default + self.field("object_class")?)? != category
                    || self.pointer(list + self.field("spawn_list_category")?)? != default
                {
                    return Err(INVALID);
                }
                found = Some(category);
            }
        }
        if let Some(category) = found {
            let mut matches = 0;
            for index in 0..count {
                if self.pointer(data + index * stride + key_offset)? == category {
                    matches += 1;
                }
            }
            if matches != 1 {
                return Err(INVALID);
            }
        }
        if read(header, 16)? != before {
            return Err(BUSY);
        }
        Ok(found)
    }
    fn tracked_actor(&self, list: usize, character: usize, pawn: usize) -> Result<bool, i32> {
        let entries_header = list + self.field("spawn_entries")?;
        let before = read(entries_header, 16)?;
        let (data, count) = Self::array_header(&before, MAX_SPAWN_ENTRIES)?;
        let stride = self.field("spawn_entry_stride")?;
        let offset = self.field("spawn_entry_character")?;
        let mut matched = None;
        for index in 0..count {
            if self.pointer(data + index * stride + offset)? == character {
                if matched.is_some() {
                    return Err(INVALID);
                }
                matched = Some(index);
            }
        }
        let Some(index) = matched else {
            return Ok(false);
        };
        let tracking_header = list + self.field("spawn_tracking")?;
        let tracking_before = read(tracking_header, 16)?;
        let (tracking, tracked_count) = Self::array_header(&tracking_before, MAX_SPAWN_ENTRIES)?;
        let mut matches = 0;
        for slot in 0..tracked_count {
            let row = tracking + slot * self.field("spawn_tracking_stride")?;
            if self.integer(row + self.field("spawn_tracking_index")?)? == index as i32 {
                if self.pointer(row + self.field("spawn_tracking_actor")?)? != pawn {
                    return Err(BUSY);
                }
                matches += 1;
            }
        }
        if read(entries_header, 16)? != before || read(tracking_header, 16)? != tracking_before {
            return Err(BUSY);
        }
        Ok(matches == 1)
    }
    fn validate_spawn_entries(&self, list: usize, target: usize) -> Result<(), i32> {
        self.checkpoint("resume.spawn-entry-inputs");
        let header = list + self.field("spawn_entries")?;
        let before = read(header, 16)?;
        let (data, count) = Self::array_header(&before, MAX_SPAWN_ENTRIES)?;
        let mut matches = 0;
        for index in 0..count {
            let character = self.pointer(
                data + index * self.field("spawn_entry_stride")?
                    + self.field("spawn_entry_character")?,
            )?;
            if character != 0 {
                self.require_class(character, "character")?;
                self.actor(character)?;
                if character == target {
                    matches += 1;
                }
            }
        }
        if matches > 1 {
            return Err(INVALID);
        }
        if read(header, 16)? != before {
            return Err(BUSY);
        }
        Ok(())
    }
    fn activate_record(
        &self,
        list: usize,
        world: usize,
        target: &Identity,
        character: usize,
        revalidate: impl FnOnce() -> Result<(), i32>,
    ) -> Result<bool, i32> {
        type Refresh = unsafe extern "system" fn(*mut c_void, *mut c_void);
        let refresh: Refresh =
            unsafe { std::mem::transmute(self.function("refresh_spawn_category")?) };
        self.require_class(list, "spawn_list")?;
        let manager = self.pointer(list + self.field("outer")?)?;
        if !self.in_world(manager, world)? {
            return Err(sod2se_abi::STALE);
        }
        let Some(category) = self.registered_category(manager, list)? else {
            return Ok(false);
        };
        self.validate_spawn_entries(list, character)?;
        revalidate()?;
        self.checkpoint("resume.category-registration-recheck");
        if self.registered_category(manager, list)? != Some(category)
            || self.identity(character)? != *target
            || self.byte(character + self.field("busy_state")?)? != 3
            || self.byte(character + self.field("record")? + self.field("dead")?)? != 0
            || self.pointer(character + self.field("character_component")?)? != 0
            || self.pointer(list + self.field("outer")?)? != manager
            || !self.in_world(manager, world)?
        {
            return Err(BUSY);
        }
        self.validate_spawn_entries(list, character)?;
        // The existing-category wrapper refreshes original viewpoints and
        // runs normal selection, creation, tracking and cleanup with delta=0.
        // It never creates a category registration or takes a custom desired set.
        self.category_activation.set(true);
        unsafe { refresh(manager as *mut c_void, category as *mut c_void) };
        self.checkpoint("resume.spawn-actor-confirmation");
        if let Some(pawn) = self.actor(character)?
            && (!self.in_world(pawn, world)? || !self.tracked_actor(list, character, pawn)?)
        {
            return Err(BUSY);
        }
        self.checkpoint("resume.activation-submitted");
        Ok(true)
    }
    pub fn resume_member(
        &self,
        context: &Context,
        target: &Identity,
        character: usize,
        allow_activation: bool,
    ) -> Result<bool, i32> {
        self.checkpoint("resume.existing-member");
        self.engine_thread()?;
        if target == &context.controlled
            || !self.matching(character, target)
            || !self.roster(context)?.contains(target)
        {
            return Err(BUSY);
        }
        if self.byte(character + self.field("record")? + self.field("dead")?)? != 0 {
            return Err(sod2se_abi::NOT_FOUND);
        }
        self.revalidate(context)?;
        self.checkpoint("resume.actor");
        if let Some(pawn) = self.actor(character)? {
            if !self.in_world(pawn, context.world)? {
                self.checkpoint("resume.old-world-actor");
                return Ok(false);
            }
            if self.community_member(context, character)? {
                let Some(list) = self.owned_spawn_list(context)? else {
                    self.checkpoint("resume.tracking-waiting");
                    return Ok(false);
                };
                if !self.tracked_actor(list, character, pawn)? {
                    self.checkpoint("resume.tracking-waiting");
                    return Ok(false);
                }
            }
            return self.bring_near(context, target, character);
        }
        if self.pointer(character + self.field("character_component")?)? != 0 {
            self.checkpoint("resume.component-waiting");
            return Ok(false);
        }
        self.checkpoint("resume.external-member");
        if !self.community_member(context, character)? {
            return Ok(false);
        }
        self.checkpoint("resume.waiting-actor");
        if allow_activation {
            // Enrollment alone does not restore the location request lost on
            // reload. Reuse the same saved-record preparation for cached members.
            self.restore_saved_community(context, target, character, true)?;
        }
        Ok(false)
    }
    /// Resolve community records first, then a bounded object slice for enclave/mission NPCs.
    /// The scan cursor is ordering only; an object pointer is never cached across frames.
    pub fn lookup(
        &self,
        context: &Context,
        target: &Identity,
        cursor: &mut usize,
    ) -> Result<Option<usize>, i32> {
        self.stage.set("restore.community-roster");
        let enclave = self.pointer(context.community + self.field("enclave")?)?;
        self.require_class(enclave, "characters")?;
        let (data, count) = self.array(enclave + self.field("characters_array")?, MAX_FOLLOWERS)?;
        for index in 0..count {
            let object = self.pointer(data + index * 8)?;
            if self.matching(object, target) {
                return Ok(Some(object));
            }
        }
        let count = self.integer(self.base + self.facts.object_count)?;
        self.stage.set("restore.external-objects");
        if !(0..=2_000_000).contains(&count) {
            return Err(INVALID);
        }
        let data = self.pointer(self.base + self.facts.object_data)?;
        for _ in 0..256.min(count as usize) {
            if *cursor >= count as usize {
                *cursor = 0;
            }
            let item = data + *cursor * 24;
            *cursor += 1;
            if self.integer(item + 8)? as u32 & 0x30000000 != 0 {
                continue;
            }
            let object = self.pointer(item)?;
            if object >= 0x10000 && self.matching(object, target) {
                return Ok(Some(object));
            }
        }
        Ok(None)
    }
    pub fn function(&self, name: &str) -> Result<usize, i32> {
        let function = self.facts.functions.get(name).ok_or(INVALID)?;
        let address = self.base.checked_add(function.rva).ok_or(INVALID)?;
        let mut memory: MEMORY_BASIC_INFORMATION = unsafe { std::mem::zeroed() };
        if unsafe {
            VirtualQuery(
                address as *const c_void,
                &mut memory,
                std::mem::size_of::<MEMORY_BASIC_INFORMATION>(),
            )
        } == 0
            || memory.AllocationBase as usize != self.base
            || ![
                PAGE_EXECUTE,
                PAGE_EXECUTE_READ,
                PAGE_EXECUTE_READWRITE,
                PAGE_EXECUTE_WRITECOPY,
            ]
            .contains(&memory.Protect)
            || address
                .checked_add(16)
                .is_none_or(|end| end > memory.BaseAddress as usize + memory.RegionSize)
        {
            return Err(UNSUPPORTED);
        }
        if read(address, 16)? != crate::decode(&function.guard)? {
            return Err(UNSUPPORTED);
        }
        Ok(address)
    }
    pub fn restore(
        &self,
        context: &Context,
        target: &Identity,
        character: usize,
        allow_activation: bool,
    ) -> Result<bool, i32> {
        self.stage.set("restore.identity");
        self.engine_thread()?;
        if !self.matching(character, target) {
            return Err(BUSY);
        }
        if self.byte(character + self.field("record")? + self.field("dead")?)? != 0 {
            return Err(sod2se_abi::NOT_FOUND);
        }
        if self.community_member(context, character)? {
            return self.restore_saved_community(context, target, character, allow_activation);
        }
        self.stage.set("restore.actor");
        let pawn = self.actor(character)?;
        if let Some(pawn) = pawn {
            if !self.in_world(pawn, context.world)? {
                return Err(BUSY);
            }
        } else if !self.community_member(context, character)? {
            // External/mission data alone cannot prove an active world owner.
            return Ok(false);
        }
        type Check = unsafe extern "system" fn(*mut c_void, *mut c_void) -> u8;
        self.stage.set("restore.eligibility");
        let allowed: Check = unsafe { std::mem::transmute(self.function("allowed")?) };
        let restriction: Check = unsafe { std::mem::transmute(self.function("restriction")?) };
        let allowed_code =
            unsafe { allowed(context.pawn as *mut c_void, character as *mut c_void) };
        if allowed_code != 0 {
            self.checkpoint(match allowed_code {
                1 => "restore.allowed-1",
                2 => "restore.allowed-2",
                3 => "restore.allowed-3",
                4 => "restore.allowed-4",
                5 => "restore.allowed-5",
                6 => "restore.allowed-6",
                7 => "restore.allowed-7",
                8 => "restore.allowed-8",
                9 => "restore.allowed-9",
                _ => "restore.allowed-unknown",
            });
            return Ok(false);
        }
        let restriction_code =
            unsafe { restriction(context.pawn as *mut c_void, character as *mut c_void) };
        if restriction_code != 0 {
            self.checkpoint(match restriction_code {
                1 => "restore.restriction-1",
                2 => "restore.restriction-2",
                3 => "restore.restriction-3",
                4 => "restore.restriction-4",
                _ => "restore.restriction-unknown",
            });
            return Ok(false);
        }
        type Validate = unsafe extern "system" fn(*mut c_void, *mut c_void, i32) -> bool;
        self.stage.set("restore.rpc-validation");
        let validate: Validate = unsafe { std::mem::transmute(self.function("validate_rpc")?) };
        if let Some(pawn) = pawn
            && !unsafe { validate(context.dialogue as *mut c_void, pawn as *mut c_void, 0) }
        {
            return Ok(false);
        }
        // Recheck after native eligibility calls; no dead or recycled incarnation may enter.
        self.stage.set("restore.context-recheck");
        if !self.matching(character, target) {
            return Err(BUSY);
        }
        self.healthy(context.controller)?;
        self.require_class(context.game, "game")?;
        let current_id = read(context.game + self.field("game_id")?, 16)?;
        let current_key: String = current_id.iter().map(|b| format!("{b:02x}")).collect();
        if current_key != context.key {
            return Err(sod2se_abi::STALE);
        }
        if self.current_world()? != context.world {
            return Err(BUSY);
        }
        // Eligibility callbacks may change network state; recheck before RPC.
        self.require_solo(context.world)?;
        if self.pointer(context.controller + self.field("pawn")?)? != context.pawn {
            return Err(BUSY);
        }
        if self.byte(character + self.field("record")? + self.field("dead")?)? != 0 {
            return Err(sod2se_abi::NOT_FOUND);
        }
        self.healthy(context.dialogue)?;
        if pawn.is_none() {
            self.stage.set("restore.community-record");
            if !self.community_member(context, character)? {
                return Err(BUSY);
            }
            self.require_class(context.manager, "followers")?;
            self.enlist_record(context.manager, character)?;
            return Ok(true);
        }
        let pawn = pawn.ok_or(BUSY)?;
        self.healthy(pawn)?;
        type Request = unsafe extern "system" fn(*mut c_void, *mut c_void, i32);
        self.stage.set("restore.rpc-submission");
        let request: Request = unsafe { std::mem::transmute(self.function("rpc")?) };
        unsafe { request(context.dialogue as *mut c_void, pawn as *mut c_void, 0) };
        // Submission is not confirmation; policy retains the entry until a later live snapshot.
        Ok(true)
    }
}
