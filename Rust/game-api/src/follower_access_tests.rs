//! Authored in-process memory and executable spies; no game code or process.
use super::*;
use std::sync::{
    Mutex,
    atomic::{AtomicUsize, Ordering},
};
use windows_sys::Win32::System::Diagnostics::Debug::FlushInstructionCache;
use windows_sys::Win32::System::Memory::{
    MEM_COMMIT, MEM_RELEASE, MEM_RESERVE, VirtualAlloc, VirtualFree,
};

static TEST_LOCK: Mutex<()> = Mutex::new(());
static CALLS: AtomicUsize = AtomicUsize::new(0);
static CALLED_MANAGER: AtomicUsize = AtomicUsize::new(0);
static CALLED_CATEGORY: AtomicUsize = AtomicUsize::new(0);
static LINK_SITE: AtomicUsize = AtomicUsize::new(0);
static LINK_COMPONENT: AtomicUsize = AtomicUsize::new(0);
static WORLD_RESULT: AtomicUsize = AtomicUsize::new(0);
static MANAGER_WORLD: AtomicUsize = AtomicUsize::new(0);
static TRACK_HEADER: AtomicUsize = AtomicUsize::new(0);
static TRACK_DATA: AtomicUsize = AtomicUsize::new(0);
static TRACK_ACTOR: AtomicUsize = AtomicUsize::new(0);
static TRACK_INDEX: AtomicUsize = AtomicUsize::new(0);
static TRACK_COUNT: AtomicUsize = AtomicUsize::new(0);
static TRACE: AtomicUsize = AtomicUsize::new(0);
static POSE_WRITES: AtomicUsize = AtomicUsize::new(0);
static KIND_WRITES: AtomicUsize = AtomicUsize::new(0);
static ADD_CALLS: AtomicUsize = AtomicUsize::new(0);
static BUSY_WRITES: AtomicUsize = AtomicUsize::new(0);
static SCENE_GETS: AtomicUsize = AtomicUsize::new(0);
static RECORD_GETS: AtomicUsize = AtomicUsize::new(0);
static ALLOWED_CODE: AtomicUsize = AtomicUsize::new(0);
static FOLLOW_CODE: AtomicUsize = AtomicUsize::new(0);
static SCENE_POSE: AtomicUsize = AtomicUsize::new(0);
static GETTER_MODE: AtomicUsize = AtomicUsize::new(0);
static READBACK_MODE: AtomicUsize = AtomicUsize::new(0);
static INPUT_ALIGNMENT: AtomicUsize = AtomicUsize::new(0);
static OUTPUT_ALIGNMENT: AtomicUsize = AtomicUsize::new(0);
static POSE_OFFSET: AtomicUsize = AtomicUsize::new(0);
static KIND_OFFSET: AtomicUsize = AtomicUsize::new(0);
static BUSY_OFFSET: AtomicUsize = AtomicUsize::new(0);
static ARRAY_OFFSET: AtomicUsize = AtomicUsize::new(0);
static NOTIFY: AtomicUsize = AtomicUsize::new(0);
static KIND_VALUE: AtomicUsize = AtomicUsize::new(0);
static FOLLOW_DYNAMIC: AtomicUsize = AtomicUsize::new(0);
static BUSY_OVERWRITE: AtomicUsize = AtomicUsize::new(0);
static BUSY_FALLBACK_POSE: AtomicUsize = AtomicUsize::new(0);

fn trace(step: usize) {
    let _ = TRACE.fetch_update(Ordering::SeqCst, Ordering::SeqCst, |previous| {
        Some((previous << 4) | step)
    });
}

unsafe extern "system" fn allowed(_: *mut c_void, _: *mut c_void) -> u8 {
    ALLOWED_CODE.load(Ordering::SeqCst) as u8
}

unsafe extern "system" fn follow_allowed(_: *mut c_void, _: *mut c_void) -> u8 {
    if FOLLOW_DYNAMIC.load(Ordering::SeqCst) != 0 && ADD_CALLS.load(Ordering::SeqCst) != 0 {
        return 1;
    }
    FOLLOW_CODE.load(Ordering::SeqCst) as u8
}

unsafe extern "system" fn component_transform(
    _: *mut c_void,
    out: *mut SavedTransform,
) -> *mut SavedTransform {
    SCENE_GETS.fetch_add(1, Ordering::SeqCst);
    OUTPUT_ALIGNMENT.store(out as usize % 16, Ordering::SeqCst);
    trace(9);
    unsafe { *out = *(SCENE_POSE.load(Ordering::SeqCst) as *const SavedTransform) };
    if GETTER_MODE.load(Ordering::SeqCst) == 1 {
        std::ptr::null_mut()
    } else {
        out
    }
}

unsafe extern "system" fn set_record_transform(
    character: *mut c_void,
    value: *const SavedTransform,
) {
    POSE_WRITES.fetch_add(1, Ordering::SeqCst);
    INPUT_ALIGNMENT.store(value as usize % 16, Ordering::SeqCst);
    trace(1);
    unsafe {
        std::ptr::write(
            (character as usize + POSE_OFFSET.load(Ordering::SeqCst)) as *mut SavedTransform,
            *value,
        )
    };
}

unsafe extern "system" fn set_position_kind(character: *mut c_void, value: u8) {
    KIND_WRITES.fetch_add(1, Ordering::SeqCst);
    KIND_VALUE.store(value as usize, Ordering::SeqCst);
    trace(2);
    put(
        character as usize + KIND_OFFSET.load(Ordering::SeqCst),
        &[value],
    );
}

unsafe extern "system" fn add_member(manager: *mut c_void, character: *mut c_void, notify: u8) {
    ADD_CALLS.fetch_add(1, Ordering::SeqCst);
    NOTIFY.store(notify as usize, Ordering::SeqCst);
    trace(3);
    let header = manager as usize + ARRAY_OFFSET.load(Ordering::SeqCst);
    let data = unsafe { std::ptr::read_unaligned(header as *const usize) };
    let count = unsafe { std::ptr::read_unaligned((header + 8) as *const i32) };
    for index in 0..count {
        if unsafe { std::ptr::read_unaligned((data + index as usize * 8) as *const usize) }
            == character as usize
        {
            return;
        }
    }
    put(
        data + count as usize * 8,
        &(character as usize).to_le_bytes(),
    );
    put(header + 8, &(count + 1).to_le_bytes());
}

unsafe extern "system" fn set_busy_state(character: *mut c_void, value: u8) {
    BUSY_WRITES.fetch_add(1, Ordering::SeqCst);
    trace(4);
    let at = character as usize + BUSY_OFFSET.load(Ordering::SeqCst);
    // Preserve the original refusal to change a conflicting nonzero BusyState.
    let previous = unsafe { *(at as *const u8) };
    if previous == 0 || previous == value {
        put(at, &[value]);
        if previous == 0 && value == 3 && BUSY_OVERWRITE.load(Ordering::SeqCst) != 0 {
            unsafe {
                std::ptr::write(
                    (character as usize + POSE_OFFSET.load(Ordering::SeqCst))
                        as *mut SavedTransform,
                    *(BUSY_FALLBACK_POSE.load(Ordering::SeqCst) as *const SavedTransform),
                )
            };
        }
    }
}

