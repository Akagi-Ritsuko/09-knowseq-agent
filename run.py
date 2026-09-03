"""项目根便捷入口：python run.py"""
import faulthandler
import traceback

if __name__ == "__main__":
    faulthandler.enable()  # 原生崩溃（0xC0000005 等）也会把现场打到 stderr
    try:
        from app.main import main
        main()
    except Exception:
        traceback.print_exc()
        print("\n[knowseq-agent] 启动失败，请把以上报错发给 AI 协助排查")
    finally:
        # 双击运行时窗口不闪退，便于看到报错
        try:
            input("\n按回车键退出...")
        except EOFError:
            pass
