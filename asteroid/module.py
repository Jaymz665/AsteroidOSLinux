import time
import logging
import queue
import threading
import mpd
import pydbus as dbus
from asteroid import Asteroid, DBusEavesdropper, WeatherPredictions
from gi.repository import GLib


def merge_dicts(first, second):
    """ Recursively deep merges two dictionaries """
    ret = first.copy()
    for k, v in second.items():
        if isinstance(v, dict) and k in first and isinstance(first[k], dict):
            ret[k] = merge_dicts(first[k], v)
        else:
            ret[k] = v
    return ret


class MetaModule(type):

    def __init__(self, name, bases, dict_):
        self.logger = logging.getLogger(name)


class Module(metaclass=MetaModule):

    defconfig = dict()

    def __init__(self, **kwargs):
        self.config = merge_dicts(self.defconfig, kwargs)

    def register(self, app):
        self.app = app
        self.asteroid = app.asteroid
        self.asteroid.dev.properties_changed.connect(self._properties_changed)

    def _properties_changed(self, name, changed, lst):
        pass


class TimeSyncModule(Module):

    def register(self, app):
        super(TimeSyncModule, self).register(app)
        # We want to do this on startup, but as the dbus-is-blocking issues is
        # not solved yet, be careful
        if self.asteroid.dev.connected:
            self._update_time()

    def _update_time(self):
        self.asteroid.update_time()
        self.logger.info("Time synchronized")

    def _properties_changed(self, name, changed, lst):
        if changed.get("Connected", False):
            self._update_time()


class ReconnectModule(Module):

    defconfig = {"timeout_base": 5,
                 "timeout_max": 300,
                 "timeout_reset": 120}

    def __init__(self, **kwargs):
        super(ReconnectModule, self).__init__(**kwargs)
        self._last_connected = 0.0
        self._timeout = 0
        self._condvar = threading.Condition()
        self._thread = threading.Thread(target=self._reconnect_fn)
        self._thread.daemon = True

    def register(self, app):
        super(ReconnectModule, self).register(app)
        self._thread.start()

    def _reconnect_fn(self):
        while True:
            self._condvar.acquire()
            while self.asteroid.dev.connected:
                self._condvar.wait(10)
            self._condvar.release()
            dt = time.time() - self._last_connected
            if dt > self.config["timeout_reset"]:
                self._timeout = 0
            if self._timeout > 0:
                self.logger.info("Reconnecting in %d seconds..." % self._timeout)
                time.sleep(self._timeout)
            else:
                self.logger.info("Reconnecting...")
            self.asteroid.connect()
            self._timeout = min(self._timeout + self.config["timeout_base"],
                                self.config["timeout_max"])
            self.logger.info("Connected!")

    def _properties_changed(self, name, changed, lst):
        if not changed.get("Connected", True):
            self._condvar.acquire()
            self._condvar.notify()
            self._condvar.release()
        elif changed.get("Connected", False):
            self._last_connected = time.time()


class NotifyModule(Module):

    def register(self, app):
        super(NotifyModule, self).register(app)
        self._pending = queue.Queue()
        self._eavesdropper = DBusEavesdropper(
                                    dbus.SessionBus(),
                                    "org.freedesktop.Notifications",
                                    "Notify",
                                    self._on_notification)

    def _notification_send(self):
        try:
            msg = self._pending.get_nowait()
            app_name, id_, app_icon, summary, body, actions, hints, \
                expiration = msg.get_body()
            self.asteroid.notify(summary, body=body,
                                 id_=(id_ if id_ else None),
                                 app_name=app_name, app_icon=app_icon)
            self.logger.info("Sent notification '%s'" % summary)
        except queue.Empty:
            pass
        return bool(self._pending.qsize())

    def _on_notification(self, msg):
        self._pending.put(msg)
        GLib.idle_add(self._notification_send)


import subprocess
from urllib.parse import quote_plus

import subprocess
from urllib.parse import quote_plus