unsafe extern "system" fn record_transform(
    character: *mut c_void,
    out: *mut SavedTransform,
) -> *mut SavedTransform {
    RECORD_GETS.fetch_add(1, Ordering::SeqCst);
    trace(5);
    unsafe {
        *out = *((character as usize + POSE_OFFSET.load(Ordering::SeqCst)) as *const SavedTransform)
    };
    match READBACK_MODE.load(Ordering::SeqCst) {
        1 => {
            unsafe { (*out).translation[0] += 10_000.0 };
            out
        }
        2 => std::ptr::null_mut(),
        _ => out,
    }
}

unsafe extern "system" fn world_self(world: *mut c_void) -> *mut c_void {
    match WORLD_RESULT.load(Ordering::SeqCst) {
        0 => world,
        other => other as *mut c_void,
    }
}

unsafe extern "system" fn actor_world(_: *mut c_void) -> *mut c_void {
    MANAGER_WORLD.load(Ordering::SeqCst) as *mut c_void
}

unsafe extern "system" fn refresh(manager: *mut c_void, category: *mut c_void) {
    trace(6);
    CALLS.fetch_add(1, Ordering::SeqCst);
    CALLED_MANAGER.store(manager as usize, Ordering::SeqCst);
    CALLED_CATEGORY.store(category as usize, Ordering::SeqCst);
    let site = LINK_SITE.load(Ordering::SeqCst);
    if site != 0 {
        unsafe {
            std::ptr::write_unaligned(site as *mut usize, LINK_COMPONENT.load(Ordering::SeqCst))
        };
    }
    let header = TRACK_HEADER.load(Ordering::SeqCst);
    if header != 0 {
        let data = TRACK_DATA.load(Ordering::SeqCst);
        let count = TRACK_COUNT.load(Ordering::SeqCst) as i32;
        put(header, &data.to_le_bytes());
        put(header + 8, &count.to_le_bytes());
        put(header + 12, &count.to_le_bytes());
        for slot in 0..count {
            let row = data + slot as usize * 0x10;
            put(row, &TRACK_ACTOR.load(Ordering::SeqCst).to_le_bytes());
            put(
                row + 8,
                &(TRACK_INDEX.load(Ordering::SeqCst) as i32).to_le_bytes(),
            );
        }
    }
}

struct Fixture {
    base: usize,
    facts: &'static Facts,
    world: usize,
    foreign_world: usize,
    foreign_level: usize,
    controller: usize,
    player_pawn: usize,
    game: usize,
    followers: usize,
    dialogue: usize,
    community: usize,
    enclave: usize,
    list: usize,
    spawn_manager: usize,
    category: usize,
    category_parent: usize,
    payload: usize,
    default: usize,
    character: usize,
    other_character: usize,
    pawn: usize,
    foreign_pawn: usize,
    component: usize,
    scene: usize,
    entries: usize,
    vtable: usize,
    manager_vtable: usize,
    categories: usize,
    tracking: usize,
    target: Identity,
}

