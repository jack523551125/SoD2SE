//! Explicit local diagnostic connection. Session nonces are never included in reports/logs.
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sod2se_abi::{INTERNAL, INVALID};
use std::{
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    path::Path,
};
#[derive(Serialize, Deserialize)]
pub struct Endpoint {
    pub schema: u32,
    pub pid: u32,
    pub port: u16,
    pub nonce: String,
}
pub fn receive(stream: &mut TcpStream) -> Result<Value, i32> {
    let mut prefix = [0; 4];
    stream.read_exact(&mut prefix).map_err(|_| INTERNAL)?;
    let size = u32::from_le_bytes(prefix) as usize;
    if size == 0 || size > 1024 * 1024 {
        return Err(INVALID);
    }
    let mut bytes = vec![0; size];
    stream.read_exact(&mut bytes).map_err(|_| INTERNAL)?;
    serde_json::from_slice(&bytes).map_err(|_| INVALID)
}
pub fn send(stream: &mut TcpStream, value: &Value) -> Result<(), i32> {
    let bytes = serde_json::to_vec(value).map_err(|_| INVALID)?;
    if bytes.len() > 1024 * 1024 {
        return Err(INVALID);
    }
    stream
        .write_all(&(bytes.len() as u32).to_le_bytes())
        .and_then(|_| stream.write_all(&bytes))
        .map_err(|_| INTERNAL)
}
pub fn connect(path: &Path, operation: &str, input: Value) -> Result<Value, i32> {
    let endpoint: Endpoint =
        serde_json::from_slice(&std::fs::read(path).map_err(|_| INTERNAL)?).map_err(|_| INVALID)?;
    if endpoint.schema != 1 || endpoint.nonce.len() != 64 {
        return Err(INVALID);
    }
    let mut stream = TcpStream::connect_timeout(
        &std::net::SocketAddr::from(([127, 0, 0, 1], endpoint.port)),
        std::time::Duration::from_secs(2),
    )
    .map_err(|_| INTERNAL)?;
    stream
        .set_read_timeout(Some(std::time::Duration::from_secs(2)))
        .map_err(|_| INTERNAL)?;
    stream
        .set_write_timeout(Some(std::time::Duration::from_secs(2)))
        .map_err(|_| INTERNAL)?;
    send(
        &mut stream,
        &json!({"nonce":endpoint.nonce,"operation":operation,"input":input}),
    )?;
    let response = receive(&mut stream)?;
    if response["pid"].as_u64() != Some(endpoint.pid as u64) {
        return Err(INVALID);
    }
    if response["status"].as_i64() != Some(0) {
        return Err(response["status"]
            .as_i64()
            .and_then(|c| i32::try_from(c).ok())
            .unwrap_or(INTERNAL));
    }
    Ok(response["value"].clone())
}
#[cfg(windows)]
pub fn bind(path: &Path) -> Result<(TcpListener, Endpoint), i32> {
    let listener = TcpListener::bind(("127.0.0.1", 0)).map_err(|_| INTERNAL)?;
    let mut bytes = [0u8; 32];
    if unsafe {
        windows_sys::Win32::Security::Cryptography::BCryptGenRandom(
            std::ptr::null_mut(),
            bytes.as_mut_ptr(),
            bytes.len() as u32,
            windows_sys::Win32::Security::Cryptography::BCRYPT_USE_SYSTEM_PREFERRED_RNG,
        )
    } < 0
    {
        return Err(INTERNAL);
    }
    let endpoint = Endpoint {
        schema: 1,
        pid: std::process::id(),
        port: listener.local_addr().map_err(|_| INTERNAL)?.port(),
        nonce: bytes.iter().map(|b| format!("{b:02x}")).collect(),
    };
    crate::settings::atomic_save(path, &serde_json::to_vec(&endpoint).map_err(|_| INTERNAL)?)?;
    Ok((listener, endpoint))
}
