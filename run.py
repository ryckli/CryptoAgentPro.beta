"""CryptoAgents Pro 启动器 — PyInstaller 打包入口。

双击运行后启动后台服务、打开浏览器。
"""
import os
import sys
import threading
import webbrowser


def main():
    # PyInstaller 打包时 sys._MEIPASS 指向临时解压目录
    if getattr(sys, 'frozen', False):
        os.chdir(sys._MEIPASS)

    from app.core.logging_config import setup_logging
    setup_logging()
    from app.core.logging_config import get_logger
    logger = get_logger("launcher")
    logger.info("=== CryptoAgents Pro Starting ===")

    import uvicorn
    from app.core.config import settings

    # 延迟打开浏览器
    def open_browser():
        import time
        time.sleep(2)
        url = f"http://127.0.0.1:{settings.PORT}"
        logger.info(f"Launching browser: {url}")
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()

    logger.info(f"Server: http://127.0.0.1:{settings.PORT}")
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=settings.PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