impl Fixture {
    fn new() -> Self {
        const SIZE: usize = 0x100000;
        let page = unsafe {
            VirtualAlloc(
                std::ptr::null(),
                SIZE,
                MEM_COMMIT | MEM_RESERVE,
                PAGE_EXECUTE_READWRITE,
            )
        };
        assert!(!page.is_null());
        let base = page as usize;
        let mut facts: Facts =
            serde_json::from_str(include_str!("../follower-bindings.json")).unwrap();
        facts.object_data = 0x800;
        facts.object_count = 0x808;
        facts.thread_id = 0x810;
        facts.thread_initialized = 0x814;
        facts.player_global = 0x820;
        for (index, cache) in facts.classes.values_mut().enumerate() {
            *cache = 0x1000 + index * 8;
            put(base + *cache, &(base + 0x2000 + index * 0x80).to_le_bytes());
        }
        for (name, offset, callback) in [
            ("world_self", 0x100usize, world_self as *const () as usize),
            (
                "refresh_spawn_category",
                0x200,
                refresh as *const () as usize,
            ),
            ("actor_world", 0x300, actor_world as *const () as usize),
            ("allowed", 0x400, allowed as *const () as usize),
            ("restriction", 0x500, follow_allowed as *const () as usize),
            (
                "component_transform",
                0x600,
                component_transform as *const () as usize,
            ),
            (
                "record_set_transform",
                0x700,
                set_record_transform as *const () as usize,
            ),
            (
                "set_saved_position_kind",
                0x900,
                set_position_kind as *const () as usize,
            ),
            ("manager_add", 0xa00, add_member as *const () as usize),
            (
                "set_busy_state",
                0xb00,
                set_busy_state as *const () as usize,
            ),
            (
                "get_record_transform",
                0xc00,
                record_transform as *const () as usize,
            ),
        ] {
            let mut code = vec![0x48, 0xb8];
            code.extend_from_slice(&(callback as u64).to_le_bytes());
            code.extend_from_slice(&[0xff, 0xe0, 0x90, 0x90, 0x90, 0x90]);
            put(base + offset, &code);
            facts.functions.insert(
                name.into(),
                Function {
                    rva: offset,
                    guard: code.iter().map(|byte| format!("{byte:02x}")).collect(),
                },
            );
        }
        assert_ne!(
            unsafe { FlushInstructionCache(GetCurrentProcess(), page, 0xd00) },
            0,
        );
        let facts = Box::leak(Box::new(facts));
        let mut next = 0x10000;
        let mut count = 0usize;
        let mut object = |class: &str| {
            let address = base + next;
            next += 0x2000;
            let cache = base + facts.classes[class];
            let class_pointer = usize::from_le_bytes(read(cache, 8).unwrap().try_into().unwrap());
            put(address + 12, &(count as i32).to_le_bytes());
            put(
                address + facts.fields["object_class"],
                &class_pointer.to_le_bytes(),
            );
            put(base + 0x8000 + count * 24, &address.to_le_bytes());
            count += 1;
            address
        };
        let world = object("world");
        let foreign_world = object("world");
        let mode = object("game_mode");
        let level = object("level");
        let foreign_level = object("level");
        let community = object("community");
        let enclave = object("characters");
        let list = object("spawn_list");
        let spawn_manager = object("spawn_manager");
        let character = object("character");
        let other_character = object("character");
        let pawn = object("pawn");
        let foreign_pawn = object("pawn");
        let component = object("component");
        let player = object("player");
        let controller = object("controller");
        let player_pawn = object("pawn");
        let player_component = object("component");
        let controlled = object("character");
        let instance = object("instance");
        let save_manager = object("save_manager");
        let game = object("game");
        let followers = object("followers");
        let dialogue = object("dialogue");
        let category = object("uclass");
        let category_parent = object("uclass");
        let payload = object("spawn_payload");
        let default = object("spawn_category");
        let scene = object("scene_component");
        put(base + facts.object_data, &(base + 0x8000).to_le_bytes());
        put(base + facts.object_count, &(count as i32).to_le_bytes());
        let fixture = Self {
            base,
            facts,
            world,
            foreign_world,
            foreign_level,
            controller,
            player_pawn,
            game,
            followers,
            dialogue,
            community,
            enclave,
            list,
            spawn_manager,
            category,
            category_parent,
            payload,
            default,
            character,
            other_character,
            pawn,
            foreign_pawn,
            component,
            scene,
            entries: base + 0x80000,
            vtable: base + 0x4000,
            manager_vtable: base + 0x4400,
            categories: base + 0xc000,
            tracking: base + 0xd000,
            target: Identity {
                id: 7,
                narrative: 0,
                entity: 0,
            },
        };
        fixture.pointer(world, fixture.vtable);
        fixture.pointer(foreign_world, fixture.vtable);
        fixture.pointer(
            fixture.vtable + fixture.field("get_world_slot"),
            base + 0x100,
        );
        for world in [world, foreign_world] {
            fixture.pointer(world + fixture.field("world_mode"), mode);
        }
        fixture.pointer(level + fixture.field("level_world"), world);
        fixture.pointer(foreign_level + fixture.field("level_world"), foreign_world);
        fixture.pointer(community + fixture.field("enclave"), enclave);
        fixture.pointer(enclave + fixture.field("enclave_spawn_list"), list);
        fixture.pointer(list + fixture.field("outer"), spawn_manager);
        fixture.pointer(spawn_manager + fixture.field("outer"), level);
        fixture.pointer(spawn_manager, fixture.manager_vtable);
        fixture.pointer(
            fixture.manager_vtable + fixture.field("get_world_slot"),
            base + 0x300,
        );
        fixture.pointer(category + fixture.field("class_parent"), category_parent);
        let category_base = usize::from_le_bytes(
            read(base + facts.classes["spawn_category"], 8)
                .unwrap()
                .try_into()
                .unwrap(),
        );
        fixture.pointer(
            category_parent + fixture.field("class_parent"),
            category_base,
        );
        fixture.pointer(category + fixture.field("spawn_category_default"), default);
        fixture.integer(default + 8, 0x10);
        fixture.pointer(default + fixture.field("object_class"), category);
        fixture.pointer(payload + fixture.field("outer"), spawn_manager);
        fixture.pointer(list + fixture.field("spawn_list_category"), default);
        fixture.registrations(&[(category, payload, list)]);
        fixture.pointer(list + fixture.field("spawn_tracking"), fixture.tracking);
        fixture.pointer(pawn + fixture.field("outer"), level);
        fixture.pointer(foreign_pawn + fixture.field("outer"), foreign_level);
        fixture.pointer(player_pawn + fixture.field("outer"), level);
        fixture.identity(character, &fixture.target);
        fixture.identity(
            other_character,
            &Identity {
                id: 8,
                narrative: 0,
                entity: 0,
            },
        );
        fixture.entries(&[other_character, character]);
        // The high-level reader also qualifies the authored controlled survivor,
        // selected community, and original manager through their actual layout.
        fixture.integer(base + facts.thread_id, unsafe { GetCurrentThreadId() }
            as i32);
        fixture.integer(base + facts.thread_initialized, 1);
        fixture.pointer(base + facts.player_global, player);
        fixture.pointer(player + fixture.field("controller"), controller);
        fixture.pointer(controller + fixture.field("outer"), level);
        fixture.pointer(controller + fixture.field("pawn"), player_pawn);
        fixture.pointer(player_pawn + fixture.field("component"), player_component);
        fixture.pointer(player_pawn + fixture.field("actor_root"), scene);
        fixture.pointer(scene + fixture.field("component_owner"), player_pawn);
        fixture.pointer(player_component + fixture.field("character"), controlled);
        fixture.identity(controlled, &fixture.context().controlled);
        fixture.pointer(world + fixture.field("world_instance"), instance);
        fixture.pointer(instance + fixture.field("save_manager"), save_manager);
        fixture.pointer(save_manager + 0x150, base + 0x6000);
        fixture.integer(save_manager + 0x158, 1);
        fixture.pointer(base + 0x6008, base + 0x7000);
        fixture.integer(base + 0x6010, 1);
        fixture.integer(base + 0x6014, 1);
        fixture.integer(base + 0x6028, -1);
        fixture.pointer(base + 0x7000, game);
        fixture.pointer(game + 0x1c8, base + 0x9000);
        fixture.integer(game + 0x1d0, 1);
        fixture.integer(game + 0x1d4, 1);
        fixture.integer(base + 0x9000, 1);
        put(game + fixture.field("game_id"), &[1; 1]);
        fixture.pointer(controller + fixture.field("followers"), followers);
        fixture.pointer(controller + fixture.field("dialogue"), dialogue);
        fixture.pointer(controller + fixture.field("community_component"), community);
        fixture.integer(community + fixture.field("last_follower_id"), 1);
        fixture.pointer(followers + fixture.field("array"), base + 0xa000);
        fixture.integer(followers + fixture.field("array") + 8, 1);
        fixture.integer(followers + fixture.field("array") + 12, 1);
        fixture.pointer(base + 0xa000, character);
        put(character + fixture.field("busy_state"), &[3]);
        fixture.pointer(enclave + fixture.field("characters_array"), base + 0xb000);
        fixture.integer(enclave + fixture.field("characters_array") + 8, 2);
        fixture.integer(enclave + fixture.field("characters_array") + 12, 2);
        fixture.pointer(base + 0xb000, character);
        fixture.pointer(base + 0xb008, controlled);
        for value in [
            &CALLS,
            &LINK_SITE,
            &LINK_COMPONENT,
            &WORLD_RESULT,
            &TRACK_HEADER,
            &TRACK_DATA,
            &TRACK_ACTOR,
            &TRACK_INDEX,
            &TRACK_COUNT,
            &TRACE,
            &POSE_WRITES,
            &KIND_WRITES,
            &ADD_CALLS,
            &BUSY_WRITES,
            &SCENE_GETS,
            &RECORD_GETS,
            &ALLOWED_CODE,
            &GETTER_MODE,
            &READBACK_MODE,
            &INPUT_ALIGNMENT,
            &OUTPUT_ALIGNMENT,
            &NOTIFY,
            &KIND_VALUE,
            &FOLLOW_DYNAMIC,
            &BUSY_OVERWRITE,
        ] {
            value.store(0, Ordering::SeqCst);
        }
        MANAGER_WORLD.store(world, Ordering::SeqCst);
        FOLLOW_CODE.store(1, Ordering::SeqCst);
        SCENE_POSE.store(base + 0xe000, Ordering::SeqCst);
        POSE_OFFSET.store(fixture.field("record_transform"), Ordering::SeqCst);
        KIND_OFFSET.store(fixture.field("saved_position_kind"), Ordering::SeqCst);
        BUSY_OFFSET.store(fixture.field("busy_state"), Ordering::SeqCst);
        ARRAY_OFFSET.store(fixture.field("array"), Ordering::SeqCst);
        fixture.pose(base + 0xe000, &Self::player_pose());
        fixture.pose(
            character + fixture.field("record_transform"),
            &Self::old_pose(),
        );
        BUSY_FALLBACK_POSE.store(base + 0xe100, Ordering::SeqCst);
        fixture.pose(base + 0xe100, &Self::old_pose());
        fixture
    }

