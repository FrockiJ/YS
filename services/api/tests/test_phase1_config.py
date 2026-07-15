import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


CONFIG_PATH = Path(__file__).resolve().parents[1] / "src" / "core" / "config.py"


def _execute_config_module():
    source = CONFIG_PATH.read_text(encoding="utf-8")
    namespace = {
        "__file__": str(CONFIG_PATH),
        "__name__": "phase1_config_test",
    }
    exec(compile(source, str(CONFIG_PATH), "exec"), namespace)
    return namespace


class ConfigBootstrapTests(unittest.TestCase):
    def test_explicit_env_file_is_loaded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "test.env"
            env_path.write_text("APP_HOST=127.0.0.1\nUPLOAD_STORAGE_PATH=tmp-storage\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=False):
                for key in ["APP_HOST", "UPLOAD_STORAGE_PATH", "YS_ENV_FILE", "PYTHON_DOTENV_DISABLED"]:
                    os.environ.pop(key, None)
                os.environ["YS_ENV_FILE"] = str(env_path)
                module = _execute_config_module()
        self.assertEqual(module["APP_HOST"], "127.0.0.1")
        self.assertEqual(module["UPLOAD_STORAGE_PATH"], "tmp-storage")

    def test_dotenv_loading_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "test.env"
            env_path.write_text("APP_HOST=127.0.0.1\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=False):
                for key in ["APP_HOST", "YS_ENV_FILE", "PYTHON_DOTENV_DISABLED"]:
                    os.environ.pop(key, None)
                os.environ["YS_ENV_FILE"] = str(env_path)
                os.environ["PYTHON_DOTENV_DISABLED"] = "1"
                module = _execute_config_module()
        self.assertEqual(module["APP_HOST"], "0.0.0.0")

    def test_non_utf8_env_file_falls_back_without_crashing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "cp950.env"
            env_path.write_bytes("APP_HOST=127.0.0.1\nNOTE=測試\n".encode("cp950"))
            with mock.patch.dict(os.environ, {}, clear=False):
                for key in ["APP_HOST", "NOTE", "YS_ENV_FILE", "PYTHON_DOTENV_DISABLED"]:
                    os.environ.pop(key, None)
                os.environ["YS_ENV_FILE"] = str(env_path)
                module = _execute_config_module()
                note = os.getenv("NOTE")
        self.assertEqual(module["APP_HOST"], "127.0.0.1")
        self.assertEqual(note, "測試")


if __name__ == "__main__":
    unittest.main()
