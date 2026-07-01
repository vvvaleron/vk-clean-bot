import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
import random
import threading
import time
import logging
import sqlite3
import os
import requests
from datetime import datetime
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()


# ========== КОНФИГ ==========
class Config:
    # Берем токен и ID группы из переменных окружения
    TOKEN = os.getenv('VK_TOKEN',
                      "vk1.a.75-ocX_hQqgI0eQv9Sd32UFvOvmH2JXgxC_e8PehKOT3d7e5tmPVIDvoy6eXCXxnUGwojWvfaei5_2KKlHiWd4LVITjbBK6oDbVhri_PZmAuV5BIRfSPltxx-dCp960FvVYv5fdkGcDqKD4lNA6-l7j1DFhvZULpANNzNd7b-vH3Yzc1Dla_xi0Oz8gb_2cKGi4zazS0gnSHUD_lzPQ3eA")
    GROUP_ID = os.getenv('VK_GROUP_ID', "168785795")

    # ВСЕ ID ВИДЕО И ФОТО
    VIDEO_GREETING = "video-168785795_456239662"
    VIDEO_MEBEL = "video-168785795_456239650"
    VIDEO_KOVRY = "video-168785795_456239652"
    VIDEO_SHTORY = "video-168785795_456239649"
    VIDEO_OKNA = "video-168785795_456239651"
    VIDEO_WORK = "clip-168785795_456239663"

    PHOTO_BEFORE_1 = "photo-168785795_457251740"
    PHOTO_BEFORE_2 = "photo-168785795_457251739"
    PHOTO_BEFORE_3 = "photo-168785795_457251738"
    PHOTO_REMINDER = "photo-168785795_457251741"

    REMINDER_CONFIG = {
        1: {'time': 40, 'text': 'фото'},
        2: {'time': 240, 'text': '3 фото'},
        3: {'time': 1080, 'text': 'видео'},
        4: {'time': 2160, 'text': 'голосовое'},
    }


config = Config()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ========== МЕНЕДЖЕР НАПОМИНАНИЙ ==========
class ReminderManager:
    def __init__(self):
        self._timers = {}
        self._state = {}
        self._lock = threading.Lock()
        self._send_func = None
        logger.info("✅ ReminderManager готов")

    def set_send_function(self, func):
        self._send_func = func
        logger.info("📤 Функция отправки установлена")

    def is_active(self, user_id):
        with self._lock:
            return user_id in self._state and self._state[user_id].get('active', False)

    def start_reminders(self, user_id, config):
        with self._lock:
            if user_id in self._timers:
                for t in self._timers[user_id]:
                    t.cancel()
                del self._timers[user_id]

            self._state[user_id] = {
                'active': True,
                'started_at': time.time(),
                'last_activity': time.time(),
                'sent': []
            }

            timers = []
            for rid, rconf in config.items():
                delay = rconf['time'] * 60
                timer = threading.Timer(
                    delay,
                    self._send_wrapper,
                    args=[user_id, rid, rconf['text']]
                )
                timer.daemon = True
                timer.start()
                timers.append(timer)
                logger.info(f"⏰ Таймер #{rid} для {user_id} через {rconf['time']} мин")

            self._timers[user_id] = timers
            logger.info(f"✅ Система напоминаний запущена для {user_id}")

    def disable_reminders(self, user_id):
        with self._lock:
            if user_id in self._state:
                self._state[user_id]['active'] = False
                logger.info(f"🔕 Напоминания отключены для {user_id}")
            if user_id in self._timers:
                for t in self._timers[user_id]:
                    t.cancel()
                del self._timers[user_id]

    def update_activity(self, user_id):
        with self._lock:
            if user_id in self._state:
                self._state[user_id]['last_activity'] = time.time()

    def _send_wrapper(self, user_id, reminder_id, reminder_type):
        try:
            logger.info(f"🔔 Сработал таймер #{reminder_id} для {user_id}")

            with self._lock:
                state = self._state.get(user_id)
                if not state or not state.get('active', False):
                    logger.info(f"⏭️ Напоминания отключены для {user_id}")
                    return

                if time.time() - state.get('last_activity', 0) < 900:
                    logger.info(f"⏭️ Пользователь {user_id} активен - пропускаем")
                    return

                if reminder_id in state.get('sent', []):
                    logger.info(f"⏭️ Напоминание #{reminder_id} уже отправлено")
                    return

            if self._send_func:
                logger.info(f"📤 Отправка напоминания #{reminder_id} пользователю {user_id}")
                self._send_func(user_id, reminder_id, reminder_type)

                with self._lock:
                    if user_id in self._state:
                        self._state[user_id]['sent'].append(reminder_id)

                logger.info(f"✅ Напоминание #{reminder_id} отправлено")
            else:
                logger.error("❌ Функция отправки не установлена!")

        except Exception as e:
            logger.error(f"❌ Ошибка в напоминании #{reminder_id}: {e}")

    def cleanup(self):
        for user_id in list(self._timers.keys()):
            for t in self._timers[user_id]:
                t.cancel()
        self._timers.clear()
        self._state.clear()


