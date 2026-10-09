//! Owned persistent follower service. Gameplay calls execute only on the engine thread.
use crate::{
    follower_access::{self, Context, Reader},
    follower_state::{Document, Identity, Policy},
};
use sod2se_abi::{BUSY, INTERNAL, INVALID, STALE, UNSUPPORTED};
use sod2se_services::{diagnostics::Logger, state::Store};
use std::{
    collections::{BTreeMap, BTreeSet},
    ffi::c_void,
    ptr,
    sync::{
        Arc, Mutex,
        atomic::{AtomicUsize, Ordering},
    },
    time::{Duration, Instant},
};
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;

type Tick = unsafe extern "system-unwind" fn(*mut c_void, u32, f32);
type Save = unsafe extern "system-unwind" fn(*mut c_void, *mut c_void, *mut c_void);
type Dismiss = unsafe extern "system-unwind" fn(*mut c_void, *mut c_void);
static TICK: AtomicUsize = AtomicUsize::new(0);
static SAVE: AtomicUsize = AtomicUsize::new(0);
static DISMISS: AtomicUsize = AtomicUsize::new(0);
static CALLS: AtomicUsize = AtomicUsize::new(0);
static BINDING: Mutex<Option<Binding>> = Mutex::new(None);
static HOOKS: Mutex<Option<Hooks>> = Mutex::new(None);
unsafe extern "system" {
    fn MH_Initialize() -> i32;
    fn MH_CreateHook(target: *mut c_void, detour: *mut c_void, original: *mut *mut c_void) -> i32;
    fn MH_EnableHook(target: *mut c_void) -> i32;
    fn MH_DisableHook(target: *mut c_void) -> i32;
    fn MH_RemoveHook(target: *mut c_void) -> i32;
}
struct Flight;
impl Flight {
    fn enter() -> Self {
        CALLS.fetch_add(1, Ordering::Acquire);
        Self
    }
}
impl Drop for Flight {
    fn drop(&mut self) {
        CALLS.fetch_sub(1, Ordering::Release);
    }
}

