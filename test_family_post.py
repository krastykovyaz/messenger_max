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
        # never reach a real standby from a test, whatever the local .env says
        mock.patch.object(f, "STANDBY_HOST", None).start()
        mock.patch.object(f, "ROLE", "primary").start()

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


class Standby(Base):
    def setUp(self):
        super().setUp()
        mock.patch.object(f, "ROLE", "standby").start()
        mock.patch.object(f, "POST_MINUTE", 40).start()
        mock.patch.object(f, "PRIMARY_MARKER", os.path.join(self.tmp.name, "primary_done")).start()

    def test_waits_until_six_forty(self):
        with self.now(at(6, 10)):
            self.assertEqual(f.seconds_until_post(), 30 * 60)

    def test_marker_from_primary_skips_without_touching_max(self):
        with open(f.PRIMARY_MARKER, "w") as fh:
            fh.write("2026-11-07")
        with self.now(at(6, 40)), mock.patch.object(f, "run_once") as run:
            f.post_today()
        run.assert_not_called()
        self.alert.assert_not_called()
        with self.now(at(6, 41)):
            self.assertTrue(f.posted_today())

    def test_yesterdays_marker_does_not_count(self):
        with open(f.PRIMARY_MARKER, "w") as fh:
            fh.write("2026-11-06")
        with self.now(at(6, 40)), mock.patch.object(f, "run_once", return_value="photo") as run:
            f.post_today()
        run.assert_called_once()

    def test_post_already_in_chat_is_not_sent_again(self):
        with self.now(at(6, 40)), mock.patch.object(f, "run_once", return_value="already"):
            f.post_today()
        self.hb.assert_not_called()
        self.assertIn("Повторно не отправляю", self.alert.call_args[0][0])

    def test_standby_post_alerts_and_does_not_notify(self):
        with self.now(at(6, 40)), mock.patch.object(f, "run_once", return_value="photo"), \
                mock.patch.object(f, "subprocess") as sp:
            f.post_today()
        self.hb.assert_called_once()
        self.assertIn("резервный сервер horek_fi", self.alert.call_args[0][0])
        sp.run.assert_not_called()


class PrimaryNotify(Base):
    def setUp(self):
        super().setUp()
        mock.patch.object(f, "ROLE", "primary").start()
        mock.patch.object(f, "STANDBY_HOST", "familypost@standby").start()
        self.sp = mock.patch.object(f, "subprocess").start()
        self.sp.run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

    def test_confirmed_post_writes_marker_then_syncs_login(self):
        with self.now(at(6)), mock.patch.object(f, "run_once", return_value="photo"):
            f.post_today()
        cmds = [c.args[0] for c in self.sp.run.call_args_list]
        self.assertEqual(len(cmds), 2)
        self.assertIn("echo 2026-11-07 > family_post/state/primary_done", cmds[0][-1])
        self.assertEqual(cmds[1][0], "rsync")
        self.assertIn("--exclude=*Cache*", cmds[1])
        self.assertIn("StrictHostKeyChecking=accept-new", cmds[0])
        self.alert.assert_not_called()

    def test_unconfirmed_send_leaves_no_marker(self):
        with self.now(at(6)), mock.patch.object(f, "run_once", side_effect=f.SendUnconfirmed("?")):
            f.post_today()
        self.sp.run.assert_not_called()

    def test_total_failure_leaves_no_marker(self):
        with self.now(at(6)), mock.patch.object(f, "run_once", side_effect=RuntimeError("down")):
            f.post_today()
        self.sp.run.assert_not_called()

    def test_no_attempt_after_the_deadline_leaves_the_day_to_the_standby(self):
        with self.now(at(6, 30)), mock.patch.object(f, "run_once") as run:
            f.post_today()
        run.assert_not_called()
        self.sp.run.assert_not_called()                  # no marker: the standby must post
        self.assertIn("резервный сервер horek_fi в 06:40", self.alert.call_args[0][0])

    def test_retries_stop_at_the_deadline(self):
        times = iter([at(6, 20), at(6, 20), at(6, 25), at(6, 25), at(6, 31), at(6, 31)])
        with mock.patch.object(f, "moscow_now", side_effect=lambda: next(times, at(6, 31))), \
                mock.patch.object(f, "run_once", side_effect=RuntimeError("down")) as run:
            f.post_today()
        self.assertEqual(run.call_count, 2)              # 06:20 and 06:25, not 06:31
        self.sp.run.assert_not_called()

    def test_ssh_warning_is_not_reported_as_the_error(self):
        self.sp.run.return_value = mock.Mock(returncode=255, stdout="", stderr=(
            "Warning: Permanently added '1.2.3.4' (ECDSA) to the list of known hosts.\n"
            "familypost@1.2.3.4: Permission denied (publickey).\n"))
        with self.now(at(6)), mock.patch.object(f, "run_once", return_value="photo"):
            f.post_today()
        self.assertIn("Permission denied", self.alert.call_args[0][0])
        self.assertNotIn("Permanently added", self.alert.call_args[0][0])

    def test_unreachable_standby_alerts_but_post_counts(self):
        self.sp.run.return_value = mock.Mock(returncode=255, stdout="", stderr="Connection timed out")
        with self.now(at(6)), mock.patch.object(f, "run_once", return_value="photo"):
            f.post_today()
        self.hb.assert_called_once()
        self.assertEqual(self.sp.run.call_count, 1)     # gives up after the marker step
        self.assertIn("резервный сервер", self.alert.call_args[0][0])
        with self.now(at(6, 1)):
            self.assertTrue(f.posted_today())


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


