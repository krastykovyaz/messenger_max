"""Offline tests for scheduling, retries and the no-double-post rules. No network, no browser.

Run: venv/bin/python -m unittest test_family_post -v
"""
import os
import tempfile
import unittest
from datetime import date, datetime
from unittest import mock

import family_chat_with_pic as f
import extras
import ai_generator


def at(hour, minute=0, day=7):
    return datetime(2026, 11, day, hour, minute, tzinfo=f.MSK)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p_state = mock.patch.object(f, "LAST_POST_FILE", os.path.join(self.tmp.name, "last"))
        self.p_state.start()
        self.p_sleep = mock.patch.object(f.time, "sleep")
        self.sleep = self.p_sleep.start()
        self.p_alert = mock.patch.object(f, "alert")
        self.alert = self.p_alert.start()
        self.p_hb = mock.patch.object(f, "heartbeat")
        self.hb = self.p_hb.start()

    def tearDown(self):
        mock.patch.stopall()
        self.tmp.cleanup()

    def now(self, dt):
        return mock.patch.object(f, "moscow_now", return_value=dt)


class Schedule(Base):
    def test_before_six_waits_until_six(self):
        with self.now(at(5, 30)):
            self.assertEqual(f.seconds_until_post(), 30 * 60)

    def test_inside_catch_up_window_posts_now(self):
        with self.now(at(6, 20)):
            self.assertEqual(f.seconds_until_post(), 0)

    def test_after_window_waits_for_tomorrow(self):
        with self.now(at(9, 0)):
            self.assertEqual(f.seconds_until_post(), 21 * 3600)

    def test_already_posted_today_waits_for_tomorrow(self):
        with self.now(at(6, 5)):
            f.mark_day_done()
            self.assertAlmostEqual(f.seconds_until_post(), 24 * 3600 - 5 * 60)


class PostToday(Base):
    def test_photo_success(self):
        with self.now(at(6)), mock.patch.object(f, "run_once", return_value="photo") as run:
            f.post_today()
        run.assert_called_once()
        self.hb.assert_called_once()
        self.alert.assert_not_called()
        with self.now(at(6, 1)):
            self.assertTrue(f.posted_today())

    def test_text_fallback_alerts(self):
        with self.now(at(6)), mock.patch.object(f, "run_once", return_value="text"):
            f.post_today()
        self.hb.assert_called_once()
        self.assertIn("без картинки", self.alert.call_args[0][0])

    def test_unconfirmed_is_never_retried(self):
        with self.now(at(6)), mock.patch.object(f, "run_once", side_effect=f.SendUnconfirmed("x")) as run:
            f.post_today()
        run.assert_called_once()
        self.hb.assert_not_called()
        self.assertIn("Не уверен", self.alert.call_args[0][0])
        with self.now(at(6, 1)):
            self.assertTrue(f.posted_today())

    def test_retries_then_succeeds(self):
        with self.now(at(6)), mock.patch.object(f, "run_once", side_effect=[RuntimeError("a"), "photo"]) as run:
            f.post_today()
        self.assertEqual(run.call_count, 2)
        self.alert.assert_not_called()

    def test_gives_up_after_attempts_and_alerts_once(self):
        with self.now(at(6)), mock.patch.object(f, "run_once", side_effect=RuntimeError("boom")) as run:
            f.post_today()
        self.assertEqual(run.call_count, f.ATTEMPTS)
        self.alert.assert_called_once()
        self.assertIn("boom", self.alert.call_args[0][0])
        with self.now(at(6, 20)):
            self.assertTrue(f.posted_today())   # no second round in the catch-up window


class RunOnce(Base):
    """Browser and network are mocked; checks fallback order and image clean-up."""

    def run_with(self, pic_effect=None, text_effect=None):
        img = os.path.join(self.tmp.name, "pic.jpg")
        open(img, "w").close()
        pw = mock.MagicMock()
        with mock.patch.object(f, "build_message_with_ai", return_value="msg"), \
                mock.patch.object(f, "purge_old_images"), \
                mock.patch.object(f, "pick_photo_topic", return_value="t"), \
                mock.patch.object(f, "download_random_image", return_value=img), \
                mock.patch.object(f, "sync_playwright", return_value=pw), \
                mock.patch.object(f, "open_chat"), \
                mock.patch.object(f, "send_message_with_pic", side_effect=pic_effect) as pic, \
                mock.patch.object(f, "send_message", side_effect=text_effect) as text:
            try:
                return f.run_once(), pic, text, img
            except Exception as e:
                return e, pic, text, img

    def test_photo_path(self):
        res, pic, text, img = self.run_with()
        self.assertEqual(res, "photo")
        text.assert_not_called()
        self.assertFalse(os.path.exists(img))

    def test_photo_error_before_enter_falls_back_to_text(self):
        res, pic, text, img = self.run_with(pic_effect=RuntimeError("no attach button"))
        self.assertEqual(res, "text")
        text.assert_called_once()
        self.assertFalse(os.path.exists(img))

    def test_photo_unconfirmed_does_not_send_text(self):
        res, pic, text, img = self.run_with(pic_effect=f.SendUnconfirmed("?"))
        self.assertIsInstance(res, f.SendUnconfirmed)
        text.assert_not_called()
        self.assertFalse(os.path.exists(img))


