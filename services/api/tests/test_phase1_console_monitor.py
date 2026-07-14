import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("PYTHON_DOTENV_DISABLED", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starlette.responses import FileResponse

from src.api import routes_console


class ConsoleMonitorTests(unittest.IsolatedAsyncioTestCase):
    async def test_extract_monitor_routes_return_files(self):
        html = await routes_console.extract_monitor_page()
        js = await routes_console.extract_monitor_js()
        css = await routes_console.extract_monitor_css()

        self.assertIsInstance(html, FileResponse)
        self.assertTrue(str(html.path).endswith("extract-monitor.html"))
        self.assertTrue(Path(html.path).exists())

        self.assertIsInstance(js, FileResponse)
        self.assertTrue(str(js.path).endswith("extract-monitor.js"))
        self.assertTrue(Path(js.path).exists())

        self.assertIsInstance(css, FileResponse)
        self.assertTrue(str(css.path).endswith("extract-monitor.css"))
        self.assertTrue(Path(css.path).exists())


if __name__ == "__main__":
    unittest.main()
