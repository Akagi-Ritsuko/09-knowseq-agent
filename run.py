"""项目根便捷入口：python run.py；HKCU Run 键自启（T-507）以 pythonw 复用本入口。"""
import faulthandler
import os
import sys
import traceback

if __name__ == "__main__":
    # pythonw（无控制台）下 std 流为 None，而部分库直接依赖流对象（如 uvicorn
    # ColourizedFormatter 调用 sys.stdout.isatty()），替换为 devnull 全局兜底
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    faulthandler.enable()  # 原生崩溃（0xC0000005 等）也会把现场打到 stderr
    try:
        from app.main import main
        main()
    except Exception:
        try:
            traceback.print_exc()
            print("\n[knowseq-agent] 启动失败，请把以上报错发给 AI 协助排查")
        except Exception:
            pass  # pythonw 下无处可打，静默
    finally:
        # 双击运行时窗口不闪退，便于看到报错；pythonw 下无 stdin，直接跳过
        if sys.stdin is not None:
            try:
                input("\n按回车键退出...")
            except EOFError:
                pass
