// KnowSeq 桌面壳（T-502 / REQ-502 / ADR-016 决策 1 方案 A）：
// 主窗初始加载内置提示页（fallback/index.html），后台线程探测后端
// GET /api/status；就绪后自动导航到 http://127.0.0.1:8765（后端零改动，
// 壳不管理后端生命周期）；未就绪显示明确提示而非白屏。
//
// [ADR-016 决策 4 · 方案 B sidecar 演进口子] 方案 A 下壳不管理后端进程；
// 迁移方案 B 时在 tauri.conf.json 启用 bundle.externalBin（PyInstaller 后端
// 产物）并在壳启动时 spawn 子进程，同步放行 tauri.localhost Origin
// （见 app/web/server.py 校验处口子注释）与 VITE_API_BASE 前缀位
// （见 webui/src/api.ts）。tauri.conf.json 不支持 JSONC 注释，
// 口子说明详见本目录 README.md。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::time::Duration;
use tauri::Manager;

const BACKEND_HOST: &str = "127.0.0.1";
const BACKEND_PORT: u16 = 8765;

/// 对后端发起一次真实 HTTP GET /api/status 探测（零依赖：裸 TCP 写 HTTP/1.0）。
/// 收到 2xx 状态行即视为就绪。
/// 注意：连接必须用 connect_timeout 限时——部分环境下对无监听端口的裸
/// connect 会被安全软件代答 SYN-ACK 而阻塞数秒，导致探测周期失真。
fn probe_backend() -> bool {
    let addr: SocketAddr = format!("{BACKEND_HOST}:{BACKEND_PORT}")
        .parse()
        .expect("后端地址非法");
    let Ok(mut stream) = TcpStream::connect_timeout(&addr, Duration::from_millis(800)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(800)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(800)));
    let req = format!("GET /api/status HTTP/1.0\r\nHost: {addr}\r\nConnection: close\r\n\r\n");
    if stream.write_all(req.as_bytes()).is_err() {
        return false;
    }
    let mut buf = [0u8; 128];
    let Ok(n) = stream.read(&mut buf) else {
        return false;
    };
    let head = String::from_utf8_lossy(&buf[..n]);
    head.split_whitespace().nth(1).is_some_and(|code| code.starts_with('2'))
}

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                // 启动探测：密集探测 60s（按截止时间控制，探测本身含 800ms
                // 连接/读超时 + 500ms 间隔），期间等后端起来
                let deadline = std::time::Instant::now() + Duration::from_secs(60);
                let ready = loop {
                    if probe_backend() {
                        break true;
                    }
                    if std::time::Instant::now() >= deadline {
                        break false;
                    }
                    std::thread::sleep(Duration::from_millis(500));
                };
                if !ready {
                    // 超时：更新内置提示页文案（明确提示而非白屏）
                    if let Some(w) = handle.get_webview_window("main") {
                        let _ = w.eval(
                            "document.getElementById('probe-status').textContent = \
                             '后端未就绪：请先启动 KnowSeq 后端（python run.py）。本窗口每 5 秒自动重试。';",
                        );
                    }
                }
                // 低频重试：无论是否超时，后端就绪即导航到控制台
                loop {
                    if probe_backend() {
                        if let Some(w) = handle.get_webview_window("main") {
                            let _ = w.eval(&format!(
                                "location.replace('http://{BACKEND_HOST}:{BACKEND_PORT}/');"
                            ));
                        }
                        break;
                    }
                    std::thread::sleep(Duration::from_millis(5000));
                }
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("KnowSeq 壳运行失败");
}
