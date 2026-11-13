import unittest
from pc_app.autostart import build_install_script, build_remove_script, ps_quote


class AutostartTests(unittest.TestCase):
    def test_highest_interactive_task_no_password_or_system(self):
        script = build_install_script(r"C:\Program Files\FanARGB\FanARGBControl.exe", "gui")
        self.assertIn("-RunLevel Highest", script)
        self.assertIn("-LogonType Interactive", script)
        self.assertIn("New-ScheduledTaskTrigger -AtLogOn", script)
        self.assertIn("Register-ScheduledTask", script)
        self.assertNotIn("-Password", script)
        self.assertNotIn("-User SYSTEM", script)
        self.assertNotIn("Bypass", script)

    def test_headless_and_quoted_paths(self):
        script = build_install_script(r"C:\App O'Brien\FanARGBControl.exe", "agent")
        self.assertIn("O''Brien", script)
        self.assertIn("--headless", script)
        self.assertEqual(ps_quote("x'y"), "'x''y'")
        self.assertIn("Unregister-ScheduledTask", build_remove_script())

    def test_bad_paths_or_modes(self):
        for path, mode in [
            ("FanARGBControl.exe", "gui"), ("C:/f/config.ini", "gui"),
            ("C:/f/a.exe", "admin-now"), ("C:/f/a.exe", ""),
        ]:
            with self.assertRaises(ValueError):
                build_install_script(path, mode)


if __name__ == "__main__":
    unittest.main()