class Clothing(unittest.TestCase):
    def advice(self, feels, t_min=0, t_max=4, wind=10, rain=False, snow=False, ice=False, uv=None):
        return extras.clothing_advice(feels, t_min, t_max, wind, rain, snow, ice, uv)

    def test_bands_follow_feels_like(self):
        self.assertIn("тёплая куртка, шапка, перчатки", self.advice(-1))
        self.assertIn("демисезонная куртка", self.advice(3.4))
        self.assertIn("лёгкая куртка или плотная толстовка", self.advice(9))
        self.assertIn("зимняя куртка, шапка, перчатки, шарф", self.advice(-7))
        self.assertIn("пуховик", self.advice(-25))
        self.assertIn("лёгкая одежда", self.advice(27))

    def test_feels_like_is_shown_with_a_real_minus(self):
        self.assertTrue(self.advice(-1.4).startswith("Рекомендация по одежде (ощущается как −1°C): "))
        self.assertIn("(ощущается как 3°C)", self.advice(3.4))

    def test_add_ons(self):
        line = self.advice(-1, t_min=-2, t_max=7, wind=40, rain=True, ice=True, uv=None)
        for part in ("непромокаемая куртка и обувь, зонт", "нескользящей подошвой",
                     "закрытая от ветра", "оденьтесь слоями"):
            self.assertIn(part, line)

    def test_snow_replaces_rain_advice(self):
        line = self.advice(-4, rain=True, snow=True)
        self.assertIn("зимняя обувь", line)
        self.assertNotIn("зонт", line)

    def test_summer_sun(self):
        self.assertIn("кепка и солнцезащитные очки", self.advice(24, t_min=18, t_max=25, uv=7))

    def test_clothing_line_from_forecast(self):
        hours = [f"2026-11-11T{h:02d}:00" for h in range(24)]
        payload = {"hourly": {
            "time": ["2026-11-10T12:00"] + hours,
            "temperature_2m": [4.0] + [2.0] * 24,
            "apparent_temperature": [1.0] + [-1.2] * 24,
            "precipitation": [0.0] + [0.0] * 24,
            "snowfall": [0.0] + [0.0] * 24,
            "precipitation_probability": [0] + [10] * 24,
            "weathercode": [3] + [3] * 24,
            "windspeed_10m": [10.0] + [12.0] * 24},
            "daily": {"uv_index_max": [0.6]}}
        with fake_get(payload), on(date(2026, 11, 11)):
            self.assertEqual(extras.clothing_line(),
                             "Рекомендация по одежде (ощущается как −1°C): тёплая куртка, шапка, перчатки")

    def test_message_falls_back_to_the_old_tip(self):
        with mock.patch.object(f, "get_weather_summary", return_value=(["СПб: 1…3°C"], "лёгкая куртка или толстовка")), \
                mock.patch.object(f, "build_extras", return_value=([], [])), \
                mock.patch.object(f, "clothing_line", side_effect=RuntimeError("503")), \
                mock.patch.object(f.AIDescriptionGeneratorQwenVL, "generate_viral_description", side_effect=lambda original_text: original_text):
            self.assertIn("Рекомендация по одежде: лёгкая куртка или толстовка", f.build_message_with_ai())