class Extras(unittest.TestCase):
    def test_birthday_today_and_soon(self):
        with mock.patch.object(extras, "BIRTHDAYS", {(6, 10): "Тестовый"}), \
                mock.patch.object(extras, "_moscow_now", return_value=datetime(2026, 6, 9, 6)):
            self.assertEqual(extras.birthday_lines(), ["🎂 Завтра день рождения: Тестовый"])

    def test_holiday_in_date_line(self):
        with mock.patch.object(extras, "_moscow_now", return_value=datetime(2026, 5, 9, 6)):
            self.assertIn("День Победы", extras.date_line())


class Movable(unittest.TestCase):
    def test_orthodox_easter_known_years(self):
        for y, d in [(2024, date(2024, 5, 5)), (2025, date(2025, 4, 20)), (2026, date(2026, 4, 12)),
                     (2027, date(2027, 5, 2)), (2030, date(2030, 4, 28))]:
            self.assertEqual(extras.orthodox_easter(y), d)

    def test_maslenitsa_week_2026(self):
        self.assertEqual(extras.movable_holiday(date(2026, 2, 16))[0], "Масленица: Встреча")
        self.assertEqual(extras.movable_holiday(date(2026, 2, 22))[0], "Масленица: Прощёное воскресенье")
        self.assertIsNone(extras.movable_holiday(date(2026, 2, 23)))   # Clean Monday

    def test_easter_and_trinity_in_date_line(self):
        with mock.patch.object(extras, "_moscow_now", return_value=datetime(2026, 4, 12, 6)):
            self.assertIn("Пасха", extras.date_line())
        with mock.patch.object(extras, "_moscow_now", return_value=datetime(2026, 5, 31, 6)):
            self.assertIn("Троица", extras.date_line())

    def test_photo_topic_on_easter(self):
        with mock.patch.object(extras, "BIRTHDAYS", {}), \
                mock.patch.object(extras, "_moscow_now", return_value=datetime(2026, 4, 12, 6)):
            self.assertEqual(extras.pick_photo_topic(), "easter eggs")


class WeatherRules(unittest.TestCase):
    def test_ice_when_crossing_zero_after_precipitation(self):
        self.assertTrue(extras.ice_risk([(2.0, 0.4), (-1.0, 0.0)], []))

    def test_no_ice_without_precipitation(self):
        self.assertFalse(extras.ice_risk([(2.0, 0.0), (-1.0, 0.0)], []))

    def test_no_ice_when_always_above_zero(self):
        self.assertFalse(extras.ice_risk([(3.0, 2.0), (1.0, 1.0)], []))

    def test_freezing_rain_code_is_ice(self):
        self.assertTrue(extras.ice_risk([(5.0, 0.0)], [3, 66]))

    def kp(self, values):
        rows = [{"time_tag": f"2026-11-07T{h:02d}:00:00", "kp": v, "observed": "predicted", "noaa_scale": None}
                for h, v in zip(range(3, 24, 3), values)]
        resp = mock.Mock(json=mock.Mock(return_value=rows), raise_for_status=mock.Mock())
        with mock.patch.object(extras.requests, "get", return_value=resp), \
                mock.patch.object(extras, "_moscow_now", return_value=datetime(2026, 11, 7, 6)):
            return extras.kp_line()

    def test_kp_quiet_day_has_no_line(self):
        self.assertIsNone(self.kp([2.0, 3.33, 3.67]))

    def test_kp_storm_levels(self):
        self.assertIn("возмущено", self.kp([2.0, 4.0]))
        self.assertIn("буря: до 5 баллов (G1)", self.kp([4.67]))
        self.assertIn("G3", self.kp([7.0]))


class DayType(unittest.TestCase):
    def line(self, code, day):
        resp = mock.Mock(text=code, raise_for_status=mock.Mock())
        with mock.patch.object(extras.requests, "get", return_value=resp), \
                mock.patch.object(extras, "_moscow_now", return_value=datetime.combine(day, datetime.min.time())):
            return extras.day_type_line()

    def test_working_saturday(self):
        self.assertIn("рабочий день", self.line("0", date(2025, 11, 1)))

    def test_weekday_off(self):
        self.assertEqual(self.line("1", date(2026, 11, 4)), "🗓 Сегодня выходной день")

    def test_shortened_day(self):
        self.assertIn("сокращённый", self.line("2", date(2026, 11, 3)))

    def test_ordinary_days_have_no_line(self):
        self.assertIsNone(self.line("0", date(2026, 11, 9)))   # Monday
        self.assertIsNone(self.line("1", date(2026, 11, 8)))   # Sunday