struct Site {
    address: usize,
    original: Vec<u8>,
    patched: Vec<u8>,
    enabled: bool,
}
struct Hooks {
    sites: Vec<Site>,
    poisoned: bool,
}
impl Hooks {
    fn install(&mut self, reader: &Reader) -> Result<(), i32> {
        let mut targets = Vec::new();
        for name in ["tick", "save", "dismiss"] {
            targets.push(reader.function(name)?);
        }
        self.install_targets(targets)
    }
    // Production callers validate executable ownership, image and guards first.
    // Inert tests use authored executable pages to exercise actual MinHook rollback.
    fn install_targets(&mut self, targets: Vec<usize>) -> Result<(), i32> {
        if targets.len() != 3 {
            return Err(INVALID);
        }
        if ![0, 1].contains(&unsafe { MH_Initialize() }) {
            return Err(INTERNAL);
        }
        for (index, address) in targets.into_iter().enumerate() {
            let callback = [
                tick as *mut c_void,
                save as *mut c_void,
                dismiss as *mut c_void,
            ][index];
            let original_bytes = follower_access::read(address, 16)?;
            let mut original = ptr::null_mut();
            if unsafe { MH_CreateHook(address as *mut c_void, callback, &mut original) } != 0 {
                return Err(INTERNAL);
            }
            [&TICK, &SAVE, &DISMISS][index].store(original as usize, Ordering::Release);
            self.sites.push(Site {
                address,
                original: original_bytes,
                patched: Vec::new(),
                enabled: false,
            });
            if unsafe { MH_EnableHook(address as *mut c_void) } != 0 {
                return Err(INTERNAL);
            }
            self.sites[index].enabled = true;
            self.sites[index].patched = follower_access::read(address, 16)?;
        }
        Ok(())
    }
    fn withdraw(&mut self) -> Result<(), i32> {
        if self.poisoned {
            return Err(UNSUPPORTED);
        }
        for site in &self.sites {
            let expected = if site.enabled {
                &site.patched
            } else {
                &site.original
            };
            if expected.len() != 16 || follower_access::read(site.address, 16)? != *expected {
                self.poisoned = true;
                return Err(UNSUPPORTED);
            }
        }
        for site in &self.sites {
            let result = unsafe { MH_DisableHook(site.address as *mut c_void) };
            if ![0, 6].contains(&result) {
                self.poisoned = true;
                return Err(INTERNAL);
            }
        }
        let deadline = Instant::now() + Duration::from_secs(2);
        while CALLS.load(Ordering::Acquire) != 0 {
            if Instant::now() >= deadline {
                self.poisoned = true;
                return Err(BUSY);
            }
            std::thread::sleep(Duration::from_millis(1));
        }
        for site in &self.sites {
            if unsafe { MH_RemoveHook(site.address as *mut c_void) } != 0 {
                self.poisoned = true;
                return Err(INTERNAL);
            }
        }
        self.sites.clear();
        Ok(())
    }
}
struct Retry {
    cursor: usize,
    next: Instant,
    activation_attempts: u8,
    activation_after: Instant,
    waiting_stage: Option<&'static str>,
}
impl Retry {
    fn new(now: Instant) -> Self {
        Self {
            cursor: 0,
            next: now,
            activation_attempts: 0,
            activation_after: now,
            waiting_stage: None,
        }
    }
    fn allow_activation(&self, now: Instant) -> bool {
        self.activation_attempts < 3 && now >= self.activation_after
    }
    fn record_resume(&mut self, now: Instant, saved_mutated: bool, activation_called: bool) {
        if saved_mutated || activation_called {
            // Record actual original calls even if later context/readback
            // checks refuse the result. Both calls in one operation consume
            // one shared attempt; getters and preflight refusals consume none.
            self.activation_attempts = (self.activation_attempts + 1).min(3);
            self.activation_after = now + Duration::from_secs(5 << (self.activation_attempts - 1));
        }
    }
}
struct Binding {
    owner: u64,
    module: String,
    store: Arc<Mutex<Store>>,
    logger: Arc<Logger>,
    policy: Policy,
    revision: u64,
    epoch: u64,
    world: usize,
    retries: BTreeMap<Identity, Retry>,
    round_robin: usize,
    error: i32,
    error_stage: &'static str,
    reported_pending: Option<usize>,
    placement_scope: Option<(String, usize)>,
    placement: BTreeSet<Identity>,
    persisted: u64,
    submissions: u64,
    suspended: bool,
}
impl Binding {
    fn leave_context(&mut self, stage: &'static str) {
        self.policy.leave();
        // Only an observed menu/loading boundary starts a fresh restoration
        // session. A temporary missing pawn must retain completed placement
        // and the bounded retry budget of this session.
        if matches!(
            stage,
            "context.local-player"
                | "context.controller"
                | "context.loading-screen"
                | "context.game-instance"
        ) {
            self.world = 0;
            self.placement_scope = None;
            self.placement.clear();
            self.retries.clear();
            self.round_robin = 0;
        }
    }
    fn track_placement(&mut self, key: &str, world: usize, vanilla: i32) {
        if self
            .placement_scope
            .as_ref()
            .is_none_or(|(saved, previous)| saved != key || *previous != world)
        {
            self.placement_scope = Some((key.into(), world));
            // The manager can retain process-local registrations across a
            // menu reload. Use the vanilla load identity, not cached membership.
            self.placement = self
                .policy
                .document()
                .communities
                .get(key)
                .into_iter()
                .flatten()
                .filter(|id| id.id != vanilla)
                .cloned()
                .collect();
        }
        self.placement.retain(|id| {
            self.policy
                .document()
                .communities
                .get(key)
                .is_some_and(|saved| saved.contains(id))
        });
    }
    fn pending(&self) -> Vec<Identity> {
        self.policy
            .pending()
            .into_iter()
            .chain(self.placement.iter().cloned())
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect()
    }
    fn flush(&mut self) -> Result<(), i32> {
        if !self.policy.dirty() {
            return Ok(());
        }
        let store = self.store.try_lock().map_err(|_| BUSY)?;
        let value = serde_json::to_value(self.policy.document()).map_err(|_| INVALID)?;
        self.revision = store.write(&self.module, 1, self.revision, value)?;
        self.policy.committed();
        self.persisted += 1;
        let saved = self
            .policy
            .document()
            .communities
            .values()
            .map(Vec::len)
            .sum::<usize>();
        let _ = self.logger.write(1, &self.module, "FOLLOWER_STATE_COMMITTED",
            &format!("Roster journal committed; revision={}; saved_total={saved}; pending={}; no identities exposed",
                self.revision, self.policy.pending().len()));
        Ok(())
    }
    fn report(&mut self, error: i32, stage: &'static str) {
        let stage = if error == 0 { "ready" } else { stage };
        let pending = self.pending().len();
        if self.error != error
            || self.error_stage != stage
            || self.reported_pending != Some(pending)
        {
            self.error = error;
            self.error_stage = stage;
            self.reported_pending = Some(pending);
            let _ = self.logger.write(
                if error == 0 { 1 } else { 3 },
                &self.module,
                if error == 0 {
                    "FOLLOWER_STATE_READY"
                } else {
                    "FOLLOWER_STATE_REFUSED"
                },
                &format!(
                    "Persistence status={error}; stage={stage}; pending={}; no identities exposed",
                    self.pending().len()
                ),
            );
        }
    }
    fn observe(&mut self, reader: &Reader, context: &Context) -> Result<Vec<Identity>, i32> {
        let live = reader.roster(context)?;
        let present = reader.present_roster(context, &live)?;
        reader.checkpoint("state.observe");
        self.observe_snapshot(context, live, present)
    }
    fn observe_snapshot(
        &mut self,
        context: &Context,
        mut live: Vec<Identity>,
        mut present: Vec<Identity>,
    ) -> Result<Vec<Identity>, i32> {
        // A cached manager may still list the controlled survivor as a
        // follower. Filter before capture so stable frames do not insert and
        // remove the same identity, dirtying an unchanged journal each time.
        live.retain(|id| id != &context.controlled);
        present.retain(|id| id != &context.controlled);
        if self.world != context.world {
            self.world = context.world;
            self.epoch = self.epoch.checked_add(1).ok_or(INTERNAL)?;
            self.retries.clear();
            self.round_robin = 0;
        }
        self.policy
            .observe_confirmed(&context.key, self.epoch, &live, &present)?;
        self.policy.forget(
            &context.key,
            self.epoch,
            std::slice::from_ref(&context.controlled),
        )?;
        self.track_placement(&context.key, context.world, context.vanilla_follower);
        Ok(live)
    }
    fn frame(&mut self, reader: &Reader, world: usize) -> Result<bool, i32> {
        if self.suspended {
            return Err(UNSUPPORTED);
        }
        // The producer also ticks preview/secondary worlds. They must not reset
        // an active session or its retry cursors/cooldowns.
        if reader.engine_thread().is_err() {
            return Ok(false);
        }
        if reader.current_world().is_ok_and(|active| active != world) {
            return Ok(false);
        }
        let context = match reader.context(world) {
            Ok(context) => context,
            Err(code) => {
                let stage = reader.stage();
                self.leave_context(stage);
                reader.checkpoint("state.commit");
                self.flush()?;
                reader.checkpoint(stage);
                return Err(code);
            }
        };
        let enlisted = self.observe(reader, &context)?;
        // Commit newly enlisted identities before issuing any restore request.
        // A failed state commit suspends new gameplay requests and retains dirty data.
        reader.checkpoint("state.commit");
        self.flush()?;
        let pending = self.pending();
        self.retries
            .retain(|identity, _| pending.contains(identity));
        if !pending.is_empty() {
            let identity = pending[self.round_robin % pending.len()].clone();
            self.round_robin = self.round_robin.wrapping_add(1);
            let retry = self
                .retries
                .entry(identity.clone())
                .or_insert_with(|| Retry::new(Instant::now()));
            if Instant::now() >= retry.next
                && let Some(character) = reader.lookup(&context, &identity, &mut retry.cursor)?
            {
                let placing = self.placement.contains(&identity) && enlisted.contains(&identity);
                let now = Instant::now();
                let allow_activation = retry.allow_activation(now);
                let result = if placing {
                    reader.resume_member(&context, &identity, character, allow_activation)
                } else {
                    reader.restore(&context, &identity, character, allow_activation)
                };
                let saved_mutated = reader.saved_mutated();
                let activation_called = reader.activation_called();
                retry.record_resume(now, saved_mutated, activation_called);
                if saved_mutated {
                    let _ = self.logger.write(1, &self.module, "FOLLOWER_SAVED_POSITION_SUBMITTED",
                        &format!("Original saved-record position restoration called; attempt={}/3; pending={}; awaiting roster/location/follow confirmation; no identities exposed",
                            retry.activation_attempts, pending.len()));
                }
                if activation_called {
                    let _ = self.logger.write(1, &self.module, "FOLLOWER_ACTIVATION_SUBMITTED",
                        &format!("Original existing-record activation called; attempt={}/3; pending={}; awaiting actor/location/follow confirmation; no identities exposed",
                            retry.activation_attempts, pending.len()));
                }
                retry.next = Instant::now() + Duration::from_secs(1);
                match result {
                    Ok(submitted) => {
                        if !submitted && retry.waiting_stage != Some(reader.stage()) {
                            retry.waiting_stage = Some(reader.stage());
                            let _ = self.logger.write(1, &self.module, "FOLLOWER_RESTORE_WAITING", &format!("Restoration waiting; stage={}; pending={}; no identities exposed", reader.stage(), pending.len()));
                        }
                        if submitted && placing {
                            self.placement.remove(&identity);
                            let _ = self.logger.write(1, &self.module, "FOLLOWER_PLACEMENT_CONFIRMED", "Restored follower is near the current player with its original AI follow target; no identities exposed");
                        } else if submitted {
                            self.submissions += 1;
                            let _ = self.logger.write(1, &self.module, "FOLLOWER_RESTORE_SUBMITTED",
                                &format!("Original enlist request submitted; requests={}; pending={}; awaiting live roster confirmation",
                                    self.submissions, pending.len()));
                        }
                    }
                    Err(code) if code == sod2se_abi::NOT_FOUND => {
                        reader.checkpoint("state.remove-dead");
                        self.policy.forget(&context.key, self.epoch, &[identity])?;
                        self.placement.retain(|id| {
                            self.policy
                                .document()
                                .communities
                                .get(&context.key)
                                .is_some_and(|saved| saved.contains(id))
                        });
                        reader.checkpoint("state.commit");
                        self.flush()?;
                    }
                    Err(code) => return Err(code),
                }
            }
        }
        Ok(true)
    }
}
fn reader() -> Result<Reader, i32> {
    Reader::new(unsafe { GetModuleHandleW(ptr::null()) } as usize)
}
fn current_context(reader: &Reader) -> Result<Context, i32> {
    reader.context(reader.current_world()?)
}
unsafe extern "system-unwind" fn tick(world: *mut c_void, kind: u32, delta: f32) {
    let _flight = Flight::enter();
    let original: Tick = unsafe { std::mem::transmute(TICK.load(Ordering::Acquire)) };
    unsafe { original(world, kind, delta) };
    let _ = std::panic::catch_unwind(|| {
        if let Ok(mut binding) = BINDING.try_lock()
            && let Some(binding) = binding.as_mut()
        {
            match reader() {
                Ok(reader) => match binding.frame(&reader, world as usize) {
                    Ok(true) => binding.report(0, "ready"),
                    Ok(false) => {}
                    Err(code) => binding.report(code, reader.stage()),
                },
                Err(code) => binding.report(code, "bindings"),
            }
        }
    });
}
unsafe extern "system-unwind" fn save(
    component: *mut c_void,
    user_payload: *mut c_void,
    community_payload: *mut c_void,
) {
    let _flight = Flight::enter();
    let _ = std::panic::catch_unwind(|| {
        if let Ok(mut binding) = BINDING.try_lock()
            && let Some(binding) = binding.as_mut()
        {
            let mut stage = "bindings";
            let result = reader().and_then(|reader| {
                let result = (|| {
                    let context = current_context(&reader)?;
                    if context.community != component as usize {
                        return Err(STALE);
                    }
                    // These arguments are raw vanilla save-record payloads,
                    // not UObjects. The owning component and qualified active
                    // context supply the community identity; never reinterpret
                    // a record buffer as DaytonSaveGame.
                    binding.observe(&reader, &context)?;
                    reader.checkpoint("state.commit");
                    binding.flush()
                })();
                stage = reader.stage();
                result
            });
            binding.report(result.err().unwrap_or(0), stage);
        }
    });
    let original: Save = unsafe { std::mem::transmute(SAVE.load(Ordering::Acquire)) };
    unsafe { original(component, user_payload, community_payload) };
}
unsafe extern "system-unwind" fn dismiss(dialogue: *mut c_void, pawn: *mut c_void) {
    let _flight = Flight::enter();
    let before = std::panic::catch_unwind(|| {
        reader().and_then(|reader| {
            let context = current_context(&reader)?;
            if context.dialogue != dialogue as usize {
                return Err(STALE);
            }
            let live = reader.roster(&context)?;
            Ok((context.key, context.world, live))
        })
    })
    .ok()
    .and_then(Result::ok);
    let original: Dismiss = unsafe { std::mem::transmute(DISMISS.load(Ordering::Acquire)) };
    unsafe { original(dialogue, pawn) };
    let _ = std::panic::catch_unwind(|| {
        if let Some((key, world, before)) = before
            && let Ok(mut binding) = BINDING.try_lock()
            && let Some(binding) = binding.as_mut()
        {
            let mut stage = "bindings";
            let result = reader().and_then(|reader| {
                let result = (|| {
                    let context = current_context(&reader)?;
                    if context.key != key || context.world != world {
                        return Err(STALE);
                    }
                    let live = binding.observe(&reader, &context)?;
                    let removed: Vec<_> = before
                        .into_iter()
                        .filter(|identity| !live.contains(identity))
                        .collect();
                    binding.policy.forget(&key, binding.epoch, &removed)?;
                    reader.checkpoint("state.commit");
                    binding.flush()
                })();
                stage = reader.stage();
                result
            });
            binding.report(result.err().unwrap_or(0), stage);
        }
    });
}