    fn reader(&self) -> Reader {
        Reader {
            base: self.base,
            facts: self.facts,
            stage: Cell::new("test"),
            saved_mutation: Cell::new(false),
            category_activation: Cell::new(false),
        }
    }

    fn context(&self) -> Context {
        Context {
            world: self.world,
            controller: self.controller,
            pawn: self.player_pawn,
            dialogue: self.dialogue,
            community: self.community,
            game: self.game,
            manager: self.followers,
            key: "01000000000000000000000000000000".into(),
            controlled: Identity {
                id: 1,
                narrative: 0,
                entity: 0,
            },
            vanilla_follower: 1,
        }
    }

    fn field(&self, name: &str) -> usize {
        self.facts.fields[name]
    }

    fn player_pose() -> SavedTransform {
        SavedTransform {
            rotation: [
                0.0,
                0.0,
                std::f32::consts::FRAC_1_SQRT_2,
                std::f32::consts::FRAC_1_SQRT_2,
            ],
            translation: [200_000.0, -150_000.0, 123.0, 0.0],
            scale: [1.25, 0.75, 1.0, 0.0],
        }
    }

    fn old_pose() -> SavedTransform {
        SavedTransform {
            rotation: [0.0, 0.0, 0.0, 1.0],
            translation: [30_000.0, -50_000.0, 100.0, 0.0],
            scale: [1.0, 1.0, 1.0, 0.0],
        }
    }

    fn pose(&self, at: usize, value: &SavedTransform) {
        assert_eq!(at % 16, 0);
        unsafe { std::ptr::write(at as *mut SavedTransform, *value) };
    }

    fn saved_enlist(&self, reader: &Reader, pose: &SavedTransform) -> Result<(), i32> {
        reader.enlist_saved_record(self.followers, self.character, pose, || Ok(()))
    }

    fn unregistered(&self) {
        let header = self.followers + self.field("array");
        self.integer(header + 8, 0);
        put(self.character + self.field("busy_state"), &[0]);
        FOLLOW_CODE.store(3, Ordering::SeqCst);
        ALLOWED_CODE.store(3, Ordering::SeqCst);
        FOLLOW_DYNAMIC.store(1, Ordering::SeqCst);
    }

    fn mutation_calls() -> usize {
        [&POSE_WRITES, &KIND_WRITES, &ADD_CALLS, &BUSY_WRITES, &CALLS]
            .into_iter()
            .map(|counter| counter.load(Ordering::SeqCst))
            .sum()
    }

    fn pointer(&self, at: usize, value: usize) {
        put(at, &value.to_le_bytes());
    }

    fn integer(&self, at: usize, value: i32) {
        put(at, &value.to_le_bytes());
    }

    fn identity(&self, character: usize, identity: &Identity) {
        let record = character + self.field("record");
        self.integer(record, identity.id);
        put(record + 8, &identity.narrative.to_le_bytes());
        put(record + 16, &identity.entity.to_le_bytes());
    }

    fn entries(&self, characters: &[usize]) {
        let header = self.list + self.field("spawn_entries");
        self.pointer(header, self.entries);
        self.integer(header + 8, characters.len() as i32);
        self.integer(header + 12, characters.len() as i32);
        for (index, character) in characters.iter().enumerate() {
            self.pointer(
                self.entries
                    + index * self.field("spawn_entry_stride")
                    + self.field("spawn_entry_character"),
                *character,
            );
        }
    }

    fn registrations(&self, values: &[(usize, usize, usize)]) {
        let header = self.spawn_manager + self.field("spawn_categories");
        self.pointer(header, self.categories);
        self.integer(header + 8, values.len() as i32);
        self.integer(header + 12, values.len() as i32);
        for (index, (key, payload, list)) in values.iter().enumerate() {
            let row = self.categories + index * self.field("spawn_category_stride");
            self.pointer(row + self.field("spawn_category_class"), *key);
            self.pointer(row + self.field("spawn_category_payload"), *payload);
            self.pointer(row + self.field("spawn_category_list"), *list);
        }
    }

    fn spawned_actor(&self, owner: usize, backlink: usize) {
        self.pointer(self.component + self.field("component_owner"), owner);
        self.pointer(self.component + self.field("character"), backlink);
        self.pointer(owner + self.field("component"), self.component);
        LINK_SITE.store(
            self.character + self.field("character_component"),
            Ordering::SeqCst,
        );
        LINK_COMPONENT.store(self.component, Ordering::SeqCst);
        TRACK_HEADER.store(self.list + self.field("spawn_tracking"), Ordering::SeqCst);
        TRACK_DATA.store(self.tracking, Ordering::SeqCst);
        TRACK_ACTOR.store(owner, Ordering::SeqCst);
        TRACK_INDEX.store(1, Ordering::SeqCst);
        TRACK_COUNT.store(1, Ordering::SeqCst);
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        assert_eq!(
            unsafe { VirtualFree(self.base as *mut c_void, 0, MEM_RELEASE) },
            1
        );
    }
}

fn put(at: usize, bytes: &[u8]) {
    unsafe { std::ptr::copy_nonoverlapping(bytes.as_ptr(), at as *mut u8, bytes.len()) };
}

#[test]
fn wrapper_uses_two_native_arguments_and_absence_is_only_a_submission() {
    let _lock = TEST_LOCK.lock().unwrap();
    let fixture = Fixture::new();
    let reader = fixture.reader();
    assert_eq!(
        reader.owned_spawn_list(&fixture.context()),
        Ok(Some(fixture.list))
    );
    assert_eq!(reader.actor(fixture.character), Ok(None));
    assert_eq!(
        reader.activate_record(
            fixture.list,
            fixture.world,
            &fixture.target,
            fixture.character,
            || Ok(())
        ),
        Ok(true)
    );
    assert_eq!(CALLS.load(Ordering::SeqCst), 1);
    assert_eq!(CALLED_MANAGER.load(Ordering::SeqCst), fixture.spawn_manager);
    assert_eq!(CALLED_CATEGORY.load(Ordering::SeqCst), fixture.category);
    assert_eq!(reader.actor(fixture.character), Ok(None));
    assert_eq!(reader.stage(), "resume.activation-submitted");
}