def fake_get(payload):
    return mock.patch.object(extras.requests, "get", return_value=mock.Mock(
        json=mock.Mock(return_value=payload), raise_for_status=mock.Mock()))


def on(day):
    return mock.patch.object(extras, "_moscow_now", return_value=datetime.combine(day, datetime.min.time()))


class Seasonal(unittest.TestCase):
    def test_plural(self):
        self.assertEqual([extras.plural(n, ("день", "дня", "дней")) for n in (1, 2, 5, 11, 21, 24)],
                         ["день", "дня", "дней", "дней", "день", "дня"])

    def test_new_year_countdown_only_in_december(self):
        with on(date(2026, 12, 19)):
            self.assertEqual(extras.new_year_line(), "🎄 До Нового года 13 дней")
        with on(date(2026, 12, 30)):
            self.assertEqual(extras.new_year_line(), "🎄 До Нового года 2 дня")
        with on(date(2026, 12, 31)):
            self.assertIsNone(extras.new_year_line())    # the date line already says it
        with on(date(2026, 11, 30)):
            self.assertIsNone(extras.new_year_line())

    def test_name_days_from_file(self):
        with on(date(2026, 1, 25)):
            self.assertEqual(extras.nameday_line(), "😇 Именины: Татьяна")
        with on(date(2026, 1, 26)):
            self.assertIsNone(extras.nameday_line())

    def test_dacha_tip_only_in_season(self):
        with on(date(2026, 6, 1)), mock.patch.object(extras, "moon_phase", return_value="растущая луна"):
            self.assertIn("сеять", extras.dacha_line())
        with on(date(2026, 11, 1)):
            self.assertIsNone(extras.dacha_line())

    def test_uv_line_threshold(self):
        with fake_get({"daily": {"uv_index_max": [2.4]}}):
            self.assertIsNone(extras.uv_line())
        with fake_get({"daily": {"uv_index_max": [6.2]}}):
            self.assertIn("УФ-индекс 6: высокий", extras.uv_line())

    def test_pollen_levels(self):
        hourly = {"alder_pollen": [0.2], "birch_pollen": [2753.5], "grass_pollen": [6.0], "mugwort_pollen": [None]}
        with fake_get({"hourly": hourly}):
            self.assertEqual(extras.pollen_line(), "🌼 Пыльца: берёза — высокий уровень, злаки — средний")
        with fake_get({"hourly": {k: [0.0] for k in hourly}}):
            self.assertIsNone(extras.pollen_line())

    def test_weekend_line(self):
        daily = {"temperature_2m_max": [5, 4.6, 1.2], "temperature_2m_min": [1, 1.6, -2.4],
                 "weathercode": [3, 3, 73], "precipitation_probability_max": [0, 10, 70]}
        with fake_get({"daily": daily}):
            self.assertEqual(extras.weekend_line(), "📅 Выходные: сб 2…5°C, пасмурно; вс -2…1°C, снег (70%)")


class Fishing(unittest.TestCase):
    def test_good(self):
        self.assertEqual(extras.fishing_score(1, -2, 8, "убывающая луна"),
                         ("хороший", ["давление стабильное", "слабый ветер"]))

    def test_bad(self):
        self.assertEqual(extras.fishing_score(-6, -3, 35, "полнолуние")[0], "плохой")

    def test_middle(self):
        self.assertEqual(extras.fishing_score(3, 1, 20, "растущая луна"), ("средний", []))


class Images(unittest.TestCase):
    def test_purge_keeps_fresh_files(self):
        import download_pics
        with tempfile.TemporaryDirectory() as d, mock.patch.object(download_pics, "SAVE_DIR", d):
            old, fresh = os.path.join(d, "old.jpg"), os.path.join(d, "new.jpg")
            open(old, "w").close()
            open(fresh, "w").close()
            os.utime(old, (0, 0))
            self.assertEqual(download_pics.purge_old_images(), 1)
            self.assertEqual(os.listdir(d), ["new.jpg"])


class Ai(unittest.TestCase):
    def test_data_is_kept_verbatim_after_greeting(self):
        g = ai_generator.AIDescriptionGeneratorQwenVL()
        with mock.patch.object(g, "_ollama_generate", return_value="Доброе утро! ☀️"):
            self.assertEqual(g.generate_viral_description("line1\nline2"), "Доброе утро! ☀️\n\nline1\nline2")

    def test_fallback_when_model_is_down(self):
        g = ai_generator.AIDescriptionGeneratorQwenVL()
        with mock.patch.object(g, "_ollama_generate", return_value=""):
            self.assertEqual(g.generate_viral_description("data"), "Доброе утро! data")


if __name__ == "__main__":
    unittest.main()