pub fn acquire(
    owner: u64,
    module: String,
    store: Arc<Mutex<Store>>,
    logger: Arc<Logger>,
) -> Result<(), i32> {
    crate::process::verify_current()?;
    if owner == 0 {
        return Err(INVALID);
    }
    let mut binding = BINDING.lock().map_err(|_| INTERNAL)?;
    if binding.is_some() {
        return Err(BUSY);
    }
    let document = store.lock().map_err(|_| INTERNAL)?.read(&module, 1)?;
    let value = if document.value.is_null() {
        Document::default()
    } else {
        serde_json::from_value(document.value).map_err(|_| INVALID)?
    };
    let policy = Policy::new(value)?;
    let mut hooks = HOOKS.lock().map_err(|_| INTERNAL)?;
    if hooks.is_some() {
        return Err(BUSY);
    }
    *hooks = Some(Hooks {
        sites: Vec::new(),
        poisoned: false,
    });
    let installation = hooks.as_mut().ok_or(INTERNAL)?.install(&reader()?);
    if let Err(code) = installation {
        if hooks.as_mut().ok_or(INTERNAL)?.withdraw().is_ok() {
            *hooks = None;
        }
        return Err(code);
    }
    *binding = Some(Binding {
        owner,
        module,
        store,
        logger,
        policy,
        revision: document.revision,
        epoch: 0,
        world: 0,
        retries: BTreeMap::new(),
        round_robin: 0,
        error: 0,
        error_stage: "initializing",
        reported_pending: None,
        placement_scope: None,
        placement: BTreeSet::new(),
        persisted: 0,
        submissions: 0,
        suspended: false,
    });
    Ok(())
}
pub fn owned_by(owner: u64) -> bool {
    BINDING
        .lock()
        .ok()
        .and_then(|binding| binding.as_ref().map(|b| b.owner == owner))
        .unwrap_or(false)
}
pub fn status(owner: u64) -> Result<serde_json::Value, i32> {
    let binding = BINDING.try_lock().map_err(|_| BUSY)?;
    let binding = binding
        .as_ref()
        .filter(|b| b.owner == owner)
        .ok_or(INVALID)?;
    Ok(
        serde_json::json!({"active":!binding.suspended,"pending":binding.pending().len(),"error":binding.error,
        "stage":binding.error_stage,"persisted":binding.persisted,"submissions":binding.submissions,"live_acceptance":"NOT_RUN"}),
    )
}
pub fn release(owner: u64) -> Result<(), i32> {
    let mut binding = BINDING.lock().map_err(|_| INTERNAL)?;
    let active = binding
        .as_mut()
        .filter(|b| b.owner == owner)
        .ok_or(INVALID)?;
    active.flush()?;
    active.suspended = true;
    let suspended = binding.take().ok_or(INVALID)?;
    drop(binding);
    let mut hooks = HOOKS.lock().map_err(|_| INTERNAL)?;
    if let Some(active) = hooks.as_mut()
        && let Err(code) = active.withdraw()
    {
        drop(hooks);
        let mut binding = BINDING.lock().map_err(|_| INTERNAL)?;
        *binding = Some(suspended);
        if let Some(active) = binding.as_mut() {
            active.report(code, "release.hooks");
        }
        return Err(code);
    }
    *hooks = None;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;
    use std::sync::atomic::AtomicU64;
    static NEXT: AtomicU64 = AtomicU64::new(0);
    const KEY: &str = "1234567890abcdef1234567890abcdef";
    fn member(id: i32) -> Identity {
        Identity {
            id,
            narrative: 100 + id as u64,
            entity: 200 + id as u64,
        }
    }
    fn context(controlled: Identity) -> Context {
        Context {
            world: 42,
            controller: 0,
            pawn: 0,
            dialogue: 0,
            community: 0,
            game: 0,
            manager: 0,
            key: KEY.into(),
            controlled,
            vanilla_follower: 1,
        }
    }
    fn root() -> PathBuf {
        std::env::temp_dir().join(format!(
            "sod2se-follower-journal-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ))
    }
    fn binding(root: &std::path::Path) -> Binding {
        Binding {
            owner: 1,
            module: "unlimited-followers".into(),
            store: Arc::new(Mutex::new(Store::open(root).unwrap())),
            logger: Arc::new(Logger::new(root.join("diagnostic.jsonl"))),
            policy: Policy::new(Document::default()).unwrap(),
            revision: 0,
            epoch: 1,
            world: 0,
            retries: BTreeMap::new(),
            round_robin: 0,
            error: 0,
            error_stage: "initializing",
            reported_pending: None,
            placement_scope: None,
            placement: BTreeSet::new(),
            persisted: 0,
            submissions: 0,
            suspended: false,
        }
    }
    #[test]
    fn actual_journal_survives_restart_partial_restore_and_explicit_dismissal() {
        let root = root();
        let roster = vec![member(1), member(2), member(3)];
        {
            let mut session = binding(&root);
            session.policy.observe(KEY, 1, &roster).unwrap();
            session.flush().unwrap();
            assert_eq!(session.revision, 1);
            assert!(!session.policy.dirty());
        }
        {
            let mut next = binding(&root);
            let stored = next.store.lock().unwrap().read(&next.module, 1).unwrap();
            next.revision = stored.revision;
            next.policy = Policy::new(serde_json::from_value(stored.value).unwrap()).unwrap();
            next.policy.observe(KEY, 2, &[member(1)]).unwrap();
            assert_eq!(next.policy.pending(), vec![member(2), member(3)]);
            next.flush().unwrap();
            assert_eq!(
                next.revision, 1,
                "partial restore must not replace the saved full roster"
            );
            next.policy.forget(KEY, 2, &[member(3)]).unwrap();
            next.flush().unwrap();
            assert_eq!(next.revision, 2);
        }
        {
            let store = Store::open(&root).unwrap();
            let document: Document =
                serde_json::from_value(store.read("unlimited-followers", 1).unwrap().value)
                    .unwrap();
            assert_eq!(document.communities[KEY], vec![member(1), member(2)]);
        }
        assert!(root.starts_with(std::env::temp_dir()));
        std::fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn ordinary_zero_narrative_roster_is_committed_and_restored_from_the_actual_journal() {
        let root = root();
        let roster: Vec<_> = (1..=3)
            .map(|id| Identity {
                id,
                narrative: 0,
                entity: 0,
            })
            .collect();
        {
            let mut first = binding(&root);
            first.policy.observe(KEY, 1, &roster).unwrap();
            first.flush().unwrap();
            assert_eq!(first.revision, 1);
        }
        {
            let mut next = binding(&root);
            let saved = next.store.lock().unwrap().read(&next.module, 1).unwrap();
            next.revision = saved.revision;
            next.policy = Policy::new(serde_json::from_value(saved.value).unwrap()).unwrap();
            next.policy.observe(KEY, 2, &roster[..1]).unwrap();
            assert_eq!(next.policy.pending(), roster[1..]);
            next.flush().unwrap();
            assert_eq!(
                next.revision, 1,
                "vanilla restores one; the remaining two must stay saved"
            );
            next.policy.observe(KEY, 2, &roster).unwrap();
            assert!(next.policy.pending().is_empty());
            next.flush().unwrap();
            assert_eq!(next.revision, 1);
        }
        let saved = Store::open(&root)
            .unwrap()
            .read("unlimited-followers", 1)
            .unwrap();
        let document: Document = serde_json::from_value(saved.value).unwrap();
        assert_eq!(document.communities[KEY], roster);
        assert!(root.starts_with(std::env::temp_dir()));
        std::fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn placement_waits_after_actor_loading_preserves_vanilla_and_respects_dismissal() {
        let root = root();
        {
            let mut session = binding(&root);
            let roster = vec![member(1), member(2), member(3)];
            session.policy.observe(KEY, 1, &roster).unwrap();
            session.flush().unwrap();
            session.policy.leave();
            session
                .policy
                .observe_confirmed(KEY, 2, &roster[..1], &roster[..1])
                .unwrap();
            session.track_placement(KEY, 42, 1);
            assert!(
                !session.placement.contains(&member(1)),
                "vanilla member is never positioned by this queue"
            );
            assert_eq!(session.pending(), roster[1..]);
            session
                .policy
                .observe_confirmed(KEY, 2, &roster, &roster)
                .unwrap();
            session.track_placement(KEY, 42, 1);
            assert!(session.policy.pending().is_empty());
            assert_eq!(
                session.pending(),
                roster[1..],
                "actor presence cannot finish placement"
            );
            session.placement.remove(&member(2));
            assert_eq!(session.pending(), vec![member(3)]);
            session.policy.forget(KEY, 2, &[member(3)]).unwrap();
            session.track_placement(KEY, 42, 1);
            assert!(
                session.pending().is_empty(),
                "dismissed members cannot be repositioned or re-enlisted"
            );
            session
                .policy
                .observe(KEY, 2, &[member(1), member(2), member(4)])
                .unwrap();
            session.track_placement(KEY, 42, 1);
            assert!(
                session.placement.is_empty(),
                "normal new recruitment during play is not a load-placement event"
            );
        }
        assert!(root.starts_with(std::env::temp_dir()));
        std::fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn menu_reload_with_cached_membership_restarts_extra_placement_and_excludes_player() {
        let root = root();
        {
            let mut session = binding(&root);
            let roster = vec![member(1), member(2), member(3)];
            session.policy.observe(KEY, 1, &roster).unwrap();
            session.flush().unwrap();
            let mut context = context(member(9));
            // Manager membership survives, while only vanilla's first actor is
            // present after this same-process menu load.
            session.leave_context("context.loading-screen");
            session
                .observe_snapshot(&context, roster.clone(), roster[..1].to_vec())
                .unwrap();
            assert_eq!(
                session.placement.iter().cloned().collect::<Vec<_>>(),
                roster[1..]
            );
            session
                .observe_snapshot(&context, roster.clone(), roster.clone())
                .unwrap();
            assert_eq!(
                session.pending(),
                roster[1..],
                "cached membership cannot bypass near-player work"
            );
            // A qualified current player cannot also be a persisted follower.
            context.controlled = member(2);
            session
                .observe_snapshot(&context, roster.clone(), roster.clone())
                .unwrap();
            assert_eq!(session.pending(), vec![member(3)]);
            session.placement.remove(&member(3));
            assert!(session.pending().is_empty());
            session.leave_context("context.controller");
            session
                .observe_snapshot(&context, vec![member(1), member(3)], vec![member(1)])
                .unwrap();
            assert_eq!(
                session.pending(),
                vec![member(3)],
                "same address/key after menu still starts a new load queue"
            );
            session
                .policy
                .forget(KEY, session.epoch, &[member(3)])
                .unwrap();
            session.track_placement(KEY, 42, 1);
            assert!(session.pending().is_empty());
        }
        assert!(root.starts_with(std::env::temp_dir()));
        std::fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn controlled_cached_member_is_removed_once_and_stable_frames_do_not_commit() {
        let root = root();
        {
            let mut session = binding(&root);
            let roster = vec![member(1), member(2), member(3)];
            session.policy.observe(KEY, 1, &roster).unwrap();
            session.flush().unwrap();
            let context = context(member(2));
            for _ in 0..100 {
                let live = session
                    .observe_snapshot(&context, roster.clone(), roster.clone())
                    .unwrap();
                assert_eq!(live, vec![member(1), member(3)]);
                session.flush().unwrap();
            }
            assert_eq!(session.revision, 2);
            assert_eq!(session.persisted, 2);
            assert_eq!(
                session.policy.document().communities[KEY],
                vec![member(1), member(3)]
            );
            assert!(!session.policy.dirty());
            let saved = session
                .store
                .lock()
                .unwrap()
                .read(&session.module, 1)
                .unwrap();
            let document: Document = serde_json::from_value(saved.value).unwrap();
            assert_eq!(document.communities[KEY], vec![member(1), member(3)]);
        }
        assert!(root.starts_with(std::env::temp_dir()));
        std::fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn menu_boundaries_reset_retries_and_rebuild_completed_placement_at_same_world_address() {
        let root = root();
        {
            let mut session = binding(&root);
            let context = context(member(9));
            let roster = vec![member(1), member(2), member(3)];
            for stage in [
                "context.local-player",
                "context.controller",
                "context.loading-screen",
                "context.game-instance",
            ] {
                session
                    .observe_snapshot(&context, roster.clone(), roster.clone())
                    .unwrap();
                session.placement.remove(&member(2));
                session.placement.remove(&member(3));
                assert!(session.pending().is_empty());
                session
                    .retries
                    .insert(member(3), Retry::new(Instant::now()));
                session.round_robin = 17;
                let epoch = session.epoch;
                session.leave_context(stage);
                assert_eq!(session.world, 0);
                assert!(session.placement_scope.is_none());
                assert!(session.retries.is_empty());
                assert_eq!(session.round_robin, 0);
                session
                    .observe_snapshot(&context, roster.clone(), roster[..1].to_vec())
                    .unwrap();
                assert_eq!(session.epoch, epoch + 1);
                assert_eq!(session.pending(), roster[1..]);
                assert_eq!(session.policy.document().communities[KEY], roster);
            }
        }
        assert!(root.starts_with(std::env::temp_dir()));
        std::fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn temporary_pawn_loss_keeps_completed_placement_and_activation_budget() {
        let root = root();
        {
            let mut session = binding(&root);
            let context = context(member(9));
            let roster = vec![member(1), member(2), member(3)];
            session
                .observe_snapshot(&context, roster.clone(), roster.clone())
                .unwrap();
            session.placement.remove(&member(2));
            let now = Instant::now();
            let mut retry = Retry::new(now);
            retry.record_resume(now, false, true);
            let deadline = retry.activation_after;
            session.retries.insert(member(3), retry);
            let epoch = session.epoch;
            session.leave_context("context.pawn");
            session
                .observe_snapshot(&context, roster.clone(), roster.clone())
                .unwrap();
            assert_eq!(session.epoch, epoch);
            assert_eq!(session.pending(), vec![member(3)]);
            assert!(!session.placement.contains(&member(2)));
            assert_eq!(session.retries[&member(3)].activation_attempts, 1);
            assert_eq!(session.retries[&member(3)].activation_after, deadline);
            session.placement.remove(&member(3));
            session.leave_context("context.pawn");
            session
                .observe_snapshot(&context, roster.clone(), roster)
                .unwrap();
            assert!(session.pending().is_empty());
        }
        assert!(root.starts_with(std::env::temp_dir()));
        std::fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn activation_retries_are_bounded_back_off_and_keep_observing_delayed_actors() {
        let now = Instant::now();
        let mut retry = Retry::new(now);
        // Missing lists/actors, failed preflight and getter-only observations
        // produce neither native mutation marker, even during a long load.
        for seconds in [0, 1, 5, 15, 30] {
            retry.record_resume(now + Duration::from_secs(seconds), false, false);
        }
        assert_eq!(retry.activation_attempts, 0);
        assert!(retry.allow_activation(now));
        let now = now + Duration::from_secs(30);
        retry.record_resume(now, false, false);
        assert_eq!(retry.activation_attempts, 0);
        assert!(
            retry.allow_activation(now),
            "loading beyond 15 seconds cannot exhaust native attempts"
        );
        retry.record_resume(now, false, true);
        assert_eq!(retry.activation_attempts, 1);
        assert!(!retry.allow_activation(now + Duration::from_millis(4999)));
        let second = now + Duration::from_secs(5);
        assert!(retry.allow_activation(second));
        retry.record_resume(second, false, false);
        assert_eq!(retry.activation_attempts, 1);
        assert!(retry.allow_activation(second));
        // Native activation happened; a failed post-call readback cannot hide it.
        retry.record_resume(second, false, true);
        assert_eq!(retry.activation_attempts, 2);
        assert!(!retry.allow_activation(second + Duration::from_millis(9999)));
        let third = second + Duration::from_secs(10);
        assert!(retry.allow_activation(third));
        retry.record_resume(third, false, true);
        assert_eq!(retry.activation_attempts, 3);
        let later = third + Duration::from_secs(60);
        assert!(!retry.allow_activation(later));
        retry.record_resume(later, false, false);
        assert_eq!(
            retry.activation_attempts, 3,
            "a delayed actor can still confirm placement"
        );
    }
    #[test]
    fn saved_restore_and_existing_resume_results_share_the_native_activation_budget() {
        let now = Instant::now();
        let mut retry = Retry::new(now);
        // A bare saved-original-record-submitted status has no marker and
        // cannot consume the budget. Both routes use this production recorder.
        retry.record_resume(now, false, false);
        assert_eq!(retry.activation_attempts, 0);
        assert!(retry.allow_activation(now));

        // Saved-record restoration has already called its original transform
        // setter, even if the later roster/context readback refuses the result.
        retry.record_resume(now, true, false);
        assert_eq!(retry.activation_attempts, 1);
        assert!(!retry.allow_activation(now + Duration::from_millis(4999)));

        // Once enlisted, the existing-member route inherits the same budget.
        let second = now + Duration::from_secs(5);
        retry.record_resume(second, false, true);
        assert_eq!(retry.activation_attempts, 2);
        assert!(!retry.allow_activation(second + Duration::from_millis(9999)));
        retry.record_resume(second, false, false);
        assert_eq!(retry.activation_attempts, 2);

        let third = second + Duration::from_secs(10);
        // A single operation may call both original paths, but is one attempt.
        retry.record_resume(third, true, true);
        assert_eq!(retry.activation_attempts, 3);
        assert!(!retry.allow_activation(third + Duration::from_secs(60)));
        // An actor from either route may still stream and confirm later.
        retry.record_resume(third, false, false);
        assert_eq!(retry.activation_attempts, 3);
    }
    #[test]
    fn combined_original_mutations_consume_one_attempt_and_getters_consume_none() {
        let now = Instant::now();
        for (saved_mutated, activation_called) in [(true, false), (false, true), (true, true)] {
            let mut retry = Retry::new(now);
            retry.record_resume(now, saved_mutated, activation_called);
            assert_eq!(retry.activation_attempts, 1);
            assert_eq!(retry.activation_after, now + Duration::from_secs(5));
            for seconds in [1, 5, 30, 60] {
                retry.record_resume(now + Duration::from_secs(seconds), false, false);
            }
            assert_eq!(retry.activation_attempts, 1);
            assert_eq!(retry.activation_after, now + Duration::from_secs(5));
            assert!(retry.allow_activation(now + Duration::from_secs(60)));
        }
    }
    #[test]
    fn failed_revision_commit_preserves_disk_and_dirty_in_memory_roster() {
        let root = root();
        {
            let mut session = binding(&root);
            session.policy.observe(KEY, 1, &[member(1)]).unwrap();
            session.flush().unwrap();
            session
                .policy
                .observe(KEY, 1, &[member(1), member(2)])
                .unwrap();
            session.revision = 0;
            assert_eq!(session.flush(), Err(STALE));
            assert!(session.policy.dirty());
            let value = session
                .store
                .lock()
                .unwrap()
                .read(&session.module, 1)
                .unwrap();
            let on_disk: Document = serde_json::from_value(value.value).unwrap();
            assert_eq!(on_disk.communities[KEY], vec![member(1)]);
            session.revision = value.revision;
            session.flush().unwrap();
            assert!(!session.policy.dirty());
        }
        assert!(root.starts_with(std::env::temp_dir()));
        std::fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn diagnostics_distinguish_same_error_at_different_stages_and_record_commits() {
        let root = root();
        {
            let mut session = binding(&root);
            session.report(UNSUPPORTED, "context.remote-peers");
            session.report(UNSUPPORTED, "context.remote-peers");
            session.report(UNSUPPORTED, "context.dialogue");
            session.report(0, "roster.identity");
            session.report(0, "context.community-id");
            session
                .policy
                .observe(KEY, 1, &[member(1), member(2), member(3)])
                .unwrap();
            session.flush().unwrap();
            let log = std::fs::read_to_string(root.join("diagnostic.jsonl")).unwrap();
            let rows: Vec<serde_json::Value> = log
                .lines()
                .map(|line| serde_json::from_str(line).unwrap())
                .collect();
            assert_eq!(
                rows.len(),
                4,
                "identical status/stage must not log each frame"
            );
            assert!(
                rows[0]["message"]
                    .as_str()
                    .unwrap()
                    .contains("stage=context.remote-peers")
            );
            assert!(
                rows[1]["message"]
                    .as_str()
                    .unwrap()
                    .contains("stage=context.dialogue")
            );
            assert_eq!(rows[2]["code"], "FOLLOWER_STATE_READY");
            assert_eq!(rows[3]["code"], "FOLLOWER_STATE_COMMITTED");
            assert!(
                rows[3]["message"]
                    .as_str()
                    .unwrap()
                    .contains("saved_total=3")
            );
            assert!(!log.contains("narrative") && !log.contains(KEY));
        }
        assert!(root.starts_with(std::env::temp_dir()));
        std::fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn foreign_process_cannot_install_persistence_hooks() {
        let root = root();
        {
            let session = binding(&root);
            assert_eq!(
                acquire(1, session.module, session.store, session.logger),
                Err(UNSUPPORTED)
            );
            assert!(HOOKS.lock().unwrap().is_none());
            assert!(BINDING.lock().unwrap().is_none());
        }
        assert!(root.starts_with(std::env::temp_dir()));
        std::fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn actual_inert_hooks_restore_bytes_refuse_foreign_changes_and_rollback_partial_setup() {
        use windows_sys::Win32::System::Memory::{
            MEM_COMMIT, MEM_RELEASE, MEM_RESERVE, PAGE_EXECUTE_READWRITE, VirtualAlloc, VirtualFree,
        };
        // Authored NOP/RET functions only, never a substitute for fixed game input.
        let allocation = unsafe {
            VirtualAlloc(
                ptr::null(),
                4096,
                MEM_COMMIT | MEM_RESERVE,
                PAGE_EXECUTE_READWRITE,
            )
        };
        assert!(!allocation.is_null());
        let bytes = allocation.cast::<u8>();
        unsafe { ptr::write_bytes(bytes, 0x90, 4096) };
        let targets: Vec<usize> = (0..3).map(|i| allocation as usize + i * 64).collect();
        for target in &targets {
            unsafe { *(target.wrapping_add(32) as *mut u8) = 0xc3 }
        }
        let originals: Vec<_> = targets
            .iter()
            .map(|target| follower_access::read(*target, 16).unwrap())
            .collect();
        let mut hooks = Hooks {
            sites: Vec::new(),
            poisoned: false,
        };
        hooks.install_targets(targets.clone()).unwrap();
        let tick_fn: Tick = unsafe { std::mem::transmute(targets[0]) };
        let save_fn: Save = unsafe { std::mem::transmute(targets[1]) };
        let dismiss_fn: Dismiss = unsafe { std::mem::transmute(targets[2]) };
        unsafe {
            tick_fn(ptr::null_mut(), 2, 0.01);
            save_fn(ptr::null_mut(), ptr::null_mut(), ptr::null_mut());
            dismiss_fn(ptr::null_mut(), ptr::null_mut());
        }
        let started = Instant::now();
        for _ in 0..20_000 {
            unsafe { tick_fn(ptr::null_mut(), 2, 0.01) };
        }
        let empty_callback_ns = started.elapsed().as_nanos() / 20_000;
        println!(
            "PERF: inert unbound tick callback {empty_callback_ns} ns/call; active game read/restore NOT_RUN"
        );
        assert_eq!(CALLS.load(Ordering::Acquire), 0);
        let changed_at = targets[0] + 15;
        let expected = hooks.sites[0].patched[15];
        unsafe { *(changed_at as *mut u8) = expected ^ 1 };
        assert_eq!(hooks.withdraw(), Err(UNSUPPORTED));
        assert_eq!(
            follower_access::read(changed_at, 1).unwrap()[0],
            expected ^ 1
        );
        // Only this authored test owns the altered byte and may repair it. The
        // production poisoned record has no recovery/re-enable operation.
        unsafe { *(changed_at as *mut u8) = expected };
        hooks.poisoned = false;
        hooks.withdraw().unwrap();
        for (target, original) in targets.iter().zip(&originals) {
            assert_eq!(follower_access::read(*target, 16).unwrap(), *original);
        }
        let mut partial = Hooks {
            sites: Vec::new(),
            poisoned: false,
        };
        assert_eq!(
            partial.install_targets(vec![targets[0], 0, targets[2]]),
            Err(INVALID)
        );
        assert_eq!(partial.sites.len(), 1);
        partial.withdraw().unwrap();
        assert_eq!(follower_access::read(targets[0], 16).unwrap(), originals[0]);
        assert_eq!(unsafe { VirtualFree(allocation, 0, MEM_RELEASE) }, 1);
    }
    #[test]
    fn offline_roster_journal_performance_and_unchanged_frames_do_not_write() {
        let root = root();
        let mut samples = Vec::new();
        let mut unchanged = Vec::new();
        {
            let mut session = binding(&root);
            let mut roster: Vec<_> = (0..20).map(member).collect();
            session.policy.observe(KEY, 1, &roster).unwrap();
            session.flush().unwrap();
            for _ in 0..1000 {
                let begin = Instant::now();
                session.policy.observe(KEY, 1, &roster).unwrap();
                session.flush().unwrap();
                unchanged.push(begin.elapsed().as_micros());
            }
            assert_eq!(
                session.persisted, 1,
                "steady frames cannot issue repeated filesystem writes"
            );
            for _ in 0..100 {
                roster[0].entity += 1;
                let begin = Instant::now();
                session.policy.observe(KEY, 1, &roster).unwrap();
                session.flush().unwrap();
                samples.push(begin.elapsed().as_micros());
            }
            assert_eq!(session.persisted, 101);
        }
        samples.sort_unstable();
        unchanged.sort_unstable();
        let report = serde_json::json!({"schema":1,"scope":"authored 20-member policy plus actual local journal I/O; not native game access",
            "platform":std::env::consts::OS,"source_version":env!("CARGO_PKG_VERSION"),
            "unchanged_samples":1000,"steady_p95_us":unchanged[950],
            "changed_samples":100,"changed_p50_us":samples[50],"changed_p95_us":samples[95],"changed_max_us":samples[99],
            "offline_budget":{"steady_p95_us":1000,"changed_p95_us":50_000},
            "native_active_callback":"NOT_RUN","game_frame_memory_growth":"NOT_RUN"});
        println!("PERF: {report}");
        if let Some(destination) = std::env::var_os("SOD2_FOLLOWER_PERF_REPORT") {
            use std::io::Write;
            let mut file = std::fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(destination)
                .unwrap();
            writeln!(file, "{report}").unwrap();
        }
        assert!(root.starts_with(std::env::temp_dir()));
        std::fs::remove_dir_all(root).unwrap();
        assert!(unchanged[950] < 1000, "offline steady policy budget");
        assert!(samples[95] < 50_000, "offline change/journal budget");
    }
}
