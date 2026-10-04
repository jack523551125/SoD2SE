//! Audited Windows boundary. All fixed-build mutation is owned by this adapter.
use super::*;
use sod2se_abi::{BUSY, INTERNAL};
use std::{
    ffi::c_void,
    mem::{size_of, zeroed},
    path::Path,
    ptr,
};
use windows_sys::Win32::{
    Foundation::*,
    System::{
        Diagnostics::{Debug::*, ToolHelp::*},
        LibraryLoader::*,
        Memory::*,
        Threading::*,
    },
};

pub struct Handle(pub HANDLE);
impl Drop for Handle {
    fn drop(&mut self) {
        if !self.0.is_null() && self.0 != INVALID_HANDLE_VALUE {
            unsafe {
                CloseHandle(self.0);
            }
        }
    }
}
// GetModuleFileNameW validates this opaque Windows handle; Rust never dereferences it.
#[allow(clippy::not_unsafe_ptr_arg_deref)]
pub fn module_path(module: HMODULE) -> Result<std::path::PathBuf, i32> {
    let mut path = vec![0u16; 32768];
    let n = unsafe { GetModuleFileNameW(module, path.as_mut_ptr(), path.len() as u32) };
    if n == 0 || n as usize >= path.len() {
        return Err(INTERNAL);
    }
    use std::os::windows::ffi::OsStringExt;
    Ok(std::ffi::OsString::from_wide(&path[..n as usize]).into())
}
pub fn verify_current() -> Result<(), i32> {
    static PROOF: std::sync::OnceLock<Result<(), i32>> = std::sync::OnceLock::new();
    *PROOF.get_or_init(|| super::verify_image(&module_path(ptr::null_mut())?))
}
pub fn wide(path: &Path) -> Vec<u16> {
    use std::os::windows::ffi::OsStrExt;
    path.as_os_str().encode_wide().chain(Some(0)).collect()
}

struct Prepared {
    address: usize,
    guard_address: usize,
    original: Vec<u8>,
    replacement: Vec<u8>,
    guard: Vec<u8>,
}
fn prepare(base: usize) -> Result<Vec<Prepared>, i32> {
    target()
        .patches
        .iter()
        .map(|p| {
            let original = decode(&p.original)?;
            let replacement = decode(&p.replacement)?;
            let guard = decode(&p.guard_original)?;
            let address = base.checked_add(p.rva).ok_or(INVALID)?;
            let guard_address = base.checked_add(p.guard_rva).ok_or(INVALID)?;
            if original.is_empty()
                || original.len() != replacement.len()
                || guard.len() > 512
                || guard_address > address
                || address.checked_add(original.len()).ok_or(INVALID)?
                    > guard_address.checked_add(guard.len()).ok_or(INVALID)?
                || address / 4096 != (address + original.len() - 1) / 4096
            {
                return Err(INVALID);
            }
            Ok(Prepared {
                address,
                guard_address,
                original,
                replacement,
                guard,
            })
        })
        .collect()
}
fn read(address: usize, output: &mut [u8]) -> Result<(), i32> {
    let mut n = 0;
    if unsafe {
        ReadProcessMemory(
            GetCurrentProcess(),
            address as *const c_void,
            output.as_mut_ptr().cast(),
            output.len(),
            &mut n,
        )
    } == 0
        || n != output.len()
    {
        return Err(INTERNAL);
    }
    Ok(())
}
fn write(address: usize, bytes: &[u8]) -> Result<(), i32> {
    let mut old = 0;
    let mut restored = 0;
    let mut n = 0;
    if unsafe {
        VirtualProtect(
            address as *const c_void,
            bytes.len(),
            PAGE_EXECUTE_READWRITE,
            &mut old,
        )
    } == 0
    {
        return Err(INTERNAL);
    }
    let written = unsafe {
        WriteProcessMemory(
            GetCurrentProcess(),
            address as *const c_void,
            bytes.as_ptr().cast(),
            bytes.len(),
            &mut n,
        )
    } != 0
        && n == bytes.len();
    let protected =
        unsafe { VirtualProtect(address as *const c_void, bytes.len(), old, &mut restored) } != 0;
    let flushed = unsafe {
        FlushInstructionCache(GetCurrentProcess(), address as *const c_void, bytes.len())
    } != 0;
    if !written || !protected || !flushed {
        return Err(INTERNAL);
    }
    let mut check = [0; 512];
    read(address, &mut check[..bytes.len()])?;
    if &check[..bytes.len()] != bytes {
        return Err(INTERNAL);
    }
    Ok(())
}

