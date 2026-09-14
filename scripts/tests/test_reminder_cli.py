import io, json, os, stat, tempfile, unittest
from datetime import datetime, timezone
import importlib.util
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("reminder_cli", os.path.join(HERE, "..", "reminder.py"))
cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
NOW = datetime(2026, 9, 15, 1, 0, tzinfo=timezone.utc)

class CLI(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.env = {"IMESSAGE_ALLOW_FROM": "+639170000001,+639170000002",
                    "REMINDERS_DIR": os.path.join(d, "rem"), "REMINDERS_TMP": os.path.join(d, "tmp")}
    def run_cli(self, *argv):
        out = io.StringIO(); code = cli.main(list(argv), self.env, NOW, out)
        return code, json.loads(out.getvalue().strip().splitlines()[-1])
    def test_add_text_weekly_and_list(self):
        code, r = self.run_cli("add-text", "--to", "+639170000002", "--text", "Trash", "--name", "Trash", "--weekly", "mon,thu", "08:00")
        self.assertEqual(code, 0); self.assertTrue(r["ok"])
        self.assertTrue(os.path.exists(os.path.join(self.env["REMINDERS_DIR"], r["id"] + ".json")))
        code, l = self.run_cli("list")
        self.assertEqual(l["reminders"][0]["name"], "Trash"); self.assertNotIn("to", l["reminders"][0])
    def test_add_text_once_normalizes_at_to_utc_z(self):
        code, r = self.run_cli("add-text", "--to", "+639170000001", "--text", "Trash",
                                "--name", "Trash", "--at", "2026-09-16T08:00:00+08:00")
        self.assertEqual(code, 0)
        self.assertEqual(r["next_run"], "2026-09-16 08:00")
        with open(os.path.join(self.env["REMINDERS_DIR"], r["id"] + ".json")) as f:
            data = json.load(f)
        self.assertEqual(data["schedule"]["at"], "2026-09-16T00:00:00Z")

    def test_add_smart_once(self):
        code, r = self.run_cli("add-smart", "--to", "+639170000001", "--prompt", "Chores today?", "--name", "Chores", "--at", "2026-09-16T07:00:00+08:00")
        self.assertEqual((code, r["next_run"]), (0, "2026-09-16 07:00"))
    def test_past_refused(self):
        code, r = self.run_cli("add-text", "--to", "+639170000001", "--text", "x", "--name", "x", "--at", "2026-09-14T07:00:00+08:00")
        self.assertEqual(code, 1); self.assertFalse(r["ok"])
    def test_not_allowlisted(self):
        code, r = self.run_cli("add-text", "--to", "+15550000000", "--text", "x", "--name", "x", "--daily", "08:00")
        self.assertEqual(code, 1); self.assertIn("allow", r["error"])
        self.assertNotIn("+15550000000", r["error"])
    def test_usage_error_is_json(self):
        code, r = self.run_cli("add-text", "--text", "x")
        self.assertEqual(code, 2); self.assertFalse(r["ok"])
    def test_cancel(self):
        _, r = self.run_cli("add-text", "--to", "+639170000001", "--text", "x", "--name", "x", "--daily", "08:00")
        self.assertEqual(self.run_cli("cancel", r["id"])[0], 0)
        self.assertEqual(self.run_cli("cancel", r["id"])[0], 1)
        self.assertEqual(self.run_cli("cancel", "../../etc/passwd")[0], 1)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0,
                      "root ignores directory permission bits")
    def test_add_write_failure_is_json(self):
        rem_dir = self.env["REMINDERS_DIR"]
        os.makedirs(rem_dir)
        os.chmod(rem_dir, stat.S_IREAD | stat.S_IEXEC)
        try:
            code, r = self.run_cli("add-text", "--to", "+639170000001", "--text", "x",
                                    "--name", "x", "--daily", "08:00")
        finally:
            os.chmod(rem_dir, stat.S_IRWXU)
        self.assertEqual(code, 1)
        self.assertFalse(r["ok"])
        self.assertIn("could not write reminder", r["error"])
        self.assertNotIn(rem_dir, r["error"])

if __name__ == "__main__":
    unittest.main()