class WeatherModule(Module):
    
    def __init__(self):
        self.config = {"update_interval": 2 * 60 * 60}
        
        # Словарь для перевода эмодзи в числовые коды
        self.weather_emojis = {
            "🌞": 800,     # Sunny
            "❄️": 602,     # Moderate snow
            "☔️": 500,     # Light rain
            "⛈": 501,      # Heavy rain
            "⚡": 200       # Thunderstorm
        }

    def register(self, app):
        super(WeatherModule, self).register(app)
        self._update_weather()
        GLib.timeout_add_seconds(self.config["update_interval"], self._update_weather)

    def _update_weather(self):
        try:
            # Получаем температуру через curl
            city_name = "Новгород"
            encoded_city = quote_plus(city_name)  # Кодируем название города для URL
            command = f'curl "https://wttr.in/{encoded_city}?format=%t"'
            result = subprocess.run(command, shell=True, capture_output=True, text=True)
            
            if result.returncode == 0:
                temperature_str = result.stdout.strip()  # Убираем лишние пробелы и символы новой строки
                temperature_c = float(temperature_str[:-2])   # Преобразуем строку в число, удаляя последние два символа (°C)
                
                # Преобразуем значение температуры из Цельсия в Кельвины
                temperature_k = temperature_c + 273.15
                
                # Создаем объект WeatherPredictions с полученными данными
                weather_ids = [self.weather_emojis.get(emoji) for emoji in self.weather_emojis.keys()]
                min_temp = [temperature_k] * len(weather_ids)  # Одинаковая минимальная температура для всех прогнозов
                max_temp = [temperature_k] * len(weather_ids)  # Одинаковая максимальная температура для всех прогнозов
                
                predictions = WeatherPredictions(city_name)
                for i in range(len(weather_ids)):
                    predictions.append_prediction(weather_ids[i], min_temp[i], max_temp[i])
                
                # Обновляем погоду на устройстве
                self.asteroid.update_weather(predictions)
                self.logger.info(f"Weather update sent for {city_name}: {temperature_c:.1f}C ({temperature_k:.1f}K)")
            else:
                self.logger.error(f"Failed to get weather data for {city_name}")
        except Exception as e:
            self.logger.exception(e)

    def _convert_to_celsius(self, temp_k):
        return temp_k - 273.15

    def _convert_to_kelvin(self, temp_c):
        return temp_c + 273.15


class MPDModule(Module):

    defconfig = {
        "host": "127.0.0.1",
        "port": 6600,
        "reconnect_period": 5
    }

    def __init__(self, **kwargs):
        super(MPDModule, self).__init__(**kwargs)
        self._mpd_watch = self._make_mpd(connect=False)

    def _properties_changed(self, name, changed, lst):
        if changed.get("Connected", False):
            self._send_update()

    def _make_mpd(self, connect=True):
        cl = mpd.MPDClient()
        cl.timeout = 10
        if connect:
            cl.connect(self.config["host"], self.config["port"])
        return cl

    def register(self, app):
        super(MPDModule, self).register(app)
        self.asteroid.register_media_listener(self._command_cb)
        GLib.timeout_add_seconds(self.config["reconnect_period"], self._mpd_reconnect)

    def _mpd_connection_error_cb(self, src=None, cond=None):
        self.logger.warn("MPD connection error, scheduling reconnect")
        GLib.timeout_add_seconds(self.config["reconnect_period"],
                                 self._mpd_reconnect)
        return False

    def _mpd_reconnect(self):
        try:
            self._mpd_watch.connect(self.config["host"], self.config["port"])
        except ConnectionRefusedError as e:
            return True
        except mpd.ConnectionError:
            return False
        self.logger.info("MPD connected")
        self._send_update()
        self._mpd_watch.send_idle()
        GLib.io_add_watch(self._mpd_watch, GLib.IO_ERR | GLib.IO_HUP | GLib.IO_NVAL,
                          self._mpd_connection_error_cb)
        GLib.io_add_watch(self._mpd_watch, GLib.IO_IN, self._mpd_cb)
        return False

    def _send_update(self):
        try:
            song = self._mpd_watch.currentsong()
            status = self._mpd_watch.status()
            self.asteroid.update_media(
                song.get("title", "Unknown"),
                song.get("album", "Unknown"),
                song.get("artist", "Unknown"),
                status["state"] == "play"
            )
        except mpd.ConnectionError as e:
            self.logger.warn("Attempt to update MPD status failed with %r" % e)

    def _mpd_cb(self, src, cond):
        try:
            changes = self._mpd_watch.fetch_idle()
            if "player" in changes:
                self._send_update()
            self._mpd_watch.send_idle()
        except (mpd.ConnectionError, mpd.PendingCommandError) as e:
            self.logger.warn("MPD idle fetch failed with %r" % e)
            return False
        return True

    def _command_cb(self, cmd):
        try:
            mpd = self._make_mpd()
            if cmd == Asteroid.MEDIA_COMMAND_PREVIOUS:
                mpd.previous()
            elif cmd == Asteroid.MEDIA_COMMAND_NEXT:
                mpd.next()
            elif cmd == Asteroid.MEDIA_COMMAND_PLAY:
                mpd.play()
            elif cmd == Asteroid.MEDIA_COMMAND_PAUSE:
                mpd.pause()
            else:
                self.logger.error("Unknown media command code %02x" % cmd)
            mpd.close()
        except Exception as e:
            self.logger.warn("Attempted to send media command %02x but failed with %r" % (cmd, e))