SPB_QUARTERS = ("Школа", [
    ("term", "1-я четверть", date(2026, 9, 1), date(2026, 10, 25)),
    ("holiday", "осенние каникулы", date(2026, 10, 26), date(2026, 11, 3)),
    ("term", "2-я четверть", date(2026, 11, 5), date(2026, 12, 30)),
    ("holiday", "зимние каникулы", date(2026, 12, 31), date(2027, 1, 10)),
    ("term", "3-я четверть", date(2027, 1, 11), date(2027, 3, 26)),
    ("holiday", "весенние каникулы", date(2027, 3, 27), date(2027, 4, 4)),
    ("term", "4-я четверть", date(2027, 4, 5), date(2027, 5, 26)),
    ("holiday", "летние каникулы", date(2027, 5, 27), date(2027, 8, 31)),
])


class School(unittest.TestCase):
    def line(self, y, m, d):
        with mock.patch.object(extras, "_load_school", return_value=SPB_QUARTERS):
            return extras.school_line(date(y, m, d))

    def test_mid_quarter_with_countdown(self):
        self.assertEqual(self.line(2026, 11, 13), "🏫 Школа: 2-я четверть, 2-я неделя · до зимних каникул 48 дней")

    def test_last_week_is_assessment(self):
        self.assertEqual(self.line(2026, 10, 19),
                         "🏫 Школа: 1-я четверть, 8-я неделя · до осенних каникул 7 дней · последняя неделя — аттестация")

    def test_last_school_day_is_friday_before_a_sunday_end(self):
        self.assertEqual(self.line(2026, 10, 23), "🔔 Школа: последний учебный день — с завтрашнего дня осенние каникулы!")

    def test_holidays(self):
        self.assertEqual(self.line(2026, 10, 26), "🏖 Школа: начались осенние каникулы! В школу — 5 ноября")
        self.assertEqual(self.line(2026, 10, 30), "🏖 Школа: осенние каникулы · в школу через 6 дней")
        self.assertEqual(self.line(2026, 12, 31), "🏖 Школа: начались зимние каникулы! В школу — 11 января")

    def test_back_to_school(self):
        self.assertEqual(self.line(2026, 11, 4), "🔔 Школа: завтра снова в школу — начинается 2-я четверть")   # public holiday gap
        self.assertEqual(self.line(2027, 1, 10), "🔔 Школа: завтра снова в школу — начинается 3-я четверть")
        self.assertEqual(self.line(2027, 1, 11), "🔔 Школа: сегодня начинается 3-я четверть — хорошего начала!")

    def test_end_of_year_and_summer(self):
        self.assertEqual(self.line(2027, 5, 26), "🔔 Школа: последний учебный день — с завтрашнего дня летние каникулы!")
        self.assertEqual(self.line(2027, 6, 15), "🏖 Школа: летние каникулы до 31 августа")
        self.assertIsNone(self.line(2027, 9, 5))     # past the calendar

    def test_no_file_no_line(self):
        with mock.patch.object(extras, "_load_school", return_value=None):
            self.assertIsNone(extras.school_line(date(2026, 11, 13)))

    def test_renewal_reminder_two_weeks_before_the_end(self):
        with mock.patch.object(extras, "_load_school", return_value=SPB_QUARTERS):
            self.assertTrue(extras.school_calendar_expiring(date(2027, 8, 17)))
            self.assertFalse(extras.school_calendar_expiring(date(2027, 8, 16)))


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