#[test]
fn registration_requires_unique_uclass_payload_and_original_default_object() {
    let _lock = TEST_LOCK.lock().unwrap();
    for refusal in 0..16 {
        let fixture = Fixture::new();
        let reader = fixture.reader();
        let header = fixture.spawn_manager + fixture.field("spawn_categories");
        match refusal {
            0 => fixture.registrations(&[]),
            1 => fixture.registrations(&[
                (fixture.category, fixture.payload, fixture.list),
                (fixture.category_parent, fixture.payload, fixture.list),
            ]),
            2 => fixture.registrations(&[
                (fixture.category, fixture.payload, fixture.list),
                (fixture.category, fixture.payload, fixture.enclave),
            ]),
            3 => fixture.integer(header + 8, -1),
            4 => fixture.integer(header + 12, 0),
            5 => fixture.integer(header + 12, MAX_SPAWN_ENTRIES as i32 + 1),
            6 => fixture.pointer(fixture.categories, fixture.character),
            7 => fixture.pointer(
                fixture.category + fixture.field("class_parent"),
                fixture.character,
            ),
            8 => fixture.pointer(
                fixture.categories + fixture.field("spawn_category_payload"),
                fixture.character,
            ),
            9 => fixture.pointer(
                fixture.payload + fixture.field("outer"),
                fixture.foreign_pawn,
            ),
            10 => fixture.integer(fixture.default + 8, 0),
            11 => fixture.pointer(
                fixture.default + fixture.field("object_class"),
                fixture.category_parent,
            ),
            12 => fixture.pointer(
                fixture.list + fixture.field("spawn_list_category"),
                fixture.payload,
            ),
            13 => {
                let index = reader.integer(fixture.default + 12).unwrap() as usize;
                fixture.pointer(fixture.base + 0x8000 + index * 24, 0);
            }
            14 => fixture
                .registrations(&[(1, 0, 0), (fixture.category, fixture.payload, fixture.list)]),
            _ => put(fixture.base + 0x200, &[0x90]),
        }
        let result = reader.activate_record(
            fixture.list,
            fixture.world,
            &fixture.target,
            fixture.character,
            || Ok(()),
        );
        if refusal == 0 {
            assert_eq!(result, Ok(false));
        } else {
            assert!(result.is_err(), "registration case {refusal}: {result:?}");
        }
        assert_eq!(
            CALLS.load(Ordering::SeqCst),
            0,
            "registration case {refusal}"
        );
    }
}

#[test]
fn wrapper_rechecks_category_context_and_member_before_calling_native_code() {
    let _lock = TEST_LOCK.lock().unwrap();
    for refusal in 0..6 {
        let fixture = Fixture::new();
        let reader = fixture.reader();
        let result = reader.activate_record(
            fixture.list,
            fixture.world,
            &fixture.target,
            fixture.character,
            || {
                match refusal {
                    0 => {
                        fixture.pointer(
                            fixture.spawn_manager + fixture.field("outer"),
                            fixture.foreign_level,
                        );
                        reader.owned_spawn_list(&fixture.context())?;
                    }
                    1 => {
                        fixture.pointer(fixture.categories, fixture.category_parent);
                        fixture.pointer(
                            fixture.category_parent + fixture.field("spawn_category_default"),
                            fixture.default,
                        );
                        fixture.pointer(
                            fixture.default + fixture.field("object_class"),
                            fixture.category_parent,
                        );
                    }
                    2 => fixture.pointer(
                        fixture.categories + fixture.field("spawn_category_list"),
                        fixture.enclave,
                    ),
                    3 => fixture.integer(fixture.character + fixture.field("record"), 9),
                    4 => put(fixture.character + fixture.field("busy_state"), &[0]),
                    _ => fixture.pointer(
                        fixture.character + fixture.field("character_component"),
                        fixture.component,
                    ),
                }
                Ok(())
            },
        );
        assert!(result.is_err(), "context case {refusal}: {result:?}");
        assert_eq!(CALLS.load(Ordering::SeqCst), 0, "context case {refusal}");
    }
}

#[test]
fn spawn_list_requires_outer_world_and_both_original_world_function_slots() {
    let _lock = TEST_LOCK.lock().unwrap();
    for refusal in 0..13 {
        let fixture = Fixture::new();
        let reader = fixture.reader();
        let mut context = fixture.context();
        match refusal {
            0 => {}
            1 => fixture.pointer(fixture.enclave + fixture.field("enclave_spawn_list"), 0),
            2 => fixture.pointer(
                fixture.spawn_manager + fixture.field("outer"),
                fixture.foreign_level,
            ),
            3 => {
                let wrong = reader
                    .pointer(fixture.base + fixture.facts.classes["character"])
                    .unwrap();
                fixture.pointer(fixture.spawn_manager + fixture.field("object_class"), wrong);
            }
            4 => fixture.pointer(
                fixture.vtable + fixture.field("get_world_slot"),
                fixture.base + 0x200,
            ),
            5 => WORLD_RESULT.store(fixture.foreign_world, Ordering::SeqCst),
            6 => context.world = fixture.foreign_world,
            7 => put(fixture.base + 0x100, &[0x90]),
            8 => fixture.pointer(
                fixture.world + fixture.field("world_mode"),
                fixture.character,
            ),
            9 => fixture.pointer(
                fixture.manager_vtable + fixture.field("get_world_slot"),
                fixture.base + 0x100,
            ),
            10 => MANAGER_WORLD.store(fixture.foreign_world, Ordering::SeqCst),
            11 => put(fixture.base + 0x300, &[0x90]),
            _ => fixture.pointer(fixture.list + fixture.field("spawn_list_category"), 1),
        }
        let result = reader.owned_spawn_list(&context);
        match refusal {
            0 | 12 => assert_eq!(result, Ok(Some(fixture.list))),
            1 => assert_eq!(result, Ok(None)),
            _ => assert!(result.is_err(), "world case {refusal}: {result:?}"),
        }
        assert_eq!(CALLS.load(Ordering::SeqCst), 0);
    }
}

#[test]
fn created_actor_requires_reciprocal_world_and_exact_original_tracking() {
    let _lock = TEST_LOCK.lock().unwrap();
    for refusal in 0..8 {
        let fixture = Fixture::new();
        let reader = fixture.reader();
        let owner = if refusal == 1 {
            fixture.foreign_pawn
        } else {
            fixture.pawn
        };
        let backlink = if refusal == 2 {
            fixture.other_character
        } else {
            fixture.character
        };
        fixture.spawned_actor(owner, backlink);
        match refusal {
            3 => TRACK_COUNT.store(0, Ordering::SeqCst),
            4 => TRACK_INDEX.store(0, Ordering::SeqCst),
            5 => TRACK_ACTOR.store(fixture.foreign_pawn, Ordering::SeqCst),
            6 => TRACK_COUNT.store(2, Ordering::SeqCst),
            7 => {
                let wrong = reader
                    .pointer(fixture.base + fixture.facts.classes["character"])
                    .unwrap();
                fixture.pointer(fixture.component + fixture.field("object_class"), wrong);
            }
            _ => {}
        }
        assert_eq!(reader.actor(fixture.character), Ok(None));
        let result = reader.activate_record(
            fixture.list,
            fixture.world,
            &fixture.target,
            fixture.character,
            || Ok(()),
        );
        if refusal == 0 {
            assert_eq!(result, Ok(true));
            assert_eq!(reader.actor(fixture.character), Ok(Some(fixture.pawn)));
            assert_eq!(reader.stage(), "resume.activation-submitted");
        } else {
            assert!(result.is_err(), "tracking case {refusal}: {result:?}");
        }
        assert_eq!(CALLS.load(Ordering::SeqCst), 1, "tracking case {refusal}");
    }
}