# ========== БАЗА ДАННЫХ ==========
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('bot.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()
        logger.info("🗄️ База данных инициализирована")

    def create_tables(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                state TEXT,
                last_activity TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                service TEXT,
                order_type TEXT,
                size TEXT,
                photo_url TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS analytics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT,
                service TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                message TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self.conn.commit()
        logger.info("📋 Таблицы созданы/проверены")

    def save_user(self, user_id, name=None, state=None):
        try:
            if name:
                self.cursor.execute('''
                    INSERT OR REPLACE INTO users (user_id, name, state, last_activity)
                    VALUES (?, ?, ?, ?)
                ''', (user_id, name, state, datetime.now()))
            else:
                self.cursor.execute('''
                    INSERT OR REPLACE INTO users (user_id, state, last_activity)
                    VALUES (?, ?, ?)
                ''', (user_id, state, datetime.now()))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения пользователя {user_id}: {e}")
            return False

    def get_user(self, user_id):
        try:
            self.cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            result = self.cursor.fetchone()
            if result:
                return {
                    'user_id': result[0],
                    'name': result[1],
                    'state': result[2],
                    'last_activity': result[3],
                    'created_at': result[4]
                }
            return None
        except Exception as e:
            logger.error(f"Ошибка получения пользователя {user_id}: {e}")
            return None

    def save_order(self, user_id, service, order_type=None, size=None, photo_url=None):
        try:
            self.cursor.execute('''
                INSERT INTO orders (user_id, service, order_type, size, photo_url)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, service, order_type, size, photo_url))
            self.conn.commit()
            return self.cursor.lastrowid
        except Exception as e:
            logger.error(f"Ошибка сохранения заказа: {e}")
            return None

    def save_analytics(self, user_id, action, service=None):
        try:
            self.cursor.execute('''
                INSERT INTO analytics (user_id, action, service)
                VALUES (?, ?, ?)
            ''', (user_id, action, service))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Ошибка сохранения аналитики: {e}")

    def save_message(self, user_id, message):
        try:
            self.cursor.execute('''
                INSERT INTO messages (user_id, message)
                VALUES (?, ?)
            ''', (user_id, message))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Ошибка сохранения сообщения: {e}")

    def update_user_state(self, user_id, state):
        try:
            self.cursor.execute('''
                UPDATE users SET state = ?, last_activity = ?
                WHERE user_id = ?
            ''', (state, datetime.now(), user_id))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка обновления состояния: {e}")
            return False

    def close(self):
        self.conn.close()


# ========== ОСНОВНОЙ БОТ ==========
class VKCleanBot:
    def __init__(self):
        self.vk_session = vk_api.VkApi(token=config.TOKEN)
        self.vk = self.vk_session.get_api()
        self.longpoll = VkLongPoll(self.vk_session)
        self.db = Database()

        self.reminder_manager = ReminderManager()
        self.reminder_manager.set_send_function(self._send_reminder)

        self.user_states = {}
        self.user_orders = {}
        self.user_names = {}

        logger.info("🚀 Бот инициализирован")

    def get_user_name(self, user_id):
        if user_id in self.user_names:
            return self.user_names[user_id]
        try:
            user_info = self.vk.users.get(user_ids=user_id, fields="first_name")
            if user_info:
                name = user_info[0]['first_name']
                self.user_names[user_id] = name
                self.db.save_user(user_id, name=name)
                return name
        except Exception as e:
            logger.error(f"Ошибка получения имени: {e}")
        return "Друг"

    def get_photo_from_event(self, event):
        """Получить фото из события VK"""
        try:
            # Получаем ID сообщения
            message_id = None
            if hasattr(event, 'message_id'):
                message_id = event.message_id
            elif hasattr(event, 'message') and hasattr(event.message, 'id'):
                message_id = event.message.id

            if not message_id:
                return None, None

            response = self.vk.messages.getById(message_ids=message_id)
            if response and 'items' in response and response['items']:
                msg = response['items'][0]
                if 'attachments' in msg:
                    for att in msg['attachments']:
                        if att.get('type') == 'photo':
                            photo = att['photo']
                            owner_id = photo.get('owner_id')
                            photo_id = photo.get('id')
                            if owner_id and photo_id:
                                return f"photo{owner_id}_{photo_id}", None
            return None, None
        except Exception as e:
            logger.error(f"Ошибка получения фото: {e}")
            return None, None

    # ========== УНИВЕРСАЛЬНЫЙ МЕТОД ОТПРАВКИ ==========
    def send_message_with_attachment(self, user_id, text, attachment=None, keyboard=None):
        """Отправляет сообщение с вложением (фото/видео) одним сообщением"""
        keyboard_json = None
        if keyboard:
            keyboard_json = keyboard.get_keyboard()
        try:
            self.vk.messages.send(
                user_id=user_id,
                message=text,
                attachment=attachment,
                random_id=random.randint(1, 2 ** 31),
                keyboard=keyboard_json
            )
            logger.info(f"💬 Сообщение с вложением отправлено {user_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка отправки с вложением: {e}")
            return False

    def send_message(self, user_id, text, keyboard=None):
        keyboard_json = None
        if keyboard:
            keyboard_json = keyboard.get_keyboard()
        try:
            self.vk.messages.send(
                user_id=user_id,
                message=text,
                random_id=random.randint(1, 2 ** 31),
                keyboard=keyboard_json
            )
            logger.info(f"💬 Сообщение отправлено {user_id}")
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")

    def send_video(self, user_id, video_attachment, message="", keyboard=None):
        return self.send_message_with_attachment(user_id, message, video_attachment, keyboard)

    def send_voice_with_text(self, user_id, text, file_path="voice.ogg"):
        try:
            upload_url = self.vk.docs.getMessagesUploadServer(
                type="audio_message",
                peer_id=user_id
            )['upload_url']

            if not os.path.exists(file_path):
                logger.error(f"Файл {file_path} не найден")
                return False

            with open(file_path, 'rb') as f:
                response = requests.post(upload_url, files={'file': f})
            file_data = response.json()

            saved_doc = self.vk.docs.save(file=file_data['file'])['audio_message']
            attachment = f"doc{saved_doc['owner_id']}_{saved_doc['id']}"

            self.vk.messages.send(
                user_id=user_id,
                message=text,
                attachment=attachment,
                random_id=random.randint(1, 2 ** 31)
            )
            logger.info(f"🎙️ Голосовое с текстом отправлено {user_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка отправки голосового: {e}")
            return False

    # ========== КЛАВИАТУРЫ ==========
    def get_start_keyboard(self):
        keyboard = VkKeyboard(one_time=False)
        keyboard.add_button("НАЧАТЬ", color=VkKeyboardColor.POSITIVE)
        return keyboard

    def get_video_keyboard(self):
        keyboard = VkKeyboard(one_time=False)
        keyboard.add_button("➕", color=VkKeyboardColor.POSITIVE)
        return keyboard

    def get_reminder_keyboard(self):
        """Клавиатура для напоминаний - только главное меню"""
        keyboard = VkKeyboard(one_time=False)
        keyboard.add_button("🏠 Главное меню", color=VkKeyboardColor.PRIMARY)
        return keyboard

    def get_main_keyboard(self):
        keyboard = VkKeyboard(one_time=False)
        keyboard.add_button("🧼 Химчистка", color=VkKeyboardColor.POSITIVE)
        keyboard.add_button("🪟 Мойка окон", color=VkKeyboardColor.PRIMARY)
        keyboard.add_line()
        keyboard.add_button("🧹 Клининг", color=VkKeyboardColor.NEGATIVE)
        keyboard.add_line()
        keyboard.add_button("❓ Задать вопрос", color=VkKeyboardColor.SECONDARY)
        return keyboard

    def get_himchistka_keyboard(self):
        keyboard = VkKeyboard(one_time=False)
        keyboard.add_button("🛋️ Мебель", color=VkKeyboardColor.POSITIVE)
        keyboard.add_button("🪟 Шторы", color=VkKeyboardColor.POSITIVE)
        keyboard.add_line()
        keyboard.add_button("🧼 Ковры", color=VkKeyboardColor.POSITIVE)
        keyboard.add_line()
        keyboard.add_button("🔙 Назад", color=VkKeyboardColor.SECONDARY)
        return keyboard

    def get_shtory_keyboard(self):
        keyboard = VkKeyboard(one_time=False)
        keyboard.add_button("Плотные шторы", color=VkKeyboardColor.POSITIVE)
        keyboard.add_button("Тюль", color=VkKeyboardColor.POSITIVE)
        keyboard.add_line()
        keyboard.add_button("🔙 Назад", color=VkKeyboardColor.SECONDARY)
        return keyboard

    def get_moyka_keyboard(self):
        keyboard = VkKeyboard(one_time=False)
        keyboard.add_button("🪟 Поддерживающая мойка", color=VkKeyboardColor.PRIMARY)
        keyboard.add_line()
        keyboard.add_button("🏗️ Послестроительная мойка", color=VkKeyboardColor.PRIMARY)
        keyboard.add_line()
        keyboard.add_button("🔙 Назад", color=VkKeyboardColor.SECONDARY)
        return keyboard

    def get_klining_keyboard(self):
        keyboard = VkKeyboard(one_time=False)
        keyboard.add_button("🧹 Поддерживающая уборка", color=VkKeyboardColor.NEGATIVE)
        keyboard.add_button("🧹 Генеральная уборка", color=VkKeyboardColor.NEGATIVE)
        keyboard.add_line()
        keyboard.add_button("🏗️ Послестроительная уборка", color=VkKeyboardColor.NEGATIVE)
        keyboard.add_line()
        keyboard.add_button("🔙 Назад", color=VkKeyboardColor.SECONDARY)
        return keyboard

    def get_chat_keyboard(self):
        keyboard = VkKeyboard(one_time=False)
        keyboard.add_button("🏠 Главное меню", color=VkKeyboardColor.SECONDARY)
        return keyboard

    # ========== НАПОМИНАНИЯ ==========
    def _send_reminder(self, user_id, reminder_id, reminder_type):
        name = self.get_user_name(user_id)

        try:
            if reminder_id == 1:
                reminder_text = f"""{name}, здравствуйте! 😊
Это Рустам, руководитель компании «Служба чистоты»

Увидел, что вы пока не продолжили расчёт стоимости.

Чаще всего в такой ситуации человек либо отвлёкся, либо решил сначала посмотреть другие варианты.

Это абсолютно нормально 👍

Если у вас появились вопросы по стоимости, срокам выполнения или результату работы — просто напишите мне в ответ на это сообщение.

Лично подскажу и помогу разобраться."""

                self.send_message_with_attachment(
                    user_id,
                    reminder_text,
                    config.PHOTO_REMINDER,
                    self.get_reminder_keyboard()
                )
                self.db.save_analytics(user_id, 'reminder_1_photo')

            elif reminder_id == 2:
                reminder_text = f"""{name}, 😄

Знаете, какая самая популярная фраза наших клиентов?

"Да диван вроде чистый..."

А потом после химчистки:

"Подождите... так он был такого цвета?!"

Без шуток — многие просто привыкают к загрязнениям и перестают их замечать.

Кстати, а что Вас сейчас интересует больше всего?
▫️ Освежить внешний вид
▫️ Убрать пятна
▫️ Избавиться от запаха
▫️ Просто узнать стоимость"""

                photos = [config.PHOTO_BEFORE_1, config.PHOTO_BEFORE_2, config.PHOTO_BEFORE_3]
                attachments = ",".join(photos)

                self.send_message_with_attachment(
                    user_id,
                    reminder_text,
                    attachments,
                    self.get_reminder_keyboard()
                )
                self.db.save_analytics(user_id, 'reminder_2_3photos')

            elif reminder_id == 3:
                reminder_text = f"""{name}, привет!

Решил показать Вам небольшой фрагмент нашей работы 😊

На видео один из объектов, где сейчас заканчиваем химчистку.

Многие клиенты до обращения переживают:

"Получится ли убрать загрязнения именно у меня?"

Честно — каждый случай индивидуален.

Но по фото обычно можно довольно точно подсказать ожидаемый результат ещё до начала работ.

А какой объект нужно привести в порядок Вам?
▫️ Диван
▫️ Матрас
▫️ Окна
▫️ Шторы
▫️ Другое"""

                self.send_video(
                    user_id,
                    config.VIDEO_WORK,
                    reminder_text,
                    self.get_reminder_keyboard()
                )
                self.db.save_analytics(user_id, 'reminder_3_video')

            elif reminder_id == 4:
                reminder_text = f"""{name}, здравствуйте!

Решил написать последний раз 😊

Если вопрос пока не актуален — ничего страшного.

Сохраните наш контакт.

Очень часто люди возвращаются через неделю, месяц или даже несколько месяцев, когда действительно появляется необходимость в химчистке мебели, чистке ковров, аквачистке штор или мойке окон.

Будем рады помочь, когда понадобится."""

                if os.path.exists("voice.ogg"):
                    self.send_voice_with_text(user_id, reminder_text, "voice.ogg")
                else:
                    self.send_message_with_attachment(
                        user_id,
                        reminder_text,
                        None,
                        self.get_reminder_keyboard()
                    )
                    logger.warning(f"⚠️ Файл voice.ogg не найден, отправлено текстовое сообщение")
                self.db.save_analytics(user_id, 'reminder_4_voice')

            logger.info(f"✅ Напоминание #{reminder_id} отправлено {user_id}")

        except Exception as e:
            logger.error(f"❌ Ошибка в напоминании #{reminder_id}: {e}")

    # ========== ОСНОВНЫЕ ОБРАБОТЧИКИ ==========
    def start_reminder_system(self, user_id):
        logger.info(f"🚀 Запуск системы напоминаний для {user_id}")
        self.reminder_manager.start_reminders(user_id, config.REMINDER_CONFIG)
        logger.info(f"✅ Система напоминаний запущена для {user_id}")

    def disable_reminders(self, user_id):
        self.reminder_manager.disable_reminders(user_id)

    def handle_main_menu(self, user_id):
        self.user_states[user_id] = "main_menu"
        self.reminder_manager.update_activity(user_id)
        self.db.update_user_state(user_id, "main_menu")
        self.db.save_analytics(user_id, 'main_menu')
        self.send_message(user_id, "🏠 Выберите услугу:", self.get_main_keyboard())

    def handle_video_greeting(self, user_id):
        name = self.get_user_name(user_id)

        greeting_text = f"""{name}, здравствуйте!

Рад знакомству 😊

Перед тем как обсудить Вашу задачу, решил записать короткое видео о себе и нашей деятельности. Так гораздо приятнее общаться, чем с безликим ботом.

Мы занимаемся химчисткой мебели, мойкой окон и уборкой квартир в Пензе и области. Любим свою работу и очень ценим доверие клиентов, ведь нас часто приглашают в дом. 

Посмотрите видео, а если останутся вопросы - смело пишите в этот чат.
Подскажем, рассчитаем стоимость и поможем подобрать подходящий вариант.

📸 Просто отправьте фото мебели или помещения в этот чат, и в течение нескольких минут мы рассчитаем стоимость работ.
Расчет бесплатный и ни к чему Вас не обязывает 😇"""

        self.send_video(user_id, config.VIDEO_GREETING, greeting_text, None)
        self.user_states[user_id] = "after_video"
        self.db.update_user_state(user_id, "after_video")
        self.db.save_analytics(user_id, 'video_greeting')
        self.reminder_manager.update_activity(user_id)
        self.send_message(user_id, "➕ Нажмите + для выбора услуги", self.get_video_keyboard())

    def handle_myagkaya_mebel(self, user_id):
        self.user_states[user_id] = "waiting_photo"
        self.user_orders[user_id] = {"service": "Мягкая мебель"}
        self.db.update_user_state(user_id, "waiting_photo")
        self.db.save_analytics(user_id, 'service_selected', 'мебель')
        self.reminder_manager.update_activity(user_id)

        video_text = """📹 Перед расчётом стоимости посмотрите короткое видео.

В нём мы показываем, как проходит химчистка дивана, какие загрязнения удаляются и какой результат можно ожидать после чистки.

После просмотра просто отправьте фото вашего дивана, и менеджер рассчитает точную стоимость и ответит на все вопросы.

⏱️ Расчёт стоимости занимает всего несколько минут."""

        self.send_video(user_id, config.VIDEO_MEBEL, video_text, self.get_video_keyboard())

        keyboard = VkKeyboard(one_time=False)
        keyboard.add_button("🏠 Главное меню", color=VkKeyboardColor.SECONDARY)
        self.send_message(user_id, "📸 Отправьте фотографию Вашей мебели.", keyboard)

    def handle_shtory(self, user_id):
        self.user_states[user_id] = "shtory_menu"
        self.db.update_user_state(user_id, "shtory_menu")
        self.db.save_analytics(user_id, 'service_selected', 'шторы')
        self.reminder_manager.update_activity(user_id)

        video_text = """📹 Перед расчётом стоимости посмотрите короткое видео.

В нём мы показываем, как проходит аквачистка штор, какие загрязнения эффективно удаляются и какой результат вы получите после чистки.

После просмотра отправьте фото, размер, и тип ткани (тюль, или плотные) ваших штор, и менеджер подготовит точный расчёт стоимости и проконсультирует по всем вопросам.

⏱️ Расчёт стоимости занимает всего несколько минут."""

        self.send_video(user_id, config.VIDEO_SHTORY, video_text, self.get_video_keyboard())
        self.send_message(user_id, "🪟 Выберите тип штор:", self.get_shtory_keyboard())

    def handle_shtory_type(self, user_id, text):
        if text == "🔙 Назад":
            self.handle_himchistka(user_id)
            return

        self.user_states[user_id] = "waiting_size"
        self.user_orders[user_id] = {"service": "Шторы", "type": text}
        self.db.update_user_state(user_id, "waiting_size")
        self.db.save_analytics(user_id, 'shtory_type_selected', text)
        self.reminder_manager.update_activity(user_id)

        keyboard = VkKeyboard(one_time=False)
        keyboard.add_button("🏠 Главное меню", color=VkKeyboardColor.SECONDARY)
        self.send_message(user_id, f"📏 Напишите размер Ваших штор.", keyboard)

    def handle_carpet(self, user_id):
        self.user_states[user_id] = "waiting_size"
        self.user_orders[user_id] = {"service": "Ковры"}
        self.db.update_user_state(user_id, "waiting_size")
        self.db.save_analytics(user_id, 'service_selected', 'ковры')
        self.reminder_manager.update_activity(user_id)

        video_text = """📹 Перед расчётом стоимости рекомендуем посмотреть короткое видео.

Вы увидите, как проходит чистка ковров, какие пятна и загрязнения поддаются удалению, а также как выглядит результат после работы специалистов.

После просмотра отправьте фото ковра, его размер и получите точный расчёт стоимости.

⏱️ Расчёт стоимости занимает всего несколько минут."""

        self.send_video(user_id, config.VIDEO_KOVRY, video_text, self.get_video_keyboard())

        keyboard = VkKeyboard(one_time=False)
        keyboard.add_button("🏠 Главное меню", color=VkKeyboardColor.SECONDARY)
        self.send_message(user_id, "📏 Напишите размер Вашего ковра.", keyboard)

    def handle_photo_request(self, user_id):
        self.user_states[user_id] = "waiting_photo"
        self.db.update_user_state(user_id, "waiting_photo")
        self.db.save_analytics(user_id, 'photo_requested')
        self.reminder_manager.update_activity(user_id)

        video_text = """📹 Перед расчётом стоимости посмотрите короткое видео.

Вы увидите, как проходит профессиональная мойка окон, какие работы входят в услугу и какого результата можно ожидать после выполнения заказа.

После просмотра отправьте фото окон или краткое описание задачи, и менеджер рассчитает точную стоимость работ.

⏱️ Расчёт стоимости занимает всего несколько минут."""

        self.send_video(user_id, config.VIDEO_OKNA, video_text, self.get_video_keyboard())

        keyboard = VkKeyboard(one_time=False)
        keyboard.add_button("🏠 Главное меню", color=VkKeyboardColor.SECONDARY)
        self.send_message(user_id, "📸 Отправьте фотографию Ваших окон.", keyboard)

    def handle_photo_received(self, user_id, photo_url=None, photo_id=None):
        self.disable_reminders(user_id)
        service = self.user_orders.get(user_id, {}).get('service', 'Неизвестно')
        self.db.save_order(user_id=user_id, service=service, photo_url=photo_url)
        self.user_states[user_id] = "chat_with_manager"
        self.db.update_user_state(user_id, "chat_with_manager")
        self.db.save_analytics(user_id, 'photo_received', service)
        self.reminder_manager.update_activity(user_id)
        self.send_message(user_id, "✅ Фото получили! Ожидайте ответ менеджера (обычно в течение 15 минут).",
                          self.get_chat_keyboard())

    def handle_size_received(self, user_id, text):
        self.disable_reminders(user_id)
        order_data = self.user_orders.get(user_id, {})
        self.db.save_order(
            user_id=user_id,
            service=order_data.get('service', 'Неизвестно'),
            order_type=order_data.get('type'),
            size=text
        )
        self.user_states[user_id] = "chat_with_manager"
        self.db.update_user_state(user_id, "chat_with_manager")
        self.db.save_analytics(user_id, 'size_received', order_data.get('service'))
        self.reminder_manager.update_activity(user_id)
        self.send_message(user_id, f"✅ Размер получили ({text}). Ожидайте ответ менеджера (обычно в течение 15 минут).",
                          self.get_chat_keyboard())

    def handle_question(self, user_id, text):
        self.disable_reminders(user_id)
        if text == "🔙 Отмена":
            self.handle_main_menu(user_id)
            return
        self.user_states[user_id] = "chat_with_manager"
        self.db.update_user_state(user_id, "chat_with_manager")
        self.db.save_analytics(user_id, 'question_asked')
        self.reminder_manager.update_activity(user_id)
        self.send_message(user_id, "✅ Ваш вопрос отправлен. Ожидайте ответ менеджера (обычно в течение 15 минут).",
                          self.get_chat_keyboard())

    def handle_himchistka(self, user_id):
        self.user_states[user_id] = "himchistka_menu"
        self.db.update_user_state(user_id, "himchistka_menu")
        self.db.save_analytics(user_id, 'service_category', 'химчистка')
        self.reminder_manager.update_activity(user_id)
        self.send_message(user_id, "🧼 Выберите, что нужно почистить:", self.get_himchistka_keyboard())

    def handle_moyka(self, user_id):
        self.user_states[user_id] = "moyka_menu"
        self.db.update_user_state(user_id, "moyka_menu")
        self.db.save_analytics(user_id, 'service_category', 'мойка окон')
        self.reminder_manager.update_activity(user_id)
        self.send_message(user_id, "🪟 Выберите тип мойки окон:", self.get_moyka_keyboard())

    def handle_klining(self, user_id):
        self.user_states[user_id] = "klining_menu"
        self.db.update_user_state(user_id, "klining_menu")
        self.db.save_analytics(user_id, 'service_category', 'клининг')
        self.reminder_manager.update_activity(user_id)
        self.send_message(user_id, "🧹 Выберите тип уборки:", self.get_klining_keyboard())

    def handle_klining_type(self, user_id, text):
        if text == "🔙 Назад":
            self.handle_main_menu(user_id)
            return
        self.user_states[user_id] = "waiting_photo"
        self.user_orders[user_id] = {"service": f"Клининг: {text}"}
        self.db.update_user_state(user_id, "waiting_photo")
        self.db.save_analytics(user_id, 'klining_type_selected', text)
        self.reminder_manager.update_activity(user_id)
        keyboard = VkKeyboard(one_time=False)
        keyboard.add_button("🏠 Главное меню", color=VkKeyboardColor.SECONDARY)
        self.send_message(user_id, "📸 Отправьте фотографию помещения.", keyboard)

    # ========== ГЛАВНЫЙ ОБРАБОТЧИК ==========
    def process_message(self, user_id, text, event=None):
        self.reminder_manager.update_activity(user_id)

        user_data = self.db.get_user(user_id)

        if not user_data:
            logger.info(f"👤 Новый пользователь {user_id}")
            if user_id in self.user_states: del self.user_states[user_id]
            if user_id in self.user_orders: del self.user_orders[user_id]
            if user_id in self.user_names: del self.user_names[user_id]

            self.db.save_user(user_id, state="awaiting_start")
            self.user_states[user_id] = "awaiting_start"
            self.start_reminder_system(user_id)

            if text.strip().lower() == "начать":
                self.handle_video_greeting(user_id)
            else:
                self.send_message(user_id, "👋 Нажмите 'НАЧАТЬ'", self.get_start_keyboard())
            return

        state = self.user_states.get(user_id, "awaiting_start")
        logger.info(f"📩 {user_id}: {text[:30]} (состояние: {state})")

        if not self.reminder_manager.is_active(user_id) and state in ["awaiting_start", "after_video"]:
            logger.info(f"🔄 Напоминания не активны для {user_id} - запускаю!")
            self.start_reminder_system(user_id)

        if state == "chat_with_manager":
            if text == "🏠 Главное меню":
                self.handle_main_menu(user_id)
            else:
                self.db.save_message(user_id, text)
            return

        if state == "awaiting_start":
            if text.strip().lower() == "начать":
                self.handle_video_greeting(user_id)
            else:
                self.send_message(user_id, "👋 Нажмите 'НАЧАТЬ'", self.get_start_keyboard())
            return

        if state == "after_video":
            if text == "➕":
                self.handle_main_menu(user_id)
            else:
                self.send_message(user_id, "➕ Нажмите +", self.get_video_keyboard())
            return

        if state == "main_menu":
            if text == "🧼 Химчистка":
                self.handle_himchistka(user_id)
            elif text == "🪟 Мойка окон":
                self.handle_moyka(user_id)
            elif text == "🧹 Клининг":
                self.handle_klining(user_id)
            elif text == "❓ Задать вопрос":
                self.user_states[user_id] = "asking_question"
                self.db.update_user_state(user_id, "asking_question")
                self.send_message(user_id, "💬 Напишите Ваш вопрос. Менеджер ответит Вам в ближайшее время.")
            else:
                self.disable_reminders(user_id)
                self.user_states[user_id] = "chat_with_manager"
                self.db.update_user_state(user_id, "chat_with_manager")
                self.db.save_message(user_id, text)
                self.send_message(user_id, "✅ Ваше сообщение передано менеджеру. Ожидайте ответа.",
                                  self.get_chat_keyboard())
            return

        if state == "himchistka_menu":
            if text == "🔙 Назад":
                self.handle_main_menu(user_id)
            elif text == "🛋️ Мебель":
                self.handle_myagkaya_mebel(user_id)
            elif text == "🪟 Шторы":
                self.handle_shtory(user_id)
            elif text == "🧼 Ковры":
                self.handle_carpet(user_id)
            else:
                self.disable_reminders(user_id)
                self.user_states[user_id] = "chat_with_manager"
                self.db.update_user_state(user_id, "chat_with_manager")
                self.db.save_message(user_id, text)
                self.send_message(user_id, "✅ Ваше сообщение передано менеджеру. Ожидайте ответа.",
                                  self.get_chat_keyboard())
            return

        if state == "shtory_menu":
            if text == "🔙 Назад":
                self.handle_himchistka(user_id)
            elif text in ["Плотные шторы", "Тюль"]:
                self.handle_shtory_type(user_id, text)
            else:
                self.disable_reminders(user_id)
                self.user_states[user_id] = "chat_with_manager"
                self.db.update_user_state(user_id, "chat_with_manager")
                self.db.save_message(user_id, text)
                self.send_message(user_id, "✅ Ваше сообщение передано менеджеру. Ожидайте ответа.",
                                  self.get_chat_keyboard())
            return

        if state == "moyka_menu":
            if text == "🔙 Назад":
                self.handle_main_menu(user_id)
            elif text in ["🪟 Поддерживающая мойка", "🏗️ Послестроительная мойка"]:
                self.handle_photo_request(user_id)
            else:
                self.disable_reminders(user_id)
                self.user_states[user_id] = "chat_with_manager"
                self.db.update_user_state(user_id, "chat_with_manager")
                self.db.save_message(user_id, text)
                self.send_message(user_id, "✅ Ваше сообщение передано менеджеру. Ожидайте ответа.",
                                  self.get_chat_keyboard())
            return

        if state == "klining_menu":
            if text == "🔙 Назад":
                self.handle_main_menu(user_id)
            elif text in ["🧹 Поддерживающая уборка", "🧹 Генеральная уборка", "🏗️ Послестроительная уборка"]:
                self.handle_klining_type(user_id, text)
            else:
                self.disable_reminders(user_id)
                self.user_states[user_id] = "chat_with_manager"
                self.db.update_user_state(user_id, "chat_with_manager")
                self.db.save_message(user_id, text)
                self.send_message(user_id, "✅ Ваше сообщение передано менеджеру. Ожидайте ответа.",
                                  self.get_chat_keyboard())
            return

        if state == "waiting_photo":
            if text == "🏠 Главное меню" or text == "🔙 Назад":
                self.handle_main_menu(user_id)
                return

            photo_id, photo_url = self.get_photo_from_event(event) if event else (None, None)
            if photo_id:
                self.user_orders[user_id]['photo_url'] = photo_url
                self.user_orders[user_id]['photo_id'] = photo_id
                self.handle_photo_received(user_id, photo_url, photo_id)
            else:
                self.disable_reminders(user_id)
                self.user_states[user_id] = "chat_with_manager"
                self.db.update_user_state(user_id, "chat_with_manager")
                self.db.save_message(user_id, text)
                self.send_message(user_id, "✅ Ваше сообщение передано менеджеру. Ожидайте ответа.",
                                  self.get_chat_keyboard())
            return

        if state == "waiting_size":
            if text == "🏠 Главное меню" or text == "🔙 Назад":
                self.handle_main_menu(user_id)
            elif text.strip():
                self.handle_size_received(user_id, text)
            else:
                self.send_message(user_id, "📏 Пожалуйста, напишите размер.")
            return

        if state == "asking_question":
            if text == "🔙 Отмена":
                self.handle_main_menu(user_id)
            else:
                self.handle_question(user_id, text)
            return

        self.user_states[user_id] = "awaiting_start"
        self.db.update_user_state(user_id, "awaiting_start")
        self.send_message(user_id, "👋 Нажмите 'НАЧАТЬ'", self.get_start_keyboard())

    # ========== ЗАПУСК ==========
    def run(self):
        logger.info("=" * 60)
        logger.info("🚀 Бот «Служба Чистоты» запущен!")
        logger.info(f"⏰ Напоминания через: 40 мин, 4 ч, 18 ч, 36 ч")
        logger.info("=" * 60)
        logger.info("⏳ Ожидание сообщений...")

        try:
            for event in self.longpoll.listen():
                if event.type == VkEventType.MESSAGE_NEW and event.to_me:
                    user_id = event.user_id
                    if hasattr(event.message, 'text'):
                        text = event.message.text
                    else:
                        text = str(event.message)

                    has_attachments = False
                    if hasattr(event, 'attachments') and event.attachments:
                        has_attachments = True
                    elif hasattr(event.message, 'attachments') and event.message.attachments:
                        has_attachments = True

                    if not text.strip() and not has_attachments:
                        continue

                    logger.info(f"📩 Сообщение от {user_id}: {text[:30]}...")
                    self.process_message(user_id, text, event)

        except KeyboardInterrupt:
            logger.info("⏹️ Бот остановлен")
        except Exception as e:
            logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
        finally:
            self.cleanup()

    def cleanup(self):
        logger.info("🧹 Очистка ресурсов...")
        self.reminder_manager.cleanup()
        self.db.close()
        logger.info("✅ Бот остановлен")


if __name__ == "__main__":
    bot = VKCleanBot()
    bot.run()ыыыыыыыыы