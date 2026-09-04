// KnowSeq 桌面壳（T-502 / REQ-502 / ADR-016 决策 1 方案 A）：
// 主窗初始加载内置提示页（fallback/index.html），后台线程探测后端
// GET /api/status；就绪后自动导航到 http://127.0.0.1:8765（后端零改动，
// 壳不管理后端生命周期）；未就绪显示明确提示而非白屏。
//
// [T-503 / REQ-503] 关窗隐藏后台常驻 + 单实例 + 壳托盘：点 X 仅隐藏主窗
// （采集不中断），二次启动唤出并聚焦已有实例，退出经托盘菜单「退出壳」；
// 托盘另含「显示主窗」「悬浮控件」开关。与 pystray 采集托盘职责分离（D5）。
// [T-504 / REQ-504] 悬浮控件：透明置顶无装饰小窗加载 webui /floating 路由，
// 隐藏创建，由托盘菜单切换显隐；页面发起拖拽的权限见 capabilities/floating.json。
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
use tauri::menu::{CheckMenuItem, Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_single_instance::init as single_instance_init;

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
        // 单实例（T-503 / REQ-503）：必须是第一个注册的插件；
        // 二次启动不产新进程，改为唤出并聚焦已有主窗
        .plugin(single_instance_init(|app, _args, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.show();
                let _ = w.unminimize();
                let _ = w.set_focus();
            }
        }))
        .on_window_event(|window, event| {
            // 关窗隐藏（T-503 / REQ-503）：点 X 仅隐藏主窗，采集不中断；
            // 真正退出走托盘菜单「退出壳」（app.exit）
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "main" {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .setup(|app| {
            // 悬浮控件窗（T-504 / REQ-504）：透明置顶无装饰小窗，隐藏创建，
            // 由托盘菜单切换显隐；加载 webui /floating 路由（后端 SPA fallback）
            let floating_url: tauri::Url = format!("http://{BACKEND_HOST}:{BACKEND_PORT}/floating")
                .parse()
                .expect("悬浮窗地址非法");
            WebviewWindowBuilder::new(app, "floating", WebviewUrl::External(floating_url))
                .title("KnowSeq 悬浮控件")
                .inner_size(240.0, 96.0)
                .decorations(false)
                .transparent(true)
                .always_on_top(true)
                .skip_taskbar(true)
                .resizable(false)
                .shadow(false)
                .visible(false)
                .build()?;

            // 壳托盘（T-503 / REQ-503）：显示主窗 / 悬浮控件开关 / 退出壳
            let show_item = MenuItem::with_id(app, "show", "显示主窗", true, None::<&str>)?;
            let floating_item =
                CheckMenuItem::with_id(app, "floating", "悬浮控件", true, false, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "退出壳", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show_item, &floating_item, &quit_item])?;
            app.manage(floating_item); // 供菜单事件显式同步勾选态

            TrayIconBuilder::new()
                .icon(app.default_window_icon().expect("缺省图标未配置").clone())
                .tooltip("KnowSeq")
                .menu(&menu)
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "show" => {
                        if let Some(w) = app.get_webview_window("main") {
                            let _ = w.show();
                            let _ = w.unminimize();
                            let _ = w.set_focus();
                        }
                    }
                    "floating" => {
                        if let Some(f) = app.get_webview_window("floating") {
                            let visible = f.is_visible().unwrap_or(false);
                            if visible {
                                let _ = f.hide();
                            } else {
                                let _ = f.show();
                                let _ = f.set_focus();
                            }
                            // 按窗口实际可见性显式同步勾选态，防菜单态漂移
                            if let Some(item) = app.try_state::<CheckMenuItem<tauri::Wry>>() {
                                let _ = item.set_checked(!visible);
                            }
                        }
                    }
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;

            // 探测线程（T-502 骨架 + T-503 离线监测）状态机：
            // ① 密集探测（60s deadline）等后端就绪，超时更新提示页文案
            // ② 低频等待（5s），就绪即导航到控制台
            // ③ 在线监测（5s 周期），连续 2 次失败判离线 → 导航回内置页
            //    离线态（?state=offline，由 fallback 页脚本显示离线文案），
            //    回到 ② 继续等待重连
            let handle = app.handle().clone();
            std::thread::spawn(move || loop {
                // ① 密集探测
                let deadline = std::time::Instant::now() + Duration::from_secs(60);
                loop {
                    if probe_backend() {
                        break;
                    }
                    if std::time::Instant::now() >= deadline {
                        if let Some(w) = handle.get_webview_window("main") {
                            // 离线态页（?state=offline）文案由页脚本管理，不覆盖
                            let _ = w.eval(
                                "if (!new URLSearchParams(location.search).get('state')) \
                                 document.getElementById('probe-status').textContent = \
                                 '后端未就绪：请先启动 KnowSeq 后端（python run.py）。本窗口每 5 秒自动重试。';",
                            );
                        }
                        break;
                    }
                    std::thread::sleep(Duration::from_millis(500));
                }
                // ② 低频等待 → 就绪导航
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
                // ③ 在线监测
                let mut fails = 0u32;
                loop {
                    std::thread::sleep(Duration::from_millis(5000));
                    if probe_backend() {
                        fails = 0;
                    } else {
                        fails += 1;
                        if fails >= 2 {
                            if let Some(w) = handle.get_webview_window("main") {
                                // Windows：内置页 origin 为 http://tauri.localhost
                                // （Tauri 2 / WebView2 默认）；?state=offline 由
                                // fallback 页脚本转成离线文案
                                let _ = w.eval(
                                    "location.replace('http://tauri.localhost/?state=offline');",
                                );
                            }
                            break;
                        }
                    }
                }
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("KnowSeq 壳运行失败");
}