#[test]
fn world_spawn_pool_can_exceed_the_saved_roster_without_using_other_identities() {
    let _lock = TEST_LOCK.lock().unwrap();
    let fixture = Fixture::new();
    let reader = fixture.reader();
    fixture.identity(fixture.other_character, &fixture.target);
    let mut pool = vec![0usize; MAX_FOLLOWERS + 2];
    pool[0] = fixture.other_character;
    pool[MAX_FOLLOWERS + 1] = fixture.character;
    fixture.entries(&pool);
    fixture.spawned_actor(fixture.pawn, fixture.character);
    TRACK_INDEX.store(MAX_FOLLOWERS + 1, Ordering::SeqCst);
    assert_eq!(
        reader.activate_record(
            fixture.list,
            fixture.world,
            &fixture.target,
            fixture.character,
            || Ok(())
        ),
        Ok(true)
    );
    assert_eq!(CALLS.load(Ordering::SeqCst), 1);
    assert_eq!(
        reader.tracked_actor(fixture.list, fixture.character, fixture.pawn),
        Ok(true)
    );
}

#[test]
fn native_wrapper_refuses_corrupt_spawn_pools_without_interpreting_other_identities() {
    let _lock = TEST_LOCK.lock().unwrap();
    for refusal in 0..6 {
        let fixture = Fixture::new();
        let reader = fixture.reader();
        let header = fixture.list + fixture.field("spawn_entries");
        match refusal {
            0 => fixture.integer(header + 8, -1),
            1 => fixture.integer(header + 12, 1),
            2 => fixture.integer(header + 12, MAX_SPAWN_ENTRIES as i32 + 1),
            3 => fixture.entries(&[1, fixture.character]),
            4 => fixture.entries(&[fixture.world, fixture.character]),
            _ => fixture.entries(&[fixture.character, fixture.character]),
        }
        let result = reader.activate_record(
            fixture.list,
            fixture.world,
            &fixture.target,
            fixture.character,
            || Ok(()),
        );
        assert!(result.is_err(), "spawn pool case {refusal}: {result:?}");
        assert_eq!(CALLS.load(Ordering::SeqCst), 0, "spawn pool case {refusal}");
    }
}

#[test]
fn resume_waits_for_cleanup_and_refuses_unowned_or_invalid_components() {
    let _lock = TEST_LOCK.lock().unwrap();
    for refusal in 0..4 {
        let fixture = Fixture::new();
        let reader = fixture.reader();
        let context = fixture.context();
        assert_eq!(reader.revalidate(&context), Ok(()));
        let mut member = fixture.character;
        match refusal {
            0 => fixture.pointer(
                fixture.character + fixture.field("character_component"),
                fixture.component,
            ),
            1 => {
                fixture.pointer(
                    fixture.character + fixture.field("character_component"),
                    fixture.component,
                );
                fixture.pointer(
                    fixture.component + fixture.field("component_owner"),
                    fixture.foreign_pawn,
                );
                fixture.pointer(
                    fixture.component + fixture.field("character"),
                    fixture.character,
                );
                fixture.pointer(
                    fixture.foreign_pawn + fixture.field("component"),
                    fixture.component,
                );
            }
            2 => {
                fixture.pointer(
                    fixture.character + fixture.field("character_component"),
                    fixture.component,
                );
                let wrong = reader
                    .pointer(fixture.base + fixture.facts.classes["character"])
                    .unwrap();
                fixture.pointer(fixture.component + fixture.field("object_class"), wrong);
            }
            _ => {
                fixture.identity(fixture.other_character, &fixture.target);
                member = fixture.other_character;
            }
        }
        let result = reader.resume_member(&context, &fixture.target, member, true);
        if refusal == 2 {
            assert_eq!(result, Err(UNSUPPORTED));
        } else {
            assert_eq!(result, Ok(false), "cleanup case {refusal}");
        }
        assert_eq!(CALLS.load(Ordering::SeqCst), 0, "cleanup case {refusal}");
    }
}

#[test]
fn typed_scene_getter_preserves_all_48_bytes_and_only_offsets_translation() {
    let _lock = TEST_LOCK.lock().unwrap();
    assert_eq!(std::mem::size_of::<SavedTransform>(), 48);
    assert_eq!(std::mem::align_of::<SavedTransform>(), 16);
    let fixture = Fixture::new();
    let reader = fixture.reader();
    let mut expected = Fixture::player_pose();
    expected.translation[0] += 200.0;
    assert_eq!(
        reader.player_saved_transform(&fixture.context()),
        Ok(expected)
    );
    assert_eq!(SCENE_GETS.load(Ordering::SeqCst), 1);
    assert_eq!(OUTPUT_ALIGNMENT.load(Ordering::SeqCst), 0);
    assert_eq!(Fixture::mutation_calls(), 0);
    assert!(!reader.saved_mutated());
    assert!(!reader.activation_called());
}

#[test]
fn scene_owner_type_getter_and_transform_failures_have_no_record_side_effects() {
    let _lock = TEST_LOCK.lock().unwrap();
    for refusal in 0..9 {
        let fixture = Fixture::new();
        let reader = fixture.reader();
        let mut pose = Fixture::player_pose();
        match refusal {
            0 => fixture.pointer(
                fixture.scene + fixture.field("component_owner"),
                fixture.foreign_pawn,
            ),
            1 => {
                let wrong = reader
                    .pointer(fixture.base + fixture.facts.classes["character"])
                    .unwrap();
                fixture.pointer(fixture.scene + fixture.field("object_class"), wrong);
            }
            2 => GETTER_MODE.store(1, Ordering::SeqCst),
            3 => pose.rotation = [0.0; 4],
            4 => pose.translation[1] = f32::NAN,
            5 => pose.scale[2] = 0.0,
            6 => pose.translation[0] = 99_999_900.0,
            7 => put(fixture.base + 0x600, &[0x90]),
            _ => fixture.pointer(fixture.player_pawn + fixture.field("actor_root"), 0),
        }
        fixture.pose(fixture.base + 0xe000, &pose);
        assert!(
            reader.player_saved_transform(&fixture.context()).is_err(),
            "scene case {refusal}"
        );
        assert_eq!(Fixture::mutation_calls(), 0);
        assert!(!reader.saved_mutated());
        assert!(!reader.activation_called());
        if matches!(refusal, 0 | 1 | 7 | 8) {
            assert_eq!(SCENE_GETS.load(Ordering::SeqCst), 0);
        }
    }
}

