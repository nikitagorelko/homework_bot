import logging
import os
import sys
import time
from functools import update_wrapper
from operator import itemgetter
from typing import TypedDict

import requests
import telegram
from dotenv import load_dotenv
from telegram.error import TelegramError

from configs import HOMEWORK_VERDICTS
from exceptions import InvalidResponseStatusException

load_dotenv()

logging.basicConfig(
    level=logging.DEBUG,
    filename='homework.log',
    format='%(asctime)s - %(levelname)s - %(message)s',
)


PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

RETRY_PERIOD = 600  # 10 минут в секундах
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}


class LoggingDecorator:
    """Декоратор логирования вызова функции."""

    def __init__(self, func):
        """Инициализация экземпляра класса-декоратора."""
        update_wrapper(self, func)
        self.func = func

    def __call__(self, *args):
        """Определение экземпляра объектом, поддерживающим вызов."""
        logging.info('Вызов функции %s with args %s', self.func.__name__, args)
        return self.func(*args)


class HomeworkDict(TypedDict):
    """Класс для аннотации типов словаря домашней работы."""

    id: int
    status: str
    homework_name: str
    reviewer_comment: str
    date_updated: str
    lesson_name: str


class APIResponseDict(TypedDict):
    """Класс для аннотации типов словаря ответа API."""

    homeworks: list[HomeworkDict]
    current_date: int


def check_tokens() -> bool:
    """Проверяет доступность переменных окружения."""
    tokens = [PRACTICUM_TOKEN, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID]
    TOKENS = ('PRACTICUM_TOKEN', 'TELEGRAM_TOKEN', 'TELEGRAM_CHAT_ID')
    missing_tokens = [token for token in TOKENS if token not in globals()]
    if missing_tokens:
        logging.critical(
            'Отсутствие обязательных переменных окружения: %s',
            missing_tokens,
        )
    return all(tokens)


def send_message(bot: telegram.Bot, message: str) -> None:
    """Отправляет сообщение в Telegram чат.

    Args:
        bot: инициализированный Telegram-бот.
        message: сообщение для отправки в Telegram.
    """
    try:
        bot.send_message(TELEGRAM_CHAT_ID, message)
        logging.debug('Сообщение отправлено')
    except TelegramError as error:
        logging.error(f'Сбой при отправки сообщения: {error}')
        raise TelegramError


@LoggingDecorator
def get_api_answer(timestamp: int) -> APIResponseDict:
    """Делает запрос к единственному эндпоинту API-сервиса Практикум.Домашка.

    Args:
        timestamp: временная метка в формате Unix time для получения работ,
        которым был присвоен статус за период
        от timestamp до настоящего момента.

    Returns:
        Ответ API в формате JSON, приведенный к типам данных Python.
    """
    try:
        response = requests.get(
            ENDPOINT,
            headers=HEADERS,
            params={'from_date': timestamp},
        )
    except requests.RequestException as error:
        logging.exception('Сбой при запросе к API')
        raise error('Ошибка запроса к API')

    status_code = response.status_code
    if status_code != requests.codes.ok:
        logging.error('Эндпоинт недоступен')
        raise InvalidResponseStatusException(
            f'Ошибочный код статуса ответа: {status_code}',
        )
    return response.json()


@LoggingDecorator
def check_response(response: APIResponseDict) -> list[HomeworkDict]:
    """Проверяет ответ API на соответствие документации.

    Args:
        response: ответ API в формате JSON, приведенный к типам данных Python.

    Returns:
        Коллекция, каждым элементом которой является
        совокупность данных о домашней работе.
    """
    if (
        isinstance(response, dict)
        and all(key in response for key in ('homeworks', 'current_date'))
        and isinstance(response.get('homeworks'), list)
    ):
        logging.debug('Ответ API прошел проверку')
        return response.get('homeworks')
    raise TypeError(
        'Ответ API несоответствует документации',
    )


@LoggingDecorator
def parse_status(homework: HomeworkDict) -> str:
    """Извлекает из информации о конкретной домашней работе статус этой работы.

    Args:
        homework: данные о домашней работе.

    Returns:
        Информационное сообщение о статусе домашней работы,
        содержащее один из вердиктов словаря HOMEWORK_VERDICTS.
    """
    try:
        name, status = itemgetter('homework_name', 'status')(homework)
        verdict = HOMEWORK_VERDICTS.get(homework.get('status'))

        if status not in HOMEWORK_VERDICTS:
            logging.error('Неожиданный статус домашней работы')
            raise ValueError('Ошибка неверного статуса домашней работы')

        return f'Изменился статус проверки работы "{name}". {verdict}'
    except KeyError:
        raise KeyError('Ошибка получения ключей из данных')


def main() -> None:
    """Основная логика работы бота."""
    if not check_tokens():
        logging.critical('Отсутствие обязательных переменных окружения')
        raise ValueError('Ошибка получения токена')
        sys.exit(1)

    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    logging.debug('Бот запущен')
    timestamp = int(time.time())
    last_message = ''
    while True:
        try:
            response = get_api_answer(timestamp)
            homeworks = check_response(response)
            if homeworks:
                message = parse_status(homeworks[0])
                if last_message != message:
                    send_message(bot, message)
                    last_message = message
                    timestamp = response.get('current_date')
        except Exception as error:
            message = f'Сбой в работе программы: {error}'
            logging.error(message)
        finally:
            time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()
