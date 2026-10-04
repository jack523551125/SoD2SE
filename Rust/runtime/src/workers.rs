use sod2se_abi::INTERNAL;
use std::sync::{
    Mutex,
    atomic::{AtomicBool, Ordering},
};
static STOP: AtomicBool = AtomicBool::new(false);
static WORKERS: Mutex<Vec<std::thread::JoinHandle<()>>> = Mutex::new(Vec::new());
pub fn stopping() -> bool {
    STOP.load(Ordering::Acquire)
}
pub fn spawn(name: &str, work: impl FnOnce() + Send + 'static) -> Result<(), i32> {
    let thread = std::thread::Builder::new()
        .name(name.into())
        .spawn(work)
        .map_err(|_| INTERNAL)?;
    WORKERS.lock().map_err(|_| INTERNAL)?.push(thread);
    Ok(())
}
pub fn stop() {
    STOP.store(true, Ordering::Release);
    if let Ok(mut workers) = WORKERS.lock() {
        for thread in workers.drain(..) {
            let _ = thread.join();
        }
    }
}