#[test]
fn saved_record_primitive_uses_original_order_and_preflights_every_guard() {
    let _lock = TEST_LOCK.lock().unwrap();
    {
        let fixture = Fixture::new();
        let reader = fixture.reader();
        let desired = Fixture::player_pose();
        assert_eq!(fixture.saved_enlist(&reader, &desired), Ok(()));
        assert_eq!(TRACE.load(Ordering::SeqCst), 0x12345);
        assert_eq!(INPUT_ALIGNMENT.load(Ordering::SeqCst), 0);
        assert_eq!(NOTIFY.load(Ordering::SeqCst), 1);
        assert_eq!(KIND_VALUE.load(Ordering::SeqCst), 2);
        assert_eq!(
            reader.byte(fixture.character + fixture.field("busy_state")),
            Ok(3)
        );
        assert_eq!(
            unsafe {
                *(fixture
                    .character
                    .wrapping_add(fixture.field("record_transform"))
                    as *const SavedTransform)
            },
            desired
        );
        assert!(reader.saved_mutated());
        assert!(!reader.activation_called());
    }
    for name in [
        "record_set_transform",
        "set_saved_position_kind",
        "manager_add",
        "set_busy_state",
        "get_record_transform",
    ] {
        let fixture = Fixture::new();
        let reader = fixture.reader();
        put(fixture.base + fixture.facts.functions[name].rva, &[0x90]);
        assert_eq!(
            fixture.saved_enlist(&reader, &Fixture::player_pose()),
            Err(UNSUPPORTED),
            "guard {name}"
        );
        assert_eq!(Fixture::mutation_calls(), 0, "guard {name}");
        assert_eq!(RECORD_GETS.load(Ordering::SeqCst), 0);
        assert!(!reader.saved_mutated());
    }
    let fixture = Fixture::new();
    let reader = fixture.reader();
    let mut invalid = Fixture::player_pose();
    invalid.scale[0] = f32::INFINITY;
    assert_eq!(fixture.saved_enlist(&reader, &invalid), Err(BUSY));
    assert_eq!(Fixture::mutation_calls(), 0);
    assert!(!reader.saved_mutated());
}

#[test]
fn outside_base_restore_requests_saved_location_before_enrollment_and_stock_selection() {
    use crate::follower_state::{Document, Policy};
    let _lock = TEST_LOCK.lock().unwrap();
    for registered in [false, true] {
        let fixture = Fixture::new();
        let reader = fixture.reader();
        let context = fixture.context();
        fixture.unregistered();
        if registered {
            fixture.integer(fixture.followers + fixture.field("array") + 8, 1);
            FOLLOW_CODE.store(1, Ordering::SeqCst);
            FOLLOW_DYNAMIC.store(0, Ordering::SeqCst);
        }
        assert!(
            !Fixture::old_pose()
                .position()
                .near(&Fixture::player_pose().position())
        );
        assert_eq!(
            reader.restore(&context, &fixture.target, fixture.character, true),
            Ok(true)
        );
        assert_eq!(TRACE.load(Ordering::SeqCst), 0x9123456);
        assert_eq!(POSE_WRITES.load(Ordering::SeqCst), 1);
        assert_eq!(KIND_VALUE.load(Ordering::SeqCst), 2);
        assert_eq!(ADD_CALLS.load(Ordering::SeqCst), 1);
        assert_eq!(
            reader.integer(fixture.followers + fixture.field("array") + 8),
            Ok(1),
            "pointer deduplication is preserved"
        );
        assert_eq!(
            reader.saved_registration(&context, &fixture.target, fixture.character),
            Ok(true)
        );
        assert!(reader.saved_mutated());
        assert!(reader.activation_called());
        assert_eq!(reader.actor(fixture.character), Ok(None));
        let mut desired = Fixture::player_pose();
        desired.translation[0] += 200.0;
        assert_eq!(
            unsafe {
                *((fixture.character + fixture.field("record_transform")) as *const SavedTransform)
            },
            desired
        );
        let enlisted = reader.roster(&context).unwrap();
        let present = reader.present_roster(&context, &enlisted).unwrap();
        assert!(present.is_empty());
        let mut policy = Policy::new(Document::default()).unwrap();
        policy
            .observe_confirmed(&context.key, 1, &enlisted, &present)
            .unwrap();
        assert_eq!(
            policy.document().communities[&context.key],
            vec![fixture.target.clone()]
        );
        assert_eq!(
            policy.pending(),
            vec![fixture.target.clone()],
            "record capture does not confirm physical position or AI follow"
        );
    }
}

#[test]
fn saved_busy_and_task_protections_refuse_before_any_spatial_mutation() {
    let _lock = TEST_LOCK.lock().unwrap();
    for refusal in 0..11 {
        let fixture = Fixture::new();
        let reader = fixture.reader();
        fixture.unregistered();
        match refusal {
            0..=2 => put(
                fixture.character + fixture.field("busy_state"),
                &[[1, 2, 4][refusal]],
            ),
            3..=5 => ALLOWED_CODE.store([1, 2, 4][refusal - 3], Ordering::SeqCst),
            6 => FOLLOW_CODE.store(2, Ordering::SeqCst),
            7 => FOLLOW_CODE.store(1, Ordering::SeqCst),
            8 => {
                fixture.integer(fixture.followers + fixture.field("array") + 8, 1);
                FOLLOW_CODE.store(0, Ordering::SeqCst);
            }
            9 => put(
                fixture.character + fixture.field("record") + fixture.field("dead"),
                &[1],
            ),
            _ => {
                fixture.identity(fixture.other_character, &fixture.target);
                fixture.pointer(fixture.base + 0xa000, fixture.other_character);
                fixture.integer(fixture.followers + fixture.field("array") + 8, 1);
                FOLLOW_CODE.store(1, Ordering::SeqCst);
            }
        }
        let result = reader.restore(&fixture.context(), &fixture.target, fixture.character, true);
        assert!(
            result == Ok(false) || result.is_err(),
            "protection case {refusal}: {result:?}"
        );
        assert_eq!(Fixture::mutation_calls(), 0, "protection case {refusal}");
        assert_eq!(SCENE_GETS.load(Ordering::SeqCst), 0);
        assert!(!reader.saved_mutated());
        assert!(!reader.activation_called());
    }
}