#[repr(C)]
struct ThreadBasic {
    status: i32,
    teb: *const u8,
    process: usize,
    thread: usize,
    affinity: usize,
    priority: i32,
    base_priority: i32,
}
#[link(name = "ntdll")]
unsafe extern "system" {
    fn NtGetNextThread(
        process: HANDLE,
        thread: HANDLE,
        access: u32,
        attributes: u32,
        flags: u32,
        next: *mut HANDLE,
    ) -> i32;
    fn NtQueryInformationThread(
        thread: HANDLE,
        class: u32,
        information: *mut c_void,
        length: u32,
        returned: *mut u32,
    ) -> i32;
}
struct Suspended {
    handles: Vec<Handle>,
    ids: Vec<u32>,
    suspended: usize,
    pending: [bool; 1024],
}
impl Suspended {
    fn new() -> Result<Self, i32> {
        let snapshot = Handle(unsafe { CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0) });
        if snapshot.0 == INVALID_HANDLE_VALUE {
            return Err(INTERNAL);
        }
        let pid = unsafe { GetCurrentProcessId() };
        let own = unsafe { GetCurrentThreadId() };
        let mut entry: THREADENTRY32 = unsafe { zeroed() };
        entry.dwSize = size_of::<THREADENTRY32>() as u32;
        let mut result = Self {
            handles: Vec::with_capacity(1024),
            ids: Vec::with_capacity(1024),
            suspended: 0,
            pending: [false; 1024],
        };
        let mut present = unsafe { Thread32First(snapshot.0, &mut entry) } != 0;
        while present {
            if entry.th32OwnerProcessID == pid && entry.th32ThreadID != own {
                let handle = Handle(unsafe {
                    OpenThread(
                        THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION,
                        0,
                        entry.th32ThreadID,
                    )
                });
                if handle.0.is_null() {
                    return Err(INTERNAL);
                }
                if result.handles.len() == 1024 {
                    return Err(BUSY);
                }
                result.handles.push(handle);
                result.ids.push(entry.th32ThreadID);
            }
            present = unsafe { Thread32Next(snapshot.0, &mut entry) } != 0;
        }
        if result.handles.is_empty() {
            return Err(BUSY);
        }
        // No Rust heap allocations while other game threads are suspended.
        for (index, handle) in result.handles.iter().enumerate() {
            if unsafe { SuspendThread(handle.0) } == u32::MAX {
                return Err(INTERNAL);
            }
            result.suspended += 1;
            result.pending[index] = true;
        }
        // Close the enumerate/suspend race using kernel thread enumeration, without
        // heap allocation while game threads are paused. Newly discovered threads
        // must also be suspended before any guard or code write is attempted.
        let mut stable = false;
        for _ in 0..3 {
            let mut previous = Handle(ptr::null_mut());
            let mut added = false;
            loop {
                let mut next = ptr::null_mut();
                let status = unsafe {
                    NtGetNextThread(
                        GetCurrentProcess(),
                        previous.0,
                        THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION,
                        0,
                        0,
                        &mut next,
                    )
                };
                if status == 0x8000001au32 as i32 {
                    break;
                }
                if status < 0 || next.is_null() {
                    return Err(INTERNAL);
                }
                let thread = Handle(next);
                let mut basic: ThreadBasic = unsafe { zeroed() };
                let mut returned = 0;
                if unsafe {
                    NtQueryInformationThread(
                        thread.0,
                        0,
                        (&mut basic as *mut ThreadBasic).cast(),
                        size_of::<ThreadBasic>() as u32,
                        &mut returned,
                    )
                } < 0
                    || returned < size_of::<ThreadBasic>() as u32
                {
                    return Err(INTERNAL);
                }
                let id = basic.thread as u32;
                if id != own && !result.ids.contains(&id) {
                    if result.handles.len() == 1024 {
                        return Err(BUSY);
                    }
                    let retained = Handle(unsafe {
                        OpenThread(
                            THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION,
                            0,
                            id,
                        )
                    });
                    if retained.0.is_null() || unsafe { SuspendThread(retained.0) } == u32::MAX {
                        return Err(INTERNAL);
                    }
                    result.pending[result.handles.len()] = true;
                    result.handles.push(retained);
                    result.ids.push(id);
                    result.suspended += 1;
                    added = true;
                }
                previous = thread;
            }
            if !added {
                stable = true;
                break;
            }
        }
        if !stable {
            return Err(BUSY);
        }
        Ok(result)
    }
    fn quiescent(&self, patches: &[Prepared]) -> Result<(), i32> {
        let in_patch = |address: u64| {
            patches.iter().any(|p| {
                address >= p.address as u64 && address < (p.address + p.original.len()) as u64
            })
        };
        let mut stack = [0; 65536];
        for thread in &self.handles {
            let mut context: CONTEXT = unsafe { zeroed() };
            context.ContextFlags = CONTEXT_CONTROL_AMD64;
            if unsafe { GetThreadContext(thread.0, &mut context) } == 0 {
                return Err(INTERNAL);
            }
            if in_patch(context.Rip) {
                return Err(BUSY);
            }
            let mut basic: ThreadBasic = unsafe { zeroed() };
            let mut returned = 0;
            if unsafe {
                NtQueryInformationThread(
                    thread.0,
                    0,
                    (&mut basic as *mut ThreadBasic).cast(),
                    size_of::<ThreadBasic>() as u32,
                    &mut returned,
                )
            } < 0
                || returned < size_of::<ThreadBasic>() as u32
            {
                return Err(INTERNAL);
            }
            let mut bounds = [0; 16];
            read(basic.teb as usize + 8, &mut bounds)?;
            let top = u64::from_le_bytes(bounds[..8].try_into().unwrap());
            let bottom = u64::from_le_bytes(bounds[8..].try_into().unwrap());
            let mut address = context.Rsp;
            if address < bottom
                || address > top
                || top - address > 32 * 1024 * 1024
                || !address.is_multiple_of(8)
            {
                return Err(BUSY);
            }
            while address < top {
                let n = (top - address).min(stack.len() as u64) as usize;
                read(address as usize, &mut stack[..n])?;
                if stack[..n]
                    .chunks_exact(8)
                    .any(|b| in_patch(u64::from_le_bytes(b.try_into().unwrap())))
                {
                    return Err(BUSY);
                }
                address += n as u64;
            }
        }
        Ok(())
    }
    fn resume(&mut self) -> Result<(), i32> {
        let mut result = Ok(());
        for (index, handle) in self.handles.iter().enumerate().rev() {
            if !self.pending[index] {
                continue;
            }
            for _ in 0..3 {
                if unsafe { ResumeThread(handle.0) } != u32::MAX {
                    self.pending[index] = false;
                    break;
                }
            }
            if self.pending[index] {
                result = Err(INTERNAL);
            }
        }
        self.suspended = self.pending.iter().filter(|&&p| p).count();
        result
    }
}
impl Drop for Suspended {
    fn drop(&mut self) {
        let _ = self.resume();
    }
}