#[test]
fn original_busy_transition_pose_override_is_reprepared_once_without_reenrollment() {
    let _lock = TEST_LOCK.lock().unwrap();
    let fixture = Fixture::new();
    let reader = fixture.reader();
    fixture.unregistered();
    BUSY_OVERWRITE.store(1, Ordering::SeqCst);
    assert_eq!(
        reader.restore(&fixture.context(), &fixture.target, fixture.character, true),
        Ok(true)
    );
    assert_eq!(TRACE.load(Ordering::SeqCst), 0x9123451256);
    assert_eq!(POSE_WRITES.load(Ordering::SeqCst), 2);
    assert_eq!(KIND_WRITES.load(Ordering::SeqCst), 2);
    assert_eq!(ADD_CALLS.load(Ordering::SeqCst), 1);
    assert_eq!(BUSY_WRITES.load(Ordering::SeqCst), 1);
    assert_eq!(RECORD_GETS.load(Ordering::SeqCst), 2);
    let mut expected = Fixture::player_pose();
    expected.translation[0] += 200.0;
    assert_eq!(
        unsafe {
            *((fixture.character + fixture.field("record_transform")) as *const SavedTransform)
        },
        expected
    );
    assert_eq!(reader.actor(fixture.character), Ok(None));
}

#[test]
fn post_add_context_failure_and_failed_pose_readback_cannot_claim_completion() {
    let _lock = TEST_LOCK.lock().unwrap();
    for failure in 0..4 {
        let fixture = Fixture::new();
        let reader = fixture.reader();
        let context = fixture.context();
        fixture.unregistered();
        let result = if failure < 2 {
            reader.enlist_saved_record(
                fixture.followers,
                fixture.character,
                &Fixture::player_pose(),
                || {
                    if failure == 0 {
                        return Err(BUSY);
                    }
                    fixture.pointer(
                        fixture.controller + fixture.field("pawn"),
                        fixture.foreign_pawn,
                    );
                    reader.revalidate(&context)
                },
            )
        } else {
            READBACK_MODE.store(failure - 1, Ordering::SeqCst);
            fixture.saved_enlist(&reader, &Fixture::player_pose())
        };
        assert!(result.is_err(), "post-mutation failure {failure}");
        assert!(reader.saved_mutated());
        assert!(!reader.activation_called());
        assert_eq!(ADD_CALLS.load(Ordering::SeqCst), 1);
        assert_eq!(CALLS.load(Ordering::SeqCst), 0);
        if failure < 2 {
            assert_eq!(TRACE.load(Ordering::SeqCst), 0x123);
            assert_eq!(BUSY_WRITES.load(Ordering::SeqCst), 0);
            assert_eq!(RECORD_GETS.load(Ordering::SeqCst), 0);
        } else if failure == 2 {
            assert_eq!(
                POSE_WRITES.load(Ordering::SeqCst),
                2,
                "at most one spatial reapplication"
            );
            assert_eq!(RECORD_GETS.load(Ordering::SeqCst), 2);
        } else {
            assert_eq!(POSE_WRITES.load(Ordering::SeqCst), 1);
            assert_eq!(RECORD_GETS.load(Ordering::SeqCst), 1);
        }
    }
}

#[test]
fn current_world_actor_uses_saved_record_sequence_without_duplicate_stock_activation() {
    let _lock = TEST_LOCK.lock().unwrap();
    let fixture = Fixture::new();
    let reader = fixture.reader();
    fixture.spawned_actor(fixture.pawn, fixture.character);
    fixture.pointer(
        fixture.character + fixture.field("character_component"),
        fixture.component,
    );
    assert_eq!(
        reader.restore(&fixture.context(), &fixture.target, fixture.character, true),
        Ok(true)
    );
    assert_eq!(TRACE.load(Ordering::SeqCst), 0x912345);
    assert_eq!(ADD_CALLS.load(Ordering::SeqCst), 1);
    assert_eq!(CALLS.load(Ordering::SeqCst), 0);
    assert_eq!(reader.actor(fixture.character), Ok(Some(fixture.pawn)));
    assert!(reader.saved_mutated());
    assert!(!reader.activation_called());
}

#[test]
fn delayed_actor_waits_for_exact_stock_tracking_before_entering_follow_processing() {
    let _lock = TEST_LOCK.lock().unwrap();
    for tracking_case in 0..5 {
        let fixture = Fixture::new();
        let context = fixture.context();
        let first_frame = fixture.reader();
        assert_eq!(
            first_frame.activate_record(
                fixture.list,
                fixture.world,
                &fixture.target,
                fixture.character,
                || first_frame.revalidate(&context),
            ),
            Ok(true),
        );
        assert_eq!(first_frame.actor(fixture.character), Ok(None));
        assert!(first_frame.activation_called());
        assert_eq!(CALLS.load(Ordering::SeqCst), 1);
        assert_eq!(TRACE.load(Ordering::SeqCst), 6);

        // A later authored frame publishes a reciprocal pawn. Its existence
        // does not manufacture the original category's tracking record.
        fixture.spawned_actor(fixture.pawn, fixture.character);
        fixture.pointer(
            fixture.character + fixture.field("character_component"),
            fixture.component,
        );
        let header = fixture.list + fixture.field("spawn_tracking");
        let count = match tracking_case {
            0 => 0,
            3 => 2,
            _ => 1,
        };
        fixture.integer(header + 8, count);
        fixture.integer(header + 12, count);
        for slot in 0..count {
            let row = fixture.tracking + slot as usize * fixture.field("spawn_tracking_stride");
            fixture.pointer(
                row + fixture.field("spawn_tracking_actor"),
                if tracking_case == 2 {
                    fixture.foreign_pawn
                } else {
                    fixture.pawn
                },
            );
            fixture.integer(
                row + fixture.field("spawn_tracking_index"),
                if tracking_case == 1 { 0 } else { 1 },
            );
        }
        let next_frame = fixture.reader();
        assert!(!next_frame.saved_mutated());
        assert!(!next_frame.activation_called());
        assert_eq!(next_frame.actor(fixture.character), Ok(Some(fixture.pawn)));
        let result = next_frame.resume_member(&context, &fixture.target, fixture.character, true);
        if tracking_case == 4 {
            assert_eq!(result, Ok(false));
            // With correct tracking, processing reaches the actual next gate.
            // The authored pawn has no AI controller, so no follow/teleport or
            // physical confirmation is invented by this fixture.
            assert_eq!(next_frame.stage(), "placement.follow-controller");
        } else {
            assert!(result == Ok(false) || result.is_err());
            assert_ne!(next_frame.stage(), "placement.follow-controller");
            if tracking_case != 2 {
                assert_eq!(next_frame.stage(), "resume.tracking-waiting");
            }
        }
        assert_eq!(CALLS.load(Ordering::SeqCst), 1, "no category resubmission");
        assert_eq!(
            Fixture::mutation_calls(),
            1,
            "no saved-pose or enrollment calls"
        );
        assert_eq!(SCENE_GETS.load(Ordering::SeqCst), 0);
        assert_eq!(RECORD_GETS.load(Ordering::SeqCst), 0);
        assert_eq!(TRACE.load(Ordering::SeqCst), 6);
        assert!(!next_frame.saved_mutated());
        assert!(!next_frame.activation_called());
    }
}