#[derive(Default)]
pub struct FollowerLease {
    owner: Option<u64>,
    poisoned: bool,
}
impl FollowerLease {
    pub fn owned_by(&self, owner: u64) -> bool {
        self.owner == Some(owner)
    }
    pub fn active(&self) -> bool {
        self.owner.is_some()
    }
    pub fn poisoned(&self) -> bool {
        self.poisoned
    }
    pub fn acquire(&mut self, owner: u64) -> Result<(), i32> {
        if owner == 0 || self.poisoned {
            return Err(INTERNAL);
        }
        if self.owner.is_some() {
            return Err(BUSY);
        }
        verify_current()?;
        let patches = prepare(unsafe { GetModuleHandleW(ptr::null()) } as usize)?;
        let mut paused = Suspended::new()?;
        paused.quiescent(&patches)?;
        let mut scratch = [0; 512];
        for p in &patches {
            read(p.guard_address, &mut scratch[..p.guard.len()])?;
            if scratch[..p.guard.len()] != p.guard {
                return Err(UNSUPPORTED);
            }
        }
        for (i, p) in patches.iter().enumerate() {
            if let Err(error) = write(p.address, &p.replacement) {
                // Restore all attempted sites, including a possibly partially written current site.
                self.poisoned = true;
                for q in patches[..=i].iter().rev() {
                    let _ = write(q.address, &q.original);
                }
                return Err(error);
            }
        }
        self.owner = Some(owner);
        paused.resume()?;
        Ok(())
    }
    pub fn release(&mut self, owner: u64) -> Result<(), i32> {
        if self.owner != Some(owner) {
            return Err(INVALID);
        }
        let patches = prepare(unsafe { GetModuleHandleW(ptr::null()) } as usize)?;
        let mut paused = Suspended::new()?;
        paused.quiescent(&patches)?;
        let mut scratch = [0; 512];
        for p in &patches {
            read(p.guard_address, &mut scratch[..p.guard.len()])?;
            let offset = p.address - p.guard_address;
            for (i, byte) in scratch[..p.guard.len()].iter().enumerate() {
                let expected = if i >= offset && i < offset + p.replacement.len() {
                    p.replacement[i - offset]
                } else {
                    p.guard[i]
                };
                if *byte != expected {
                    self.poisoned = true;
                    return Err(UNSUPPORTED);
                }
            }
        }
        for p in &patches {
            if let Err(e) = write(p.address, &p.original) {
                self.poisoned = true;
                return Err(e);
            }
        }
        self.owner = None;
        paused.resume()?;
        Ok(())
    }
}
